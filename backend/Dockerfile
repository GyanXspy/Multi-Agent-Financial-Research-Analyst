# ── Multi-stage Dockerfile for the FastAPI backend ──
# Stage 1: Install dependencies
# Stage 2: Slim runtime image

# --- Stage 1: Builder ---
# Use bookworm (Debian 12 stable) — trixie repos are unreliable in builds
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build



COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Stage 2: Runtime ---
FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

# Default: run with gunicorn + uvicorn workers
# Override with docker-compose or k8s for worker mode
CMD ["gunicorn", "app.main:app", \
     "-c", "gunicorn.conf.py"]
