#!/usr/bin/env python3
"""ANVIL-027: follow docs/self-host-install.md, block by block, on new docker:dind engines.

usage: python3 verbatim_run.py <host directory holding the 0.1.0 and 0.1.1 release directories>

Every ```sh block of the page runs in page order, exactly as written, as one `sh -e -x` script inside a new
privileged docker:dind engine with an empty /var/lib/docker volume (the ANVIL-026 reset environment). The blocks
under "Restore on another machine" run in a second new engine of the same kind.

Between blocks the runner does only what the page leaves to the operator. Each such action is printed as
`operator:` with its command:
- install the tools the page's Requirements name, with the page's own Alpine example (`apk add ...`);
- answer the installer's three prompts (owner email, workspace name, new password). The answers are generated
  inside the engine and fed on standard input, as a person would type them. They are never printed;
- the two build blocks are not run, because there is no published release: the existing release directory with
  the version each block's --output names is copied to that path instead;
- copy the backup and release directories that "Restore on another machine" names to the second engine, with
  tar, which keeps file modes.
Read-only checks after the last block are printed as `observe:`. Python 3.9 standard library only.
"""
import datetime
import hashlib
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DOC = ROOT / 'docs' / 'self-host-install.md'
DIND = 'docker:dind@sha256:08a98015fce594af7c382883bea080ea206de74402a95da9dc52b6428c8cd121'
ENGINES = {'first': ('anvil027-first', 'anvil027-first-docker'), 'second': ('anvil027-second', 'anvil027-second-docker')}
SECOND_SECTION = 'Restore on another machine'
ANSWERS = '/run/anvil027-owner-answers'
BLOCK_FILE = '/run/anvil027-block.sh'
SECRETS = []
SEEN = {'secret_values': 0}
SUMMARY = []


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def emit(text=''):
    """Print, with any known secret value replaced, and count replacements."""
    for value in SECRETS:
        if value and value in text:
            SEEN['secret_values'] += text.count(value);text = text.replace(value, '[REDACTED]')
    print(text, flush=True)


