# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""arche caps torch's CPU threads around its model calls, and puts them back.

torch defaults to every logical CPU. On a 16-thread WSL2 laptop, against a cap
of 8: masking one invoice 965 ms vs 760 ms, one encoder query 556 ms vs 6 ms.
The cap changes speed only, so it is never pinned."""

from __future__ import annotations

import arche
import pytest
from arche._models import torch_thread_count, torch_threads

torch = pytest.importorskip("torch")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    monkeypatch.delenv("MKL_NUM_THREADS", raising=False)
    before = torch.get_num_threads()
    yield
    arche.configure(torch_threads=None)
    torch.set_num_threads(before)


class TestCount:
    def test_automatic_is_half_the_cpus_at_most_eight(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 16)
        assert torch_thread_count() == 8
        monkeypatch.setattr("os.cpu_count", lambda: 4)
        assert torch_thread_count() == 2
        monkeypatch.setattr("os.cpu_count", lambda: 1)
        assert torch_thread_count() == 1

    def test_the_environment_wins_over_automatic(self, monkeypatch):
        monkeypatch.setenv("OMP_NUM_THREADS", "3")
        assert torch_thread_count() is None

    def test_configured_and_requested(self):
        arche.configure(torch_threads=3)
        assert torch_thread_count() == 3
        assert torch_thread_count(5) == 5
        arche.configure(torch_threads=0)
        assert torch_thread_count() is None

    @pytest.mark.parametrize("bad", [-1, 2.5, True, "4"])
    def test_configure_rejects_what_is_not_a_count(self, bad):
        with pytest.raises(TypeError, match="torch_threads"):
            arche.configure(torch_threads=bad)


def test_the_cap_holds_inside_and_is_restored_after():
    torch.set_num_threads(6)
    with torch_threads(2):
        assert torch.get_num_threads() == 2
    assert torch.get_num_threads() == 6


def test_restored_even_when_the_model_raises():
    torch.set_num_threads(6)
    with pytest.raises(RuntimeError), torch_threads(2):
        raise RuntimeError("model failed")
    assert torch.get_num_threads() == 6


def test_zero_leaves_torch_alone():
    torch.set_num_threads(6)
    arche.configure(torch_threads=0)
    with torch_threads():
        assert torch.get_num_threads() == 6


def test_gliner_runs_under_the_cap(monkeypatch):
    seen = []

    class Model:
        def extract_entities(self, text, labels, **kw):
            seen.append(torch.get_num_threads())
            return {"entities": {"person": [{"text": "Ada", "start": 0, "end": 3,
                                             "confidence": 0.9}]}}

    monkeypatch.setattr("arche._models.get_gliner2", lambda *a, **k: Model())
    from arche.detect._gliner2 import propose

    torch.set_num_threads(6)
    arche.configure(torch_threads=2)
    spans = propose("Ada", ["person"], model="m", threshold=0.5, runtime="torch")
    assert seen == [2] and torch.get_num_threads() == 6
    assert [s.text for s in spans] == ["Ada"]
