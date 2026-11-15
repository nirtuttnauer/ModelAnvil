#!/usr/bin/env python3
"""Write build-record.json for a CMake build of pinned llama.cpp (read-only inspection, no compilation).

usage: record_cmake_build.py --source LLAMA_SRC --build CMAKE_BUILD_DIR --configure "cmake ..." --build-command "cmake --build ..."
Records the commit and clean-tree check, CMake and compiler versions, selected CMakeCache values, the
ggml-cpu/ggml-vulkan compile flags from compile_commands.json, whether any Metal or BLAS source was
compiled, and each binary's SHA-256, linked libraries and Metal symbol count. scripts/qualify_vulkan_inference.py
reads the result.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

COMMIT = 'f5027fb21307eb264aed483242603d68c87b0fe3'
TOOLS = ('llama-server', 'llama-completion', 'llama-quantize', 'llama-bench', 'test-backend-ops')
CACHE_KEYS = ('CMAKE_BUILD_TYPE', 'BUILD_SHARED_LIBS', 'CMAKE_C_COMPILER', 'CMAKE_CXX_COMPILER', 'CMAKE_OSX_SYSROOT',
              'CMAKE_OSX_DEPLOYMENT_TARGET', 'GGML_VULKAN', 'GGML_METAL', 'GGML_BLAS', 'GGML_NATIVE', 'GGML_ACCELERATE',
              'GGML_LLAMAFILE', 'GGML_CPU_REPACK', 'GGML_CPU_KLEIDIAI', 'GGML_OPENMP', 'GGML_BACKEND_DL',
              'GGML_CPU_ALL_VARIANTS', 'GGML_SCHED_MAX_COPIES', 'GGML_CUDA', 'GGML_RPC', 'LLAMA_OPENSSL',
              'LLAMA_BUILD_UI', 'LLAMA_USE_PREBUILT_UI', 'LLAMA_SUBPROCESS', 'LLAMA_LLGUIDANCE', 'LLAMA_CONNECT',
              'Vulkan_GLSLC_EXECUTABLE', 'Vulkan_LIBRARY', 'Vulkan_INCLUDE_DIR', 'SPIRV-Headers_DIR')


def run(*args):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True, text=True).stdout


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--configure', required=True)
    parser.add_argument('--build-command', required=True)
    args = parser.parse_args()
    if run('git', '-C', args.source, 'rev-parse', 'HEAD').strip() != COMMIT:
        raise SystemExit('source is not the pinned commit')
    cache = {}
    for line in (args.build / 'CMakeCache.txt').read_text().splitlines():
        match = re.match(r'^([^#/][^:]*):[A-Z]+=(.*)$', line)
        if match and match.group(1) in CACHE_KEYS:
            cache[match.group(1)] = match.group(2)
    commands = json.loads((args.build / 'compile_commands.json').read_text())
    files = [entry['file'] for entry in commands]
    def flags(fragment):
        entry = next(e for e in commands if fragment in e['file'])
        return [t for t in entry['command'].split() if t.startswith(('-D', '-m', '-U', '-O', '-std'))]
    vulkan = any('/ggml-vulkan/' in f for f in files)
    record = {
        'llama_commit': COMMIT, 'llama_build_number': int(run('git', '-C', args.source, 'rev-list', '--count', 'HEAD')),
        'source_tree_clean': subprocess.run(['git', '-C', str(args.source), 'diff-index', '--quiet', 'HEAD', '--']).returncode == 0,
        'build_system': run('cmake', '--version').splitlines()[0], 'configure_command': args.configure,
        'build_command': args.build_command, 'cmake_cache': cache,
        'compiler_version': run('/usr/bin/cc', '--version').splitlines()[0],
        'vulkan': vulkan, 'metal_compiled': any('ggml-metal' in f for f in files),
        'blas_compiled': any('ggml-blas' in f for f in files), 'translation_units_in_compile_database': len(files),
        'ggml_cpu_flags': flags('ggml-cpu/ggml-cpu.c'),
        **({'ggml_vulkan_flags': flags('ggml-vulkan/ggml-vulkan.cpp'),
            'vulkan_shader_sources': sum(1 for f in files if f.endswith('.comp.cpp')),
            'glslc_version': run(cache['Vulkan_GLSLC_EXECUTABLE'], '--version').splitlines()[0]} if vulkan else {}),
    }
    record['binaries'] = {}
    for tool in TOOLS:
        path = args.build / 'bin' / tool
        symbols = subprocess.run(['nm', str(path)], capture_output=True, text=True).stdout
        record['binaries'][tool] = {'path': str(path), 'sha256': sha256(path),
                                    'linked_libraries': [l.strip() for l in run('otool', '-L', path).splitlines()[1:]],
                                    'metal_symbol_count': sum(1 for l in symbols.splitlines() if 'metal' in l.lower())}
    (args.build / 'build-record.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print(json.dumps({t: v['sha256'] for t, v in record['binaries'].items()}, indent=1))


if __name__ == '__main__':
    main()