def docker(*args, data=None, timeout=1800):
    result = subprocess.run(['docker', *args], input=data, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    return result.returncode, result.stdout.decode(errors='replace')


def quiet(engine, command):
    """A runner-side command whose output is held in memory and never printed."""
    return docker('exec', ENGINES[engine][0], 'sh', '-c', command)


def page_blocks(text):
    section = subsection = None;fence = None;lines = [];blocks = [];others = []
    for number, line in enumerate(text.splitlines(), 1):
        if fence is None:
            if line.startswith('## '):section, subsection = line[3:].strip(), None
            elif line.startswith('### '):subsection = line[4:].strip()
            match = re.match(r'^(\s*)```(\S*)\s*$', line)
            if match:
                if match.group(1):raise SystemExit('indented code fence at page line %d; the runner reads top-level fences only' % number)
                fence = (match.group(2), number);lines = []
        elif line.strip() == '```':
            kind, start = fence
            if kind == 'sh':blocks.append({'section': section, 'subsection': subsection, 'line': start, 'code': '\n'.join(lines)})
            else:others.append((kind, start))
            fence = None
        else:lines.append(line)
    if fence is not None:raise SystemExit('unclosed code fence at page line %d' % fence[1])
    return blocks, others


def where(block):
    return block['section'] + (' / ' + block['subsection'] if block['subsection'] else '')


def run_script(engine, code, stdin_file=None):
    """Write the block to a file in the engine and run it with sh -e -x from the home directory."""
    name = ENGINES[engine][0]
    status, output = docker('exec', '-i', name, 'sh', '-c', 'cat > ' + BLOCK_FILE, data=code.encode() + b'\n')
    if status:return status, 'could not write the block into the engine: ' + output, 0.0
    started = time.monotonic()
    status, output = docker('exec', '-w', '/root', name, 'sh', '-c', 'sh -e -x ' + BLOCK_FILE + ' < ' + (stdin_file or '/dev/null'))
    return status, output, round(time.monotonic() - started, 1)


def step(label, engine, how, code, *, page_line=None, stdin_file=None):
    number = len(SUMMARY) + 1
    emit();emit('== step %d %s  engine %s  %s%s' % (number, now(), engine, label, '  (page line %d)' % page_line if page_line else ''))
    emit('---- ' + how);emit(code)
    status, output, seconds = run_script(engine, code, stdin_file)
    emit('---- output');emit(output.rstrip('\n'))
    emit('---- exit %d, %.1f s' % (status, seconds))
    SUMMARY.append((number, engine, label, page_line, how.split(':')[0], status, seconds))
    return status


def start_engine(engine, mounts):
    name, volume = ENGINES[engine]
    docker('rm', '-f', name);docker('volume', 'rm', volume)
    args = ['run', '-d', '--privileged', '--name', name, '--platform', 'linux/arm64', '-v', volume + ':/var/lib/docker']
    for source, target in mounts:args += ['-v', str(source) + ':' + target + ':ro']
    status, output = docker(*args, DIND)
    if status:raise RuntimeError('could not start the engine container: ' + output)
    for _ in range(90):
        if docker('exec', name, 'docker', 'info')[0] == 0:break
        time.sleep(1)
    else:raise RuntimeError('the inner Docker engine did not start')
    emit();emit('== engine %s (%s) started %s from %s with new volume %s' % (engine, name, now(), DIND, volume))
    for label, command in (('inner engine', "docker version --format '{{.Server.Version}} {{.Server.Os}}/{{.Server.Arch}}'"),
            ('images before', 'docker images -q | wc -l'), ('volumes before', 'docker volume ls -q | wc -l'),
            ('containers before', 'docker ps -aq | wc -l'), ('MemTotal bytes', "docker info --format '{{.MemTotal}}'")):
        emit('observe: %s: %s' % (label, docker('exec', name, 'sh', '-c', command)[1].strip()))


def main():
    cache = Path(sys.argv[1]).expanduser().resolve()
    seeds = [(cache / version, '/seed/' + version) for version in ('0.1.0', '0.1.1')]
    for source, _ in seeds:
        if not (source / 'release.json').is_file():raise SystemExit('missing release directory: ' + str(source))
    text = DOC.read_text()
    blocks, others = page_blocks(text)
    alpine = re.search(r'On Alpine Linux, for example: `(apk add [^`]+)`', text).group(1)
    copied = re.search(r'to the same paths on the second machine: here `~/([^`]+)` and `~/([^`]+)`', text).groups()
    requirements = [b for b in blocks if b['section'] == 'Requirements']
    head = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    emit('ANVIL-027 verbatim run of docs/self-host-install.md, started %s' % now())
    emit('repository HEAD %s; page sha256 %s; %d sh blocks; other fences (not commands): %s' % (
        head, hashlib.sha256(text.encode()).hexdigest(), len(blocks), ', '.join('%s at line %d' % o for o in others) or 'none'))
    for index, block in enumerate(blocks, 1):emit('  block %d: page line %d, %s' % (index, block['line'], where(block)))
    rc = 1
    try:rc = walk(blocks, requirements, alpine, copied, seeds)
    except Exception as exc:emit('runner error: %s: %s' % (type(exc).__name__, exc))
    finally:
        emit();emit('== cleanup %s' % now())
        for name, volume in ENGINES.values():
            emit('rm %s: exit %d; volume rm %s: exit %d' % (name, docker('rm', '-f', name)[0], volume, docker('volume', 'rm', volume)[0]))
        emit('left: containers %d, volumes %d' % (len(docker('ps', '-aq', '-f', 'name=anvil027-')[1].split()), len(docker('volume', 'ls', '-q', '-f', 'name=anvil027-')[1].split())))
        emit();emit('== summary')
        emit('| step | engine | what | page line | how | exit | seconds |')
        emit('|---:|---|---|---:|---|---:|---:|')
        for number, engine, label, line, how, status, seconds in SUMMARY:
            emit('| %d | %s | %s | %s | %s | %d | %.1f |' % (number, engine, label, line or '', how, status, seconds))
        lines = {row[3] for row in SUMMARY if row[4] == 'verbatim'}
        emit('page blocks run verbatim: %d of %d sh blocks, the Requirements block once on each engine; build blocks replaced by a release copy: %d; every step exit 0: %s' % (
            len(lines), len(blocks), sum(1 for b in blocks if 'build_selfhost_release.py' in b['code']), all(row[5] == 0 for row in SUMMARY)))
        emit('secret values seen in the output (owner password, DJANGO_SECRET_KEY, POSTGRES_PASSWORD): %d' % SEEN['secret_values'])
    if SEEN['secret_values'] or not all(row[5] == 0 for row in SUMMARY):return 1
    return rc


def secret(engine, command):
    status, value = quiet(engine, command);value = value.strip()
    if status or len(value) < 16 or '\n' in value:raise RuntimeError('could not read a value to scan for')
    SECRETS.append(value)


def walk(blocks, requirements, alpine, copied, seeds):
    start_engine('first', seeds)
    if step('Requirements: tools', 'first', "operator: the page's Alpine example from Requirements", alpine):return 1
    status, _ = quiet('first', "umask 077 && python3 -c \"import secrets; print('owner@first-machine.test'); print('Install page walk-through'); print(secrets.token_urlsafe(24))\" > " + ANSWERS)
    if status:emit('operator: could not prepare the prompt answers');return 1
    secret('first', 'sed -n 3p ' + ANSWERS)
    emit();emit('operator: generated the answers to the installer prompts inside the engine (%s, mode 0600; owner email, workspace name, a secrets.token_urlsafe(24) password). Not printed.' % ANSWERS)
    second_ready = False
    for index, block in enumerate(blocks, 1):
        engine = 'second' if block['section'] == SECOND_SECTION else 'first'
        if engine == 'second' and not second_ready:
            start_engine('second', [])
            if step('Restore on another machine, page step 1: tools', 'second', "operator: the page's Alpine example from Requirements", alpine):return 1
            for requirement in requirements:
                if step('Restore on another machine, page step 1: Requirements check', 'second', 'verbatim: the Requirements block at page line %d' % requirement['line'], requirement['code'], page_line=requirement['line']):return 1
            emit();emit('== operator: page step 2, copy ~/%s and ~/%s to the second machine with tar (keeps modes) %s' % (copied + (now(),)))
            sender = subprocess.Popen(['docker', 'exec', ENGINES['first'][0], 'tar', '-C', '/root', '-cf', '-', *copied], stdout=subprocess.PIPE)
            receiver = subprocess.run(['docker', 'exec', '-i', ENGINES['second'][0], 'tar', '-C', '/root', '-xpf', '-'], stdin=sender.stdout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            sender.stdout.close();sent = sender.wait()
            emit('operator: tar exit %d and %d' % (sent, receiver.returncode))
            if sent or receiver.returncode:return 1
            emit(docker('exec', ENGINES['second'][0], 'sh', '-c', 'ls -la ' + ' '.join('/root/' + c for c in copied))[1].rstrip())
            second_ready = True
        if 'build_selfhost_release.py' in block['code']:
            target = re.search(r'--output (\S+)', block['code']).group(1);version = target.rstrip('/').rsplit('/', 1)[1]
            emit();emit('== page block %d (line %d, %s) is a build and is not run: no published release exists.' % (index, block['line'], where(block)))
            emit(block['code'])
            copy = 'mkdir -p "$(dirname %s)"\ncp -a /seed/%s %s\nls -la %s' % (target, version, target, target)
            if step('copy release %s for the build block at page line %d' % (version, block['line']), 'first', 'operator: copy the existing release %s to the path the build block names' % version, copy):return 1
            continue
        stdin_file = ANSWERS if 'install_selfhost.py' in block['code'] else None
        how = 'verbatim: page block %d' % index + (', with the three prompt answers typed on standard input' if stdin_file else '')
        status = step(where(block), engine, how, block['code'], page_line=block['line'], stdin_file=stdin_file)
        if stdin_file:
            quiet('first', 'rm -f ' + ANSWERS)
            if status == 0:
                for key in ('DJANGO_SECRET_KEY', 'POSTGRES_PASSWORD'):secret('first', "sed -n 's/^%s=//p' /root/modelanvil/.env" % key)
        if status:return 1
    emit();emit('== observe (read-only, not page steps) %s' % now())
    for engine, command in OBSERVE:
        emit('observe: [%s] %s' % (engine, command));emit(docker('exec', ENGINES[engine][0], 'sh', '-c', command)[1].rstrip())
    return 0


OBSERVE = (
    ('first', 'git -C ~/src/ModelAnvil rev-parse HEAD'),
    ('first', 'python3 -c "import json; r = json.load(open(\'/root/modelanvil-rehearsal-drill/record/report.json\')); print(\'drill passed\', r[\'passed\'], [(s[\'step\'], s[\'exit_code\'], s[\'seconds\']) for s in r[\'steps\']], {k: v[\'equal\'] for k, v in r[\'checks\'].items()}, \'rollback backup age s\', r[\'rollback\'][\'backup_age_seconds\'], \'restore s\', r[\'rollback\'][\'restore_seconds\'])"'),
    ('first', 'du -sh ~/modelanvil-releases/* ~/modelanvil ~/modelanvil/release-history/* ~/modelanvil-rollback ~/modelanvil-backups/* ~/modelanvil-rehearsal-drill/* 2>&1; ls -la ~/modelanvil-rehearsal-drill'),
    ('first', 'docker system df; docker images --format "{{.ID}} {{.Size}}"; docker volume ls; docker ps -a --format "{{.Names}} {{.Status}}"'),
    ('second', 'du -sh ~/modelanvil-releases/* ~/modelanvil ~/modelanvil-backups/*; docker system df; docker images --format "{{.ID}} {{.Size}}"; docker volume ls; docker ps -a --format "{{.Names}} {{.Status}}"'),
)


if __name__ == '__main__':
    sys.exit(main())
