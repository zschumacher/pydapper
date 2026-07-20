"""Reusable adapter conformance suite for pydapper command classes.

Adapter authors implement a :class:`SyncAdapterHarness` and/or
:class:`AsyncAdapterHarness` for their concrete command classes and run the
mandatory per-mode core profiles::

    from pydapper.testing.adapter_conformance import run_core_sync

    report = run_core_sync(MyAdapterHarness())
    report.raise_for_failures()

``core-sync`` and ``core-async`` are independent mandatory profiles; a dual-mode
adapter must pass both. Optional capabilities are covered by independent capability
profiles keyed to :class:`pydapper.AdapterCapability`; see :func:`capability_profiles`.

This package uses only the standard library and pydapper core: it never imports
pytest, optional database drivers, or any test-service tooling, and importing it
starts nothing.
"""

from ._harness import AsyncAdapterHarness
from ._harness import SyncAdapterHarness
from ._profiles import CORE_ASYNC
from ._profiles import CORE_SYNC
from ._profiles import AsyncCase
from ._profiles import ConformanceProfile
from ._profiles import SyncCase
from ._profiles import capability_profiles
from ._profiles import core_async_profile
from ._profiles import core_sync_profile
from ._results import CaseResult
from ._results import ConformanceError
from ._results import ConformanceFailureError
from ._results import ConformanceReport
from ._results import HarnessDefinitionError
from ._results import ProfileDefinitionError
from ._runner import run_core_async
from ._runner import run_core_sync
from ._sqlspec import CONFORMANCE_COLUMNS
from ._sqlspec import CONFORMANCE_ROWS
from ._sqlspec import seed_rows

__all__ = [
    "CORE_ASYNC",
    "CORE_SYNC",
    "CONFORMANCE_COLUMNS",
    "CONFORMANCE_ROWS",
    "AsyncAdapterHarness",
    "AsyncCase",
    "CaseResult",
    "ConformanceError",
    "ConformanceFailureError",
    "ConformanceProfile",
    "ConformanceReport",
    "HarnessDefinitionError",
    "ProfileDefinitionError",
    "SyncAdapterHarness",
    "SyncCase",
    "capability_profiles",
    "core_async_profile",
    "core_sync_profile",
    "run_core_async",
    "run_core_sync",
    "seed_rows",
]
