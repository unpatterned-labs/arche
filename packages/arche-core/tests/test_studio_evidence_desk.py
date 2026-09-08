# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Regression checks for the Evidence Desk controls in arche studio."""

import importlib.util
from pathlib import Path

#: The page as shipped, wherever the package is installed.
_INDEX = Path(importlib.util.find_spec("arche._studio").origin).with_name("index.html")


def test_command_dialog_respects_the_hidden_attribute():
    """The palette must disappear when navigation closes it.

    A class selector setting `display: grid` can override the browser's default
    hidden treatment. This rule keeps the command dialog from masking the
    workspace after the user chooses a destination.
    """
    page = _INDEX.read_text(encoding="utf-8")

    assert ".command[hidden]{display:none}" in page
