# The arche development environment: every extra, the tests, the benchmarks.
#
#   docker build -f .devcontainer/Dockerfile -t arche-dev .
#   docker run --rm -it -v "$PWD":/workspace arche-dev
#   docker run --rm -v "$PWD":/workspace arche-dev uv run pytest packages/arche-core/tests -q
#
# The runtime image (packages/arche-core/Dockerfile) is what a user runs. This
# is what a contributor and CI run: the workspace, uv, the dev group and all
# of arche-core's extras -- Splink, DuckDB, docling, RapidOCR, both GLiNER
# models -- installed the way that works on Linux (CPU torch from PyTorch's
# own index, before anything can pull the CUDA build). The suite, the
# benchmark gate and the synthetic worlds then run in one container on any
# machine, and a laptop's own cache can no longer be the reason a test passes
# or fails. Published as ghcr.io/<owner>/arche-dev alongside the runtime image.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    HF_HOME=/models/hf \
    ARCHE_MODEL_DIR=/models/arche \
    PATH="/opt/venv/bin:/root/.local/bin:${PATH}"

RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl libgl1 libglib2.0-0 build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /usr/local/bin/

WORKDIR /workspace

# Dependencies first, so a source change does not reinstall the world. The
# workspace pyproject and lock are enough for uv to resolve; the package
# sources are mounted or copied afterwards.
COPY pyproject.toml uv.lock ./
COPY packages/arche-core/pyproject.toml packages/arche-core/README.md packages/arche-core/
# The wheel needs the version file to exist even for a metadata-only build.
COPY packages/arche-core/src/arche/_version.py packages/arche-core/src/arche/_version.py

# CPU torch comes from the lock: the root pyproject pins torch and torchvision
# to PyTorch's CPU index on Linux (`[tool.uv.sources]`), so `uv sync` cannot
# resolve the CUDA build here or on any contributor's Linux machine. The
# first version of this file installed CPU torch by hand first, and the next
# `uv sync` quietly replaced it with the lock's CUDA build: 2.7 GB of driver
# libraries in an image that runs on CPU by design.
#
# The uv cache lives in a BuildKit cache mount, not in the layer, so no wheel
# sits in the image twice.
RUN --mount=type=cache,target=/root/.cache/uv     uv venv /opt/venv  && uv sync --all-packages --group full --no-install-workspace

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv     uv sync --all-packages --group full

# Warm the models so the first test that needs them does not download them.
# `warm()` reports rather than raises; the dev image tolerates a model that
# will not load (a contributor may not need it) but says so in the build log.
RUN uv run python -c "import json; from arche._service import warm; print(json.dumps(warm(), indent=2))"

CMD ["bash"]
