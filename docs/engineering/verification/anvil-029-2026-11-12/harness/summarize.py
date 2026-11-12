#!/usr/bin/env python3
"""Summarize one ANVIL-029 measurement output directory as JSON."""
import json
import re
import sys
from pathlib import Path

UNITS = {'B': 1, 'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3, 'kB': 1000, 'MB': 1000**2, 'GB': 1000**3}


def read(path):
    try:
        return path.read_text(errors='replace')
    except OSError:
        return None


def time_v(text):
    if text is None:
        return None
    wanted = {
        'Command being timed': 'command', 'Maximum resident set size (kbytes)': 'max_rss_kbytes',
        'Elapsed (wall clock) time (h:mm:ss or m:ss)': 'elapsed', 'Exit status': 'exit_status',
        'User time (seconds)': 'user_seconds', 'System time (seconds)': 'system_seconds',
        'Percent of CPU this job got': 'cpu_percent', 'Major (requiring I/O) page faults': 'major_faults',
    }
    out = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('Command terminated by signal'):
            out['terminated_by_signal'] = stripped
        key, _, value = stripped.partition(': ')
        if key in wanted:
            out[wanted[key]] = value.strip()
    if 'elapsed' in out:
        parts = [float(p) for p in out['elapsed'].split(':')]
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + part
        out['elapsed_seconds'] = round(seconds, 2)
    if 'max_rss_kbytes' in out:
        out['max_rss_bytes'] = int(out['max_rss_kbytes']) * 1024
        out['max_rss_gib'] = round(out['max_rss_bytes'] / 1024**3, 3)
    return out


def size(text):
    match = re.fullmatch(r'([0-9.]+)\s*([A-Za-z]+)', text.strip())
    return int(float(match.group(1)) * UNITS[match.group(2)]) if match else None


def main(directory):
    d = Path(directory)
    result = {'directory': d.name}
    result['exit_code'] = (read(d / 'exit-code.txt') or '').strip() or None
    result['time_v'] = time_v(read(d / 'time-v.txt'))
    peak = read(d / 'memory.peak.txt')
    if peak:
        result['cgroup_memory_peak_bytes'] = int(peak.split()[0])
        result['cgroup_memory_peak_gib'] = round(int(peak.split()[0]) / 1024**3, 3)
    for name in ('memory.peak-after-apt.txt', 'memory.peak-after-engine-start.txt', 'engine-init.memory.peak.txt'):
        value = read(d / name)
        if value:
            result[name.replace('.txt', '')] = int(value.split()[0])
    events = read(d / 'memory.events.txt')
    if events:
        result['cgroup_memory_events'] = dict((k, int(v)) for k, v in (line.split() for line in events.splitlines() if line.strip()))
    state = read(d / 'state.json')
    if state:
        value = json.loads(state)
        result['docker_state'] = {k: value.get(k) for k in ('ExitCode', 'OOMKilled', 'StartedAt', 'FinishedAt', 'Error')}
    samples = read(d / 'cgroup-samples.txt') or ''
    current = anon = 0
    containers = {}
    engine = 0
    count = 0
    for line in samples.splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == 'C' and len(fields) >= 7:
            name = fields[3] if fields[3] != '?' else fields[2][:12]
            entry = containers.setdefault(name, {'memory_peak_bytes': 0, 'max_anon_bytes': 0})
            entry['memory_peak_bytes'] = max(entry['memory_peak_bytes'], int(fields[4]))
            if fields[6].isdigit():
                entry['max_anon_bytes'] = max(entry['max_anon_bytes'], int(fields[6]))
            continue
        if fields[0] == 'E' and len(fields) >= 4:
            engine = max(engine, int(fields[3]))
            continue
        if fields[0] == 'T':
            fields = fields[1:]
        if len(fields) >= 4 and all(f.isdigit() for f in fields[:4]):
            count += 1
            current = max(current, int(fields[1]))
            anon = max(anon, int(fields[2]))
    result['samples'] = count
    result['sampled_max_memory_current_bytes'] = current
    result['sampled_max_anon_bytes'] = anon
    result['sampled_max_anon_gib'] = round(anon / 1024**3, 3)
    if engine:
        result['sampled_engine_init_memory_peak_bytes'] = engine
    if containers:
        result['inner_containers'] = containers
    stats = read(d / 'docker-stats.raw') or ''
    usage = 0
    for chunk in re.split(r'\x1b\[[0-9;]*[A-Za-z]|\n', stats):
        if '|' in chunk and '/' in chunk:
            value = size(chunk.split('|')[0].split('/')[0])
            if value:
                usage = max(usage, value)
    result['docker_stats_max_usage_bytes'] = usage
    result['docker_stats_max_usage_gib'] = round(usage / 1024**3, 3)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main(sys.argv[1])
