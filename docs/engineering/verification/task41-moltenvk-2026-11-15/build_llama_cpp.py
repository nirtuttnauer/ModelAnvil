#!/usr/bin/env python3
"""Build pinned llama.cpp without CMake, as CPU-only or CPU+Vulkan; Metal and BLAS are never compiled.

This host had no CMake and installing one was outside the authorised scope, so this script
reproduces the upstream CMake configuration for this commit by hand:

  cmake -B BUILD -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DGGML_METAL=OFF \
        -DGGML_BLAS=OFF -DLLAMA_OPENSSL=OFF -DGGML_VULKAN=ON|OFF   (GGML_NATIVE, ACCELERATE,
        LLAMAFILE, CPU_REPACK, LLAMA_SUBPROCESS left at their defaults; UI assets omitted)

It mirrors the definitions, include directories, ARM feature probes, Vulkan glslc extension
probes and vulkan-shaders-gen steps of ggml/src/CMakeLists.txt, ggml/src/ggml-cpu/CMakeLists.txt,
ggml/src/ggml-vulkan/CMakeLists.txt, src/, common/, vendor/, tools/mtmd, tools/server, tools/ui
(empty asset table: the server must run with --no-webui), the completion/quantize/bench tools
and tests/test-backend-ops (linked against ggml only).

usage: build_llama_cpp.py --source LLAMA_SRC --build OUT --vulkan on|off [--jobs N]
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

COMMIT = 'f5027fb21307eb264aed483242603d68c87b0fe3'
CC, CXX = '/usr/bin/clang', '/usr/bin/clang++'
BREW = Path('/opt/homebrew')
GLSLC = BREW / 'bin/glslc'
OPT = ['-O3', '-DNDEBUG', '-Xclang', '-fno-pch-timestamp']
TOOLS = ('llama-server', 'llama-completion', 'llama-quantize', 'llama-bench', 'test-backend-ops')


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True, text=True, **kwargs)


def cmake_tokens(path, pattern):
    text = re.sub(r'#[^\n]*', '', Path(path).read_text())
    match = re.search(pattern, text, re.S)
    if not match:
        raise SystemExit(f'source list not found in {path}: {pattern}')
    return match.group(1).split()


def sources(root, base, tokens):
    found = [base / t for t in tokens if t.endswith(('.c', '.cpp'))]
    missing = [str(p) for p in found if not (root / p).is_file()]
    if missing:
        raise SystemExit(f'missing sources: {missing}')
    return found


def configure(template, output, values):
    text = Path(template).read_text()
    for key, value in values.items():
        text = text.replace(f'@{key}@', value)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)


def arm_flags(scratch):
    """ggml-cpu GGML_NATIVE probes: '-mcpu=native' plus +feature/+nofeature exactly as CMake tests them."""
    probes = {
        'dotprod': ('DOTPROD', '#include <arm_neon.h>\nint main() { int8x16_t _a, _b; volatile int32x4_t _s = vdotq_s32(_s, _a, _b); return 0; }'),
        'i8mm': ('MATMUL_INT8', '#include <arm_neon.h>\nint main() { int8x16_t _a, _b; volatile int32x4_t _s = vmmlaq_s32(_s, _a, _b); return 0; }'),
        'sve': ('SVE', '#include <arm_sve.h>\nint main()  { svfloat32_t _a, _b; volatile svfloat32_t _c = svadd_f32_z(svptrue_b8(), _a, _b); return 0; }'),
        'sme': ('SME', '#include <arm_sme.h>\n__arm_locally_streaming int main() { __asm__ volatile("smstart; smstop;"); return 0; }'),
    }
    verbose = subprocess.run([CC, '-mcpu=native', '-E', '-v', '-'], stdin=subprocess.DEVNULL,
                             capture_output=True, text=True).stderr
    native = (re.search(r"-march=[^ ']+", verbose) or re.search(r"-mcpu=[^ ']+", verbose))
    native = native.group(0) if native and not native.group(0).endswith('=native') else '-mcpu=native'
    fix, undef = '', []
    for tag, (feature, code) in probes.items():
        source = scratch / f'probe-{tag}.cpp'
        source.write_text(code)
        binary = scratch / f'probe-{tag}'
        ok = subprocess.run([CXX, f'{native}+{tag}', source, '-o', binary], capture_output=True).returncode == 0
        ok = ok and subprocess.run([binary], capture_output=True).returncode == 0
        if ok:
            fix += f'+{tag}'
        else:
            trivial = scratch / 'probe-trivial.cpp'
            trivial.write_text('int main() { return 0; }')
            if subprocess.run([CXX, f'{native}+no{tag}', trivial, '-o', scratch / 'probe-trivial'],
                              capture_output=True).returncode == 0:
                fix += f'+no{tag}'
                undef.append(f'-U__ARM_FEATURE_{feature}')
    flags = []
    fp16 = scratch / 'probe-fp16.cpp'
    fp16.write_text('int main() { return 0; }')
    check = subprocess.run([CXX, '-mfp16-format=ieee', '-Werror', '-c', fp16, '-o', scratch / 'probe-fp16.o'],
                           capture_output=True, text=True)
    if check.returncode == 0 and not check.stderr.strip():
        flags.append('-mfp16-format=ieee')
    return [*flags, *undef, native + fix]


def vulkan_features(source_dir):
    """ggml-vulkan test_shader_extension_support: ON unless glslc reports the extension unsupported."""
    tests = [('GL_KHR_cooperative_matrix', 'coopmat.comp', 'GGML_VULKAN_COOPMAT_GLSLC_SUPPORT'),
             ('GL_NV_cooperative_matrix2', 'coopmat2.comp', 'GGML_VULKAN_COOPMAT2_GLSLC_SUPPORT'),
             ('GL_NV_cooperative_matrix_decode_vector', 'coopmat2_decode_vector.comp',
              'GGML_VULKAN_COOPMAT2_DECODE_VECTOR_GLSLC_SUPPORT'),
             ('GL_EXT_integer_dot_product', 'integer_dot.comp', 'GGML_VULKAN_INTEGER_DOT_GLSLC_SUPPORT'),
             ('GL_EXT_bfloat16', 'bfloat16.comp', 'GGML_VULKAN_BFLOAT16_GLSLC_SUPPORT'),
             ('GL_EXT_float_e2m1', 'float_e2m1.comp', 'GGML_VULKAN_FLOAT_E2M1_GLSLC_SUPPORT'),
             ('GL_EXT_float_e4m3', 'float_e4m3.comp', 'GGML_VULKAN_FLOAT_E4M3_GLSLC_SUPPORT')]
    enabled = {}
    for extension, name, define in tests:
        result = subprocess.run([GLSLC, '-o', '-', '-fshader-stage=compute', '--target-env=vulkan1.3',
                                 source_dir / 'feature-tests' / name], capture_output=True)
        error = result.stderr.decode(errors='replace')
        enabled[define] = not re.search(f'extension not supported: {re.escape(extension)}', error)
    return enabled


def compile_one(job):
    source, obj, command = job
    if obj.exists():
        return obj, None
    obj.parent.mkdir(parents=True, exist_ok=True)
    temporary = obj.with_suffix('.o.tmp')
    result = subprocess.run([*command, '-c', source, '-o', temporary], capture_output=True, text=True)
    if result.returncode:
        return obj, result.stderr[-6000:]
    os.replace(temporary, obj)
    return obj, None


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--vulkan', choices=('on', 'off'), required=True)
    parser.add_argument('--jobs', type=int, default=6)
    args = parser.parse_args()
    root, out, vulkan = args.source.resolve(), args.build.resolve(), args.vulkan == 'on'
    if run(['git', '-C', root, 'rev-parse', 'HEAD']).stdout.strip() != COMMIT:
        raise SystemExit(f'llama.cpp source is not at the pinned commit {COMMIT}')
    if subprocess.run(['git', '-C', root, 'diff-index', '--quiet', 'HEAD', '--']).returncode:
        raise SystemExit('llama.cpp tracked tree is modified; refusing to build')
    if out == root or root in out.parents:
        raise SystemExit('build directory must be outside the source tree')
    out.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix='probe-', dir=out))

    short = run(['git', '-C', root, 'rev-parse', '--short', 'HEAD']).stdout.strip()
    number = run(['git', '-C', root, 'rev-list', '--count', 'HEAD']).stdout.strip()
    compiler = 'AppleClang ' + run([CC, '-dumpversion']).stdout.strip()
    gen = out / 'generated'
    configure(root / 'ggml/src/ggml-version.h.in', gen / 'ggml/ggml-version.h', {'GGML_VERSION': '0.27.0', 'GGML_BUILD_COMMIT': short})
    configure(root / 'src/llama-version.h.in', gen / 'src/llama-version.h', {'LLAMA_VERSION': '0.7.0-dev', 'LLAMA_BUILD_COMMIT': short})
    configure(root / 'common/build-info.cpp.in', gen / 'common/build-info.cpp',
              {'LLAMA_BUILD_NUMBER': number, 'LLAMA_BUILD_COMMIT': short, 'BUILD_COMPILER': compiler,
               'BUILD_TARGET': f'{platform.system()} {platform.machine()}'})
    ui_h = (root / 'tools/ui/ui.h.in').read_text().replace('#cmakedefine LLAMA_UI_HAS_ASSETS 1', '/* #undef LLAMA_UI_HAS_ASSETS */')
    (gen / 'ui').mkdir(parents=True, exist_ok=True)
    (gen / 'ui/ui.h').write_text(ui_h.replace('@N_ASSETS@', '0'))
    configure(root / 'tools/ui/ui.cpp.in', gen / 'ui/ui.cpp', {'ASSET_ARRAYS': '', 'ASSET_TABLE': '', 'N_ASSETS': '0', 'USE_GZIP': 'false'})

    arch = arm_flags(scratch)
    public = ['-D_DARWIN_C_SOURCE', '-DGGML_USE_CPU'] + (['-DGGML_USE_VULKAN'] if vulkan else [])
    base_inc = ['-I', root / 'ggml/include', '-I', root / 'include']
    ggml_dir = ['-DGGML_SCHED_MAX_COPIES=4', '-D_XOPEN_SOURCE=600', '-I', root / 'ggml/src']
    vendor = ['-I', root / 'vendor']
    common_inc = ['-I', root / 'common', *vendor, '-DLLAMA_SUBPROCESS']
    c = [CC, *OPT, '-std=gnu11', *public, *base_inc]
    cxx = [CXX, *OPT, '-std=gnu++17', *public, *base_inc]

    groups = {}
    ggml_base = sources(root, Path('ggml/src'), cmake_tokens(root / 'ggml/src/CMakeLists.txt', r'add_library\(ggml-base(.*?)\)'))
    groups['ggml-base'] = (ggml_base, ggml_dir + ['-I', gen / 'ggml'])
    groups['ggml'] = (sources(root, Path('ggml/src'), cmake_tokens(root / 'ggml/src/CMakeLists.txt', r'add_library\(ggml\s(.*?)\)')), ggml_dir)
    cpu = cmake_tokens(root / 'ggml/src/ggml-cpu/CMakeLists.txt', r'list \(APPEND GGML_CPU_SOURCES(.*?)\)')
    cpu += ['ggml-cpu/llamafile/sgemm.cpp', 'ggml-cpu/arch/arm/quants.c', 'ggml-cpu/arch/arm/repack.cpp']
    groups['ggml-cpu'] = (sources(root, Path('ggml/src'), cpu),
                          ggml_dir + ['-I', root / 'ggml/src/ggml-cpu', '-DGGML_USE_ACCELERATE', '-DACCELERATE_NEW_LAPACK',
                                      '-DACCELERATE_LAPACK_ILP64', '-DGGML_USE_LLAMAFILE', '-DGGML_USE_CPU_REPACK', *arch])
    record = {'llama_commit': COMMIT, 'llama_build_number': int(number), 'short_commit': short, 'compiler': compiler,
              'compiler_version': run([CC, '--version']).stdout.splitlines()[0], 'vulkan': vulkan, 'metal_compiled': False,
              'blas_compiled': False, 'openssl': False, 'shared_libs': False, 'webui_assets': False,
              'cpu_arch_flags': arch, 'cpu_definitions': ['GGML_USE_ACCELERATE', 'ACCELERATE_NEW_LAPACK',
              'ACCELERATE_LAPACK_ILP64', 'GGML_USE_LLAMAFILE', 'GGML_USE_CPU_REPACK'], 'public_definitions': public}
    links = ['-framework', 'Accelerate', '-lpthread']
    if vulkan:
        shaders_dir = root / 'ggml/src/ggml-vulkan/vulkan-shaders'
        features = vulkan_features(shaders_dir)
        feature_defs = [f'-D{name}' for name, on in features.items() if on]
        record.update(glslc=str(GLSLC), glslc_version=run([GLSLC, '--version']).stdout.splitlines()[0],
                      vulkan_glslc_features=features)
        vk_out = out / 'ggml-vulkan'
        generator = vk_out / 'vulkan-shaders-gen'
        if not generator.exists():
            vk_out.mkdir(parents=True, exist_ok=True)
            run([CXX, *OPT, '-std=gnu++17', *feature_defs, shaders_dir / 'vulkan-shaders-gen.cpp', '-o', generator, '-lpthread'])
        header, spv = vk_out / 'ggml-vulkan-shaders.hpp', vk_out / 'vulkan-shaders.spv'
        if not header.exists():
            run([generator, '--output-dir', spv, '--target-hpp', header])
        comps = sorted(shaders_dir.glob('*.comp'))

        def shader(comp):
            target = vk_out / f'{comp.name}.cpp'
            if target.exists():
                return None
            result = subprocess.run([generator, '--glslc', GLSLC, '--source', comp, '--output-dir', spv,
                                     '--target-hpp', header, '--target-cpp', str(target) + '.tmp'], capture_output=True, text=True)
            if result.returncode:
                return f'{comp.name}: {result.stdout[-3000:]}{result.stderr[-3000:]}'
            os.replace(str(target) + '.tmp', target)
            return None
        with concurrent.futures.ThreadPoolExecutor(max(1, args.jobs // 3)) as pool:
            failures = [f for f in pool.map(shader, comps) if f]
        if failures:
            raise SystemExit('shader generation failed:\n' + '\n'.join(failures))
        vk_sources = sources(root, Path('ggml/src/ggml-vulkan'), ['ggml-vulkan.cpp', 'ggml-vulkan-buffers.cpp', 'ggml-vulkan-debug.cpp'])
        vk_flags = ggml_dir + ['-I', vk_out, '-I', BREW / 'include', *feature_defs]
        groups['ggml-vulkan'] = (vk_sources + [vk_out / f'{p.name}.cpp' for p in comps], vk_flags)
        links += ['-L', BREW / 'lib', '-lvulkan']

    llama_core = cmake_tokens(root / 'src/CMakeLists.txt', r'set\(LLAMA_CORE_SOURCES(.*?)\)')
    models = sorted(p.relative_to(root / 'src').as_posix() for p in (root / 'src/models').glob('*.cpp'))
    groups['llama'] = (sources(root, Path('src'), llama_core + models), ['-I', root / 'src', '-I', gen / 'src'])
    groups['vendor-hash'] = (sources(root, Path('vendor/hash'), ['hash.cpp', 'xxhash/xxhash.c', 'sha256/sha256.c']),
                             [*vendor, '-I', root / 'vendor/hash', '-w'])
    groups['vendor-hash-sha1'] = ([Path('vendor/hash/sha1/sha1.c')], [*vendor, '-I', root / 'vendor/hash', '-w', '-x', 'c++'])
    groups['cpp-httplib'] = ([Path('vendor/cpp-httplib/httplib.cpp')],
                             ['-w', '-DCPPHTTPLIB_FORM_URL_ENCODED_PAYLOAD_MAX_LENGTH=1048576', '-DCPPHTTPLIB_LISTEN_BACKLOG=512',
                              '-DCPPHTTPLIB_REQUEST_URI_MAX_LENGTH=32768', '-DCPPHTTPLIB_TCP_NODELAY=1'])
    parsers = [t.replace('${CMAKE_CURRENT_LIST_DIR}/', 'parsers/') for t in
               cmake_tokens(root / 'common/parsers/sources.cmake', r'set\(LLAMA_CHAT_PARSERS_SOURCES(.*?)\)')]
    common = cmake_tokens(root / 'common/CMakeLists.txt', r'add_library\(\$\{TARGET\}\s+\$\{LLAMA_CHAT_PARSERS_SOURCES\}(.*?)\)')
    groups['llama-common'] = (sources(root, Path('common'), parsers + common) + [gen / 'common/build-info.cpp'], common_inc)
    mtmd = cmake_tokens(root / 'tools/mtmd/CMakeLists.txt', r'add_library\(mtmd(.*?)\)')
    groups['mtmd'] = (sources(root, Path('tools/mtmd'), mtmd), ['-I', root / 'tools/mtmd', *vendor, '-DMTMD_VIDEO'])
    server_cmake = root / 'tools/server/CMakeLists.txt'
    server = (cmake_tokens(server_cmake, r'add_library\(\$\{TARGET\} STATIC(.*?)\)')
              + cmake_tokens(server_cmake, r'set\(TARGET llama-server-impl\)\s*add_library\(\$\{TARGET\}(.*?)\)') + ['main.cpp'])
    server_inc = ['-I', root / 'tools/server', '-I', root / 'tools/mtmd', '-I', root, '-I', gen / 'ui', *common_inc]
    groups['llama-server'] = (sources(root, Path('tools/server'), server), server_inc)
    groups['llama-ui'] = ([gen / 'ui/ui.cpp'], ['-I', gen / 'ui'])
    for tool, files in (('completion', ['completion.cpp', 'main.cpp']), ('quantize', ['quantize.cpp', 'main.cpp']),
                        ('llama-bench', ['llama-bench.cpp', 'main.cpp'])):
        groups[f'tool-{tool}'] = (sources(root, Path('tools') / tool, files), ['-I', root / 'tools' / tool, *common_inc])
    # tests/CMakeLists.txt: llama_build(test-backend-ops.cpp LINK ggml)
    groups['test-backend-ops'] = (sources(root, Path('tests'), ['test-backend-ops.cpp']), [])

    jobs, objects = [], {}
    for name, (files, flags) in groups.items():
        for file in files:
            path = file if file.is_absolute() else root / file
            compiler = c if path.suffix == '.c' and '-x' not in flags else cxx
            rel = path.relative_to(out) if out in path.parents else path.relative_to(root)
            obj = out / 'obj' / name / (rel.as_posix().replace('/', '__') + '.o')
            jobs.append((path, obj, [*map(str, compiler), *map(str, flags)]))
            objects.setdefault(name, []).append(obj)
    (out / 'compile_commands.json').write_text(json.dumps(
        [{'file': str(s), 'output': str(o), 'arguments': [*cmd, '-c', str(s), '-o', str(o)]} for s, o, cmd in jobs], indent=1))
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        failures = [(o, e) for o, e in pool.map(compile_one, jobs) if e]
    if failures:
        for obj, error in failures[:5]:
            print(f'FAILED {obj}\n{error}', file=sys.stderr)
        raise SystemExit(f'{len(failures)} compile failures')

    core = [o for n in ('llama-common', 'cpp-httplib', 'llama', 'ggml', 'ggml-cpu', 'ggml-vulkan', 'ggml-base')
            for o in objects.get(n, [])]
    bin_dir = out / 'bin'
    bin_dir.mkdir(exist_ok=True)
    targets = {'llama-server': objects['llama-server'] + objects['llama-ui'] + objects['mtmd'] + objects['vendor-hash']
               + objects['vendor-hash-sha1'],
               'llama-completion': objects['tool-completion'], 'llama-quantize': objects['tool-quantize'],
               'llama-bench': objects['tool-llama-bench']}
    for name, extra in targets.items():
        run([CXX, *extra, *core, '-o', bin_dir / name, *links])
    ggml_only = [o for n in ('ggml', 'ggml-cpu', 'ggml-vulkan', 'ggml-base') for o in objects.get(n, [])]
    run([CXX, *objects['test-backend-ops'], *ggml_only, '-o', bin_dir / 'test-backend-ops', *links])
    record['binaries'] = {name: {'path': str(bin_dir / name), 'sha256': sha256(bin_dir / name),
                                 'linked_libraries': run(['otool', '-L', bin_dir / name]).stdout.splitlines()[1:]}
                          for name in TOOLS}
    record['source_tree_clean'] = subprocess.run(['git', '-C', root, 'diff-index', '--quiet', 'HEAD', '--']).returncode == 0
    record['translation_units'] = len(jobs)
    shutil.rmtree(scratch, ignore_errors=True)
    (out / 'build-record.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: record[k] for k in ('llama_commit', 'vulkan', 'cpu_arch_flags', 'translation_units')}))


if __name__ == '__main__':
    main()
