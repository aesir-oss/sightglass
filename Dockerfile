# syntax=docker/dockerfile:1
# One image for the API, the workers and migrations; deploy/compose.yaml picks the command. See docs/deploy.md.

# --- build: the pixi environment, the Rust extension and the frontend bundle ---
FROM ghcr.io/prefix-dev/pixi:0.81.0-noble@sha256:788ae451641666e2d1f79d3dbe35392dfc7e9b394b16a3acb75c347f3badb2ab AS build

WORKDIR /app
COPY pixi.toml pixi.lock ./
COPY .pixi/config.toml .pixi/config.toml
COPY backend/ backend/
# The environment comes from the lockfile only; sightglass itself is an editable install of backend/src.
RUN --mount=type=cache,target=/root/.cache/rattler \
    --mount=type=cache,target=/root/.cache/uv \
    pixi install --locked
# Release build of sightglass._core, placed in backend/src next to the Python package.
RUN --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/app/backend/target \
    cd backend && pixi run -- maturin develop --release --skip-install

COPY frontend/ frontend/
RUN pixi run build-web

# Activation script for the runtime stage: the environment's variables, then the container's command.
RUN pixi shell-hook --environment default --shell bash > /shell-hook.sh \
    && echo 'exec "$@"' >> /shell-hook.sh

# --- runtime: the environment and the built files, run as an unprivileged user ---
FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac AS runtime

RUN groupadd --system --gid 10001 sightglass \
    && useradd --system --uid 10001 --gid sightglass --home-dir /data --no-create-home --shell /usr/sbin/nologin sightglass \
    && mkdir -p /data/cache/blobs/.tmp /data/tmp \
    && chown -R sightglass:sightglass /data

# Same paths as the build stage: the editable install points at /app/backend/src.
COPY --from=build /app/.pixi/envs/default /app/.pixi/envs/default
COPY --from=build /app/backend/alembic.ini /app/backend/alembic.ini
COPY --from=build /app/backend/src /app/backend/src
COPY --from=build /app/frontend/dist /app/frontend/dist
COPY --from=build --chmod=0755 /shell-hook.sh /shell-hook.sh

ENV SIGHTGLASS_CACHE_DIR=/data/cache \
    SIGHTGLASS_FRONTEND_DIR=/app/frontend/dist \
    TMPDIR=/data/tmp \
    HOME=/data \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER sightglass
WORKDIR /app/backend
EXPOSE 8000
ENTRYPOINT ["/bin/bash", "/shell-hook.sh"]
CMD ["uvicorn", "sightglass.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
