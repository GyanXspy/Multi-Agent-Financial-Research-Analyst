"""
Shared rate limiter instance (slowapi, keyed by client IP).

Imported by main.py (to register the middleware/handler) and by routers
(to decorate endpoints).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
