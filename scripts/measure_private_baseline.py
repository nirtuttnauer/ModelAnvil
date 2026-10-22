#!/usr/bin/env python3
"""Run the disposable real CPU journey with acquisition offline and socket connects refused."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ['MODELANVIL_OFFLINE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_activation_baseline import main


if __name__ == '__main__':
    attempts = []
    def refused(*args, **kwargs):
        attempts.append(True)
        raise AssertionError('The offline CPU baseline attempted a socket connection.')
    with patch('socket.socket.connect', refused), patch('socket.create_connection', refused):
        main()
    output = Path(sys.argv[sys.argv.index('--output') + 1])
    report = json.loads(output.read_text())
    assert not attempts, 'Offline execution attempted an external connection.'
    report.update(offline_policy=True, outbound_connection_attempts=0,
                  verification='Actual CPU training, durable evaluation, authenticated chat and a recorded decision with Python socket connections refused.')
    output.write_text(json.dumps(report, indent=2)+'\n')
