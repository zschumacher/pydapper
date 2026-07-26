"""Profile and case definitions plus the production capability-profile catalog.

``core-sync`` and ``core-async`` are the mandatory per-mode profiles. Optional
capability profiles are keyed to :class:`~pydapper.capabilities.AdapterCapability`
members; each capability feature adds its own independent profile here in the same
change that implements the feature — an unimplemented capability must never appear
covered. The production catalog is immutable and currently ships the
``transactions`` profile.

The capability surface (:class:`ConformanceProfile`, :class:`SyncCase`,
:class:`AsyncCase`, and :func:`capability_profiles`) is stable alongside the
mandatory core profiles.
"""

import inspect
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Mapping
from typing import Optional
from typing import Tuple

from pydapper.capabilities import AdapterCapability

from ._results import ProfileDefinitionError

if TYPE_CHECKING:
    from ._checks import AsyncCaseContext
    from ._checks import SyncCaseContext

#: Stable identifier of the mandatory synchronous core profile.
CORE_SYNC = "core-sync"

#: Stable identifier of the mandatory asynchronous core profile.
CORE_ASYNC = "core-async"

#: Stable identifier of the optional ``transactions`` capability profile.
TRANSACTIONS_PROFILE = "transactions"

#: Case kinds: ``"live"`` cases run through the harness's real database resources;
#: ``"instrumented"`` cases run the real concrete command class around
#: framework-owned recording/fault-injection connections.
CASE_KINDS = ("live", "instrumented")


@dataclass(frozen=True)
class SyncCase:
    """One named synchronous conformance case. ``run`` is framework-owned.

    Adapter authors do not write cases; profiles ship with the framework.
    """

    case_id: str
    description: str
    kind: str
    run: Callable[["SyncCaseContext"], None]


@dataclass(frozen=True)
class AsyncCase:
    """One named asynchronous conformance case. ``run`` is framework-owned.

    See :class:`SyncCase`.
    """

    case_id: str
    description: str
    kind: str
    run: Callable[["AsyncCaseContext"], Awaitable[None]]


def _validate_cases(profile_id: str, cases: Tuple[Any, ...], mode: str) -> None:
    seen = set()
    for case in cases:
        if case.kind not in CASE_KINDS:
            raise ProfileDefinitionError(profile_id, f"{mode} case {case.case_id!r} has invalid kind {case.kind!r}")
        if case.case_id in seen:
            raise ProfileDefinitionError(profile_id, f"duplicate {mode} case id {case.case_id!r}")
        seen.add(case.case_id)
        # a mode/run mismatch would otherwise surface only at run time, as a confusing
        # TypeError from awaiting None (or a sync body silently executing its side effects)
        is_coroutine = inspect.iscoroutinefunction(case.run)
        if mode == "async" and not is_coroutine:
            raise ProfileDefinitionError(profile_id, f"{mode} case {case.case_id!r} run must be a coroutine function")
        if mode == "sync" and is_coroutine:
            raise ProfileDefinitionError(
                profile_id, f"{mode} case {case.case_id!r} run must not be a coroutine function"
            )


@dataclass(frozen=True)
class ConformanceProfile:
    """A named, per-mode set of conformance cases.

    A profile must contain at least one case; zero-case profiles are rejected so an
    empty profile can never make a capability appear covered. Case identifiers are
    unique per mode and case order is the deterministic execution and reporting
    order.
    """

    profile_id: str
    capability: Optional[AdapterCapability]
    sync_cases: Tuple[SyncCase, ...] = ()
    async_cases: Tuple[AsyncCase, ...] = ()

    def __post_init__(self) -> None:
        if not self.profile_id or not isinstance(self.profile_id, str):
            raise ProfileDefinitionError(str(self.profile_id), "profile_id must be a non-empty string")
        if self.capability is not None and not isinstance(self.capability, AdapterCapability):
            raise ProfileDefinitionError(
                self.profile_id,
                f"capability must be an AdapterCapability member or None, got {type(self.capability).__name__}",
            )
        if not self.sync_cases and not self.async_cases:
            raise ProfileDefinitionError(self.profile_id, "a conformance profile must define at least one case")
        _validate_cases(self.profile_id, tuple(self.sync_cases), "sync")
        _validate_cases(self.profile_id, tuple(self.async_cases), "async")


def core_sync_profile() -> ConformanceProfile:
    """Build the mandatory ``core-sync`` profile with its full case inventory."""
    from ._cases_sync import sync_core_cases

    return ConformanceProfile(profile_id=CORE_SYNC, capability=None, sync_cases=sync_core_cases())


def core_async_profile() -> ConformanceProfile:
    """Build the mandatory ``core-async`` profile with its full case inventory."""
    from ._cases_async import async_core_cases

    return ConformanceProfile(profile_id=CORE_ASYNC, capability=None, async_cases=async_core_cases())


def transactions_profile() -> ConformanceProfile:
    """Build the optional ``transactions`` capability profile.

    Both modes ship the same nine case ids in the same order, so sync and async
    declaring adapters are held to one contract.
    """
    from ._cases_transactions import transactions_sync_cases
    from ._cases_transactions_async import transactions_async_cases

    return ConformanceProfile(
        profile_id=TRANSACTIONS_PROFILE,
        capability=AdapterCapability.TRANSACTIONS,
        sync_cases=transactions_sync_cases(),
        async_cases=transactions_async_cases(),
    )


def capability_profiles() -> Mapping[AdapterCapability, ConformanceProfile]:
    """Return the production catalog of optional capability profiles.

    The catalog is immutable. Capability features register their profile here in the
    same change that implements the capability, keyed by the owning
    :class:`AdapterCapability` member; a capability with no profile here is not
    implemented and may not be declared by any command class.
    """
    return MappingProxyType({AdapterCapability.TRANSACTIONS: transactions_profile()})


def validate_capability_catalog(catalog: Mapping[AdapterCapability, ConformanceProfile]) -> None:
    """Validate a capability-profile catalog's structural integrity.

    Keys must be :class:`AdapterCapability` members and each profile must declare the
    same capability it is keyed under. Zero-case profiles are already impossible by
    construction.
    """
    for capability, profile in catalog.items():
        if not isinstance(capability, AdapterCapability):
            raise ProfileDefinitionError(
                getattr(profile, "profile_id", "<unknown>"),
                f"capability catalog key must be an AdapterCapability member, got {type(capability).__name__}",
            )
        if not isinstance(profile, ConformanceProfile):
            raise ProfileDefinitionError(
                "<unknown>",
                f"capability catalog value for {capability.value!r} must be a ConformanceProfile, "
                f"got {type(profile).__name__}",
            )
        if profile.capability is not capability:
            raise ProfileDefinitionError(
                profile.profile_id,
                f"profile is keyed under capability {capability.value!r} but declares "
                f"{profile.capability.value if profile.capability else None!r}",
            )
