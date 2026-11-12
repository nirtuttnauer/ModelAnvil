#!/usr/bin/env python3
"""Phase durations from a docker logs -t container log of a golden-path run."""
import re, sys
from datetime import datetime
marks = [('measure-start', 'clone'), ('+ python3.12 -m venv', 'venv'), ('pip install torch', 'torch install'),
         ('pip install -r requirements.txt', 'requirements install'), ('+ make migrate', 'migrate+bootstrap+check'),
         ('golden_path.py --train', 'download+train'), ('loading exported candidate with verify_cpu_export', 'independent inference'),
         ('measure-end', None)]
times = []
for line in open(sys.argv[1], errors='replace'):
    stamp, _, text = line.partition(' ')
    for key, label in marks:
        if key in text and not any(k == key for k, _, _ in times):
            t = datetime.fromisoformat(stamp[:26].rstrip('Z'))
            times.append((key, label, t))
times.sort(key=lambda x: x[2])
out = []
for (k, label, t), (_, _, n) in zip(times, times[1:]):
    if label:
        out.append(f'{label} {(n - t).total_seconds():.1f}s')
print('; '.join(out))
