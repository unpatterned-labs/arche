# arche-core, with every parser and model inside it.
#
#   docker build -t arche-core packages/arche-core
#   docker run -p 8766:8766 -v arche-data:/data arche-core
#
# Why this lives in a library repository at all: the build calls
# `arche._service.warm()` and FAILS if any model or parser does not load.
# That is a test, and it is the only one that proves the model extras
# (`detect2`, `doc`, `doc-ocr`) install and import together on Linux -- it
# found the CUDA-torch default and the torchvision/transformers import
# failure that no unit test could see. CI builds it for that reason.
#
# It is also a runnable image: `arche serve` on 0.0.0.0 inside the container,
# CPU only, nothing fetched at runtime (HF_HUB_OFFLINE), non-root, a
# healthcheck that waits for the warm start. It has no authentication of its
# own. Composing it behind a proxy, multi-workspace, keys -- that is the
# hosted product's concern, not this file's, which is why there is no
# compose file beside it.

# ---- 1. build the wheel from this checkout ---------------------------------
FROM python:3.12-slim AS build
WORKDIR /src
COPY . /src/arche-core
RUN pip install --no-cache-dir hatchling \
 && pip wheel --no-deps --no-cache-dir -w /wheels /src/arche-core

# ---- 2. the runtime, with weights baked in ----------------------------------
FROM python:3.12-slim AS runtime

# Where the weights live. HF_HOME is where huggingface_hub caches; ARCHE_MODEL_DIR
# is arche's own air-gapped lookup. Both point inside the image.
ENV HF_HOME=/models/hf \
    ARCHE_MODEL_DIR=/models/arche \
    ARCHE_WARM=1 \
    ARCHE_LEDGER=/data/ledger.duckdb \
    PYTHONUNBUFFERED=1 \
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

COPY --from=build /wheels /wheels
RUN pip install "$(ls /wheels/arche_core-*.whl)[pdf,docx,doc,doc-ocr,detect2,service,resolve,ledger]" \
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

RUN useradd --create-home --uid 1000 arche \
 && mkdir -p /data && chown arche:arche /data
USER arche
VOLUME ["/data"]
EXPOSE 8766

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request,json,sys; b=json.load(urllib.request.urlopen('http://127.0.0.1:8766/livez')); sys.exit(0 if b.get('ok') and b.get('warm') else 1)"

CMD ["arche", "serve", "--host", "0.0.0.0", "--port", "8766", "--warm"]
