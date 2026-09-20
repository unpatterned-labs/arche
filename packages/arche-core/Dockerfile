# arche as a container: the service, the CLI and the MCP server, with every
# parser and both models inside it.
#
#   docker build -f packages/arche-core/Dockerfile -t arche-core .
#   docker run --rm -p 8766:8766 -v arche-data:/data arche-core        # arche serve
#   docker run --rm -i arche-core mcp                                  # an MCP server on stdio
#   docker run --rm arche-core detect --jurisdiction NG "Adaeze, NIN 12345678901"
#   docker run --rm arche-core --help
#
# `arche` is the entrypoint, so every subcommand works as an argument, and the
# default is `serve`. `mcp` is the case a container helps most: an agent
# runtime can start arche without Python, the extras or the weights on the
# host --
#
#   {"mcpServers": {"arche": {"command": "docker",
#                             "args": ["run", "-i", "--rm", "ghcr.io/unpatterned-labs/arche-core", "mcp"]}}}
#
# Why this lives in a library repository at all: the build calls
# `arche._service.warm()` and FAILS if any model or parser does not load.
# That is a test, and it is the only one that proves the model extras
# (`detect2`, `doc`, `doc-ocr`) install and import together on Linux -- it
# found the CUDA-torch default and the torchvision/transformers import
# failure that no unit test could see. CI builds it for that reason, and
# publishes it to GHCR from main and from release tags.
#
# CPU only, nothing fetched at runtime (HF_HUB_OFFLINE), non-root, a
# healthcheck that waits for the warm start. It has no authentication of its
# own. Composing it behind a proxy, multi-workspace, keys -- that is the
# hosted product's concern, not this file's, which is why there is no
# compose file beside it.

# ---- 1. build the wheels from this checkout ---------------------------------
FROM python:3.12-slim AS build
WORKDIR /src
# Context is the repository root, so `deploy/compose.yaml` can build it with
# `context: ..`. The root .dockerignore keeps caches, worlds and local data out.
COPY packages/arche-core /src/arche-core
RUN pip install --no-cache-dir hatchling \
 && pip wheel --no-deps --no-cache-dir -w /wheels /src/arche-core

# ---- 2. the runtime, with weights baked in ----------------------------------
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="arche-core" \
      org.opencontainers.image.description="Entity resolution and personal-data handling with a receipt: detect, deidentify, compare, reconcile, documents -- with the statute attached and a decision id that replays" \
      org.opencontainers.image.source="https://github.com/unpatterned-labs/arche" \
      org.opencontainers.image.licenses="Apache-2.0"

# Where the weights live. HF_HOME is where huggingface_hub caches; ARCHE_MODEL_DIR
# is arche's own air-gapped lookup. Both point inside the image.
# Unbuffered so MCP responses reach the client immediately: a stdio protocol
# behind a block buffer looks like a hang.
ENV HF_HOME=/models/hf \
    ARCHE_MODEL_DIR=/models/arche \
    ARCHE_WARM=1 \
    ARCHE_LEDGER=/data/ledger.duckdb \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# libgl/glib: docling's layout models and RapidOCR link against OpenCV.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# CPU torch AND torchvision first, from PyTorch's own CPU index. Without this
# line pip resolves `gliner2[local]` -> torch to the default Linux wheel,
# which is the CUDA build: two gigabytes of driver libraries for a container
# that runs on CPU by design. torchvision has to come from the same index in
# the same command: docling pulls it, and a PyPI torchvision against a CPU
# torch fails at import with "operator torchvision::nms does not exist",
# which surfaces three layers up as transformers refusing to load
# PreTrainedModel. Measured on the first build of this file.
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# The core wheel with every parser and model extra, the service and the MCP
# server. The `[local]` marker inside `detect2` is load-bearing: bare `gliner2`
# is an API client that posts text to a hosted service.
COPY --from=build /wheels /wheels
RUN pip install "$(ls /wheels/arche_core-*.whl)[pdf,docx,doc,doc-ocr,detect2,service,resolve,ledger,mcp]" \
 && rm -rf /wheels

# Pull every model once, at build time, through the same code path the
# service uses at startup. `warm()` loads GLiNER 2, GLiNER2-PII and constructs
# docling's converter (which fetches its layout and table models). The result
# is printed so a failed download fails the build, not the first request.
RUN python - <<'EOF'
import json
from arche._service import warm
loaded = warm()
print(json.dumps(loaded, indent=2))
bad = {k: v for k, v in loaded.items() if v is not True}
if bad:
    raise SystemExit(f"model warm-up failed: {bad}")
if not loaded:
    raise SystemExit("nothing loaded: are the detect2 and doc extras installed?")
EOF

# From here on, no network is needed and none is attempted for models.
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

# Nothing here needs root, and an agent runtime starting this unattended is
# exactly the case where that matters.
RUN useradd --create-home --uid 10001 arche \
 && mkdir -p /data && chown arche:arche /data
USER arche
WORKDIR /home/arche
VOLUME ["/data"]
EXPOSE 8766

# A container that starts but has not finished loading its models is the
# failure worth catching, and it is not visible from `arche --version`. Only
# meaningful under `serve`; a `mcp` or one-shot container has no port.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request,json,sys; b=json.load(urllib.request.urlopen('http://127.0.0.1:8766/livez')); sys.exit(0 if b.get('ok') and b.get('warm') else 1)"

# `arche` as the entrypoint means every subcommand works as an argument. The
# default is the service; `mcp` is the server on stdio (needs `-i`).
ENTRYPOINT ["arche"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8766", "--warm"]

# To keep the ledger, mount /data. To sign every answer, make a key on the
# volume and name it:
#
#   docker run --rm -v arche-data:/data arche-core attest keygen /data/signing.pem
#   docker run --rm -p 8766:8766 -v arche-data:/data -e ARCHE_SIGNING_KEY=/data/signing.pem arche-core
