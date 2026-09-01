"""MIOS V5 — Institutional Market Intelligence Operating System.

Version-locked architecture: see SPEC_V5.0.md in this package.
Core contract + orchestrator live in mios_v5.core; stage engines in
mios_v5.engines; dashboard panels in mios_v5.ui.
"""

__version__ = "5.0.0-alpha.1"

from .core import (  # noqa: F401
    Bias, Engine, EngineError, EngineResult, ErrorType, MarketState,
    Orchestrator, Provenance, RunReport, Severity, Status, Tier,
)
