"""Bounded HTTP workers; training runs in a separate process."""
import os

bind = '0.0.0.0:8000'
workers = int(os.environ.get('GUNICORN_WORKERS', '2'))
timeout = 60
graceful_timeout = 30
preload_app = True
accesslog = None  # Avoid retaining sensitive query strings and artifact grant IDs.
errorlog = '-'
forwarded_allow_ips = '*'
control_socket_disable = True
