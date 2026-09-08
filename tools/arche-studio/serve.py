#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""arche studio lives in the wheel now: ``arche studio``, or ``python -m arche._studio``.

This file stays so an old bookmark still works. It adds the checkout's source
tree to the path when arche is not installed, then hands over.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "packages" / "arche-core" / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from arche._studio import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
