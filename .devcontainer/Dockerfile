# uv / uvx from the official image, pulled in as a named build stage so
# Dependabot tracks and bumps this tag (its docker ecosystem parses `FROM`, not
# `COPY --from=<image>`).
FROM ghcr.io/astral-sh/uv:0.11.28 AS uv

# Microsoft's Python devcontainer base
FROM mcr.microsoft.com/devcontainers/python:3.14-bookworm

# System libraries some Home Assistant dependencies expect to be present.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libturbojpeg0 libpcap-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/
