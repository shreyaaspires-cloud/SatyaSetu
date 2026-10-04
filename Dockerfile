# SatyaSetu Backend Dockerfile
# Optimized for Python 3.12, multi-stage, secure non-root user

FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Install system dependencies for audio/image processing (ffmpeg, libgl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy dependency files
COPY requirements.txt ./

# Install python dependencies
RUN uv pip install --system --no-cache -r requirements.txt

# Copy application source
COPY app/ ./app/
COPY app_main.py main.py ./
COPY .env.example ./.env

# Create non-root user
RUN useradd -m -u 1000 satyasetu && chown -R satyasetu:satyasetu /app
USER satyasetu

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["sh", "-c", "uvicorn app_main:app --host 0.0.0.0 --port ${PORT}"]
