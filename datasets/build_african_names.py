"""Simple runner script for building the African names lexicon."""

from __future__ import annotations

import sys

from datasets.names_dataops.cli import main

if __name__ == "__main__":
    args = ["build_lexicon", *sys.argv[1:]]
    raise SystemExit(main(args))
