"""Stub allocator tests."""

from __future__ import annotations

import pandas as pd
from aa_model.allocation.constraints import Constraints
from aa_model.allocation.stub import StubAllocator
from aa_model.assumptions.cma import CMA
from aa_model.io.schemas import PublicAllocationConfig


def test_stub_returns_config_weights():
    cfg = PublicAllocationConfig(stub_weights={"a": 0.3, "b": 0.7})
    a = StubAllocator(cfg)
    a.fit(pd.DataFrame(), CMA(), Constraints())
    w = a.weights()
    assert w["a"] == 0.3
    assert w["b"] == 0.7
    assert abs(w.sum() - 1.0) < 1e-12


def test_stub_diagnostics_records_fit_inputs():
    cfg = PublicAllocationConfig(stub_weights={"a": 1.0})
    a = StubAllocator(cfg)
    returns = pd.DataFrame({"a": [0.01, 0.02]})
    a.fit(returns, CMA(), Constraints(min_weights={"a": 0.0}, max_weights={"a": 1.0}))
    d = a.diagnostics()
    assert d["engine"] == "stub"
    assert d["fit_inputs"]["returns_shape"] == (2, 1)
    assert d["fit_inputs"]["n_constraints"] == 2


def test_weights_are_a_copy():
    cfg = PublicAllocationConfig(stub_weights={"a": 0.6, "b": 0.4})
    a = StubAllocator(cfg)
    a.fit(pd.DataFrame(), CMA(), Constraints())
    w = a.weights()
    w["a"] = 0.0
    # Mutating the returned series must not affect subsequent calls.
    w2 = a.weights()
    assert w2["a"] == 0.6
