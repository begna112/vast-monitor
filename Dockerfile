# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12.2
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies early to leverage Docker layer caching
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create an unprivileged user with a writable home (vastai SDK needs one)
ARG UID=10001
ARG GID=10001
RUN groupadd --gid ${GID} appuser \
    && useradd --uid ${UID} --gid appuser --shell /usr/sbin/nologin --create-home --home-dir /home/appuser appuser
ENV HOME=/home/appuser

# Copy application source as the runtime user
COPY --chown=appuser:appuser . .
COPY --chown=appuser:appuser entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser

ENTRYPOINT ["/entrypoint.sh"]
CMD []
