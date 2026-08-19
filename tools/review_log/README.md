# Arche review log

This local Streamlit tool reviews an Arche adjudication pack without modifying
the original CSV. It validates the pack's decision-ID manifest, lets a reviewer
stage an accountable outcome, and downloads a separate labelled copy.

## Run with Python

```bash
pip install -r tools/review_log/requirements.txt
streamlit run tools/review_log/app.py
```

The default path is the Nigeria facility pack. Set `REVIEW_PACK` or use the
sidebar path input for another compatible pack.

## Run with Docker

```bash
docker build -t arche-review-log -f tools/review_log/Dockerfile .
docker run --rm -p 8501:8501 -v "${PWD}/data/review_packs/nigeria_facilities_2026-08-19:/data:ro" arche-review-log
```

Open `http://localhost:8501`. The mounted input is read-only. Use the download
button to save a labelled CSV outside the container.
