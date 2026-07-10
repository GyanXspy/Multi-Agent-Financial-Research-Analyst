"""
HTTP middleware — request-ID injection and security headers.

Extracted from main.py so middleware can be composed cleanly and tested
independently.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import set_request_id


# Docs/OpenAPI paths are excluded from strict CSP so Swagger UI can load its
# external CDN assets. All API responses still get the hardened policy.
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Injects a unique X-Request-Id into every request and response.
    Propagated through logs via the contextvars-based request_id.
    Accepts an incoming X-Request-Id header (from a load balancer) or generates one.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming_id = request.headers.get("x-request-id")
        rid = set_request_id(incoming_id or uuid.uuid4().hex[:12])

        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds hardened security headers to every response.
    Docs paths get a relaxed CSP so Swagger UI can function.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not request.url.path.startswith(DOCS_PATHS):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response
