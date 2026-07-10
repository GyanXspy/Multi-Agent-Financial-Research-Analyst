"""
Gunicorn configuration for production deployment.

Run with:
    gunicorn app.main:app -c gunicorn.conf.py
"""

import multiprocessing
import os

# Bind address
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

# Workers — use env override or a sensible default
workers = int(os.getenv("WORKERS", min(multiprocessing.cpu_count() * 2 + 1, 8)))

# Use Uvicorn's ASGI worker
worker_class = "uvicorn.workers.UvicornWorker"

# Timeouts
timeout = 120  # seconds — generous for long analysis pipelines
graceful_timeout = 30
keepalive = 5

# Trust proxy headers only from the load balancer
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1")

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")

# Preload app for faster worker forks (shares memory)
preload_app = True

# Limit request sizes (16 MB)
limit_request_body = 16 * 1024 * 1024

# Max requests before worker restart (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 50
