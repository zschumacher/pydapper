"""The synchronous and asynchronous core conformance runners.

The runner owns every behavioral assertion and every result: cases pass only when
the framework's own checks pass, results are reported in the deterministic declared
order, per-case resources are isolated, and harness teardown runs after success and
failure. When both a case and its teardown fail, the case failure is preserved and
the teardown failure is retained as structured secondary information.

Failures are attributed to whoever caused them: a failure inside the harness's own
``create_commands()`` is reported as a harness setup failure
(``CaseResult.harness_setup_failed``), never as adapter misbehavior, so one broken
seeding call cannot masquerade as dozens of behavioral failures.

Both runners accept an optional ``case_ids`` filter for debugging one case against a
slow backend. Filtering is applied to the planned case list after planning and never
weakens reporting: unknown or empty selections raise before anything runs, and a
filtered report carries ``covers_full_inventory=False``.

``run_core_async`` is a plain awaitable and never starts an event loop, so it can be
awaited inside an existing loop, and task cancellation propagates promptly after the
active case's resources are released.
"""

import asyncio
from typing import Callable
from typing import Collection
from typing import List
from typing import Mapping
from typing import Optional
from typing import Tuple
from typing import TypeVar

from pydapper.capabilities import AdapterCapability

from ._checks import AsyncCaseContext
from ._checks import SyncCaseContext
from ._harness import AsyncAdapterHarness
from ._harness import SyncAdapterHarness
from ._profiles import AsyncCase
from ._profiles import ConformanceProfile
from ._profiles import SyncCase
from ._profiles import capability_profiles
from ._profiles import core_async_profile
from ._profiles import core_sync_profile
from ._profiles import validate_capability_catalog
from ._results import CaseCheckError
from ._results import CaseResult
from ._results import CaseSelectionError
from ._results import ConformanceReport
from ._results import HarnessDefinitionError
from ._results import HarnessSetupError

_HARNESS_CASE_ID = "<harness-validation>"

_CaseT = TypeVar("_CaseT", SyncCase, AsyncCase)


def _require_harness_identity(harness: object, profile_id: str) -> Tuple[str, str]:
    adapter_name = getattr(harness, "adapter_name", None)
    if not isinstance(adapter_name, str) or not adapter_name:
        raise HarnessDefinitionError(profile_id, _HARNESS_CASE_ID, "adapter_name")
    command_class = getattr(harness, "command_class", None)
    if not isinstance(command_class, type):
        raise HarnessDefinitionError(profile_id, _HARNESS_CASE_ID, "command_class")
    return adapter_name, f"{command_class.__module__}.{command_class.__qualname__}"


def _declared_capability_cases(
    harness: object,
    catalog: Mapping[AdapterCapability, ConformanceProfile],
    mode: str,
) -> List[Tuple[str, object]]:
    """Collect (profile_id, case) pairs for every declared capability with a profile.

    A declared capability *without* a populated profile is reported by the core
    ``capabilities.declared-profile-populated`` case; here we only run the profiles
    that exist. Order is deterministic: enum definition order, then declared case
    order.
    """
    command_class = getattr(harness, "command_class", None)
    declared: object = getattr(command_class, "capabilities", frozenset())
    if not isinstance(declared, frozenset):
        return []
    pairs: List[Tuple[str, object]] = []
    for member in AdapterCapability:
        if member not in declared:
            continue
        profile = catalog.get(member)
        if profile is None:
            continue
        cases = profile.sync_cases if mode == "sync" else profile.async_cases
        for case in cases:
            pairs.append((profile.profile_id, case))
    return pairs


def _select_cases(
    profile_id: str,
    planned: List[Tuple[str, _CaseT]],
    case_ids: Optional[Collection[str]],
) -> Tuple[List[Tuple[str, _CaseT]], bool]:
    """Narrow ``planned`` to ``case_ids``, returning the cases to run and completeness.

    ``case_ids`` is a debugging aid, not a conformance option: it is applied to the
    already-planned list (core profile cases plus declared-capability profile cases),
    so an id from either source selects. Every requested id must be planned and the
    selection must be non-empty — both failures raise :class:`CaseSelectionError`
    before any case runs, so a typo can never masquerade as a passing run. The second
    return value is ``True`` only when the run covers the full planned inventory.
    """
    if case_ids is None:
        return planned, True
    if isinstance(case_ids, str):
        raise TypeError(
            f"case_ids must be a collection of case ids, not a single string; pass e.g. case_ids=[{case_ids!r}]."
        )
    requested = tuple(dict.fromkeys(case_ids))
    if not requested:
        raise CaseSelectionError(profile_id, requested, ())
    known = {case.case_id for _, case in planned}
    unknown = tuple(case_id for case_id in requested if case_id not in known)
    if unknown:
        raise CaseSelectionError(profile_id, requested, unknown)
    wanted = set(requested)
    selected = [(case_profile_id, case) for case_profile_id, case in planned if case.case_id in wanted]
    return selected, len(selected) == len(planned)


def run_core_sync(
    harness: SyncAdapterHarness,
    *,
    capability_catalog: Optional[Mapping[AdapterCapability, ConformanceProfile]] = None,
    case_ids: Optional[Collection[str]] = None,
) -> ConformanceReport:
    """Run the mandatory ``core-sync`` profile against one sync adapter harness.

    Returns a :class:`ConformanceReport` whose results follow the declared case
    order; call :meth:`ConformanceReport.raise_for_failures` for exception-style
    reporting. ``capability_catalog`` defaults to the production catalog and only
    selects which capability profiles *additionally run*; the capability-honesty
    core cases always consult the production :func:`capability_profiles` catalog,
    so an injected catalog cannot make an unimplemented capability appear covered
    or weaken any core case.

    ``case_ids`` narrows the run to the named cases and exists only to shorten the
    debug loop against slow backends; it defaults to ``None``, which runs the full
    planned inventory exactly as before. Ids from the core profile and from any
    declared-capability profile both select. Unknown ids and empty selections raise
    :class:`CaseSelectionError` before any case runs, and a filtered run's report
    reports ``covers_full_inventory=False``, so a subset run can never be presented
    as conformance.
    """
    if not isinstance(harness, SyncAdapterHarness):
        raise TypeError(
            f"run_core_sync requires a SyncAdapterHarness; got {type(harness).__name__}. "
            "Async adapters run through run_core_async with an AsyncAdapterHarness."
        )
    profile = core_sync_profile()
    catalog = capability_profiles() if capability_catalog is None else capability_catalog
    validate_capability_catalog(catalog)
    adapter_name, command_class_name = _require_harness_identity(harness, profile.profile_id)

    planned: List[Tuple[str, SyncCase]] = [(profile.profile_id, case) for case in profile.sync_cases]
    planned.extend(_declared_capability_cases(harness, catalog, "sync"))  # type: ignore[arg-type]
    selected, covers_full_inventory = _select_cases(profile.profile_id, planned, case_ids)

    results: List[CaseResult] = []
    for case_profile_id, case in selected:
        ctx = SyncCaseContext(harness, case_profile_id, case.case_id, catalog)
        try:
            result = _run_sync_case(ctx, case)
        except BaseException:
            # cancellation/shutdown propagates, but the case's live resources are
            # still released first
            _teardown_sync(harness, ctx)
            raise
        cleanup_error = _teardown_sync(harness, ctx)
        results.append(_merge_cleanup(result, cleanup_error))

    return ConformanceReport(
        profile_id=profile.profile_id,
        adapter_name=adapter_name,
        command_class_name=command_class_name,
        results=tuple(results),
        covers_full_inventory=covers_full_inventory,
    )


async def run_core_async(
    harness: AsyncAdapterHarness,
    *,
    capability_catalog: Optional[Mapping[AdapterCapability, ConformanceProfile]] = None,
    case_ids: Optional[Collection[str]] = None,
) -> ConformanceReport:
    """Run the mandatory ``core-async`` profile against one async adapter harness.

    This coroutine is awaited inside the caller's existing event loop; the framework
    never calls ``asyncio.run()``. Semantics — including ``case_ids`` filtering and
    ``ConformanceReport.covers_full_inventory`` — otherwise match :func:`run_core_sync`.
    """
    if not isinstance(harness, AsyncAdapterHarness):
        raise TypeError(
            f"run_core_async requires an AsyncAdapterHarness; got {type(harness).__name__}. "
            "Sync adapters run through run_core_sync with a SyncAdapterHarness."
        )
    profile = core_async_profile()
    catalog = capability_profiles() if capability_catalog is None else capability_catalog
    validate_capability_catalog(catalog)
    adapter_name, command_class_name = _require_harness_identity(harness, profile.profile_id)

    planned: List[Tuple[str, AsyncCase]] = [(profile.profile_id, case) for case in profile.async_cases]
    planned.extend(_declared_capability_cases(harness, catalog, "async"))  # type: ignore[arg-type]
    selected, covers_full_inventory = _select_cases(profile.profile_id, planned, case_ids)

    results: List[CaseResult] = []
    for case_profile_id, case in selected:
        ctx = AsyncCaseContext(harness, case_profile_id, case.case_id, catalog)
        try:
            result = await _run_async_case(ctx, case)
        except BaseException:
            # cancellation/shutdown propagates, but the case's live resources are
            # still released first
            await _teardown_async(harness, ctx)
            raise
        cleanup_error = await _teardown_async(harness, ctx)
        results.append(_merge_cleanup(result, cleanup_error))

    return ConformanceReport(
        profile_id=profile.profile_id,
        adapter_name=adapter_name,
        command_class_name=command_class_name,
        results=tuple(results),
        covers_full_inventory=covers_full_inventory,
    )


#: Exceptions the runner must never convert into case failures: cancellation and
#: interpreter shutdown propagate after per-case teardown has run.
_PROPAGATED = (KeyboardInterrupt, SystemExit, asyncio.CancelledError)


def _run_sync_case(ctx: SyncCaseContext, case: SyncCase) -> CaseResult:
    return _execute_case(ctx, lambda: case.run(ctx))


async def _run_async_case(ctx: AsyncCaseContext, case: AsyncCase) -> CaseResult:
    try:
        await case.run(ctx)
    except BaseException as error:  # noqa: BLE001 - converted to structured results below
        return _failure_from_error(ctx, error)
    return CaseResult(profile_id=ctx.profile_id, case_id=ctx.case_id, passed=True)


def _execute_case(ctx: SyncCaseContext, run: Callable[[], None]) -> CaseResult:
    try:
        run()
    except BaseException as error:  # noqa: BLE001 - converted to structured results below
        return _failure_from_error(ctx, error)
    return CaseResult(profile_id=ctx.profile_id, case_id=ctx.case_id, passed=True)


def _failure_from_error(ctx: object, error: BaseException) -> CaseResult:
    profile_id = getattr(ctx, "profile_id", "<unknown>")
    case_id = getattr(ctx, "case_id", "<unknown>")
    if isinstance(error, _PROPAGATED):
        raise error
    if isinstance(error, HarnessDefinitionError):
        return CaseResult(
            profile_id=profile_id,
            case_id=case_id,
            passed=False,
            message=str(error),
            cause=error,
            missing_field=error.missing_field,
        )
    if isinstance(error, HarnessSetupError):
        # the harness's own create_commands() broke: report the harness, not the adapter,
        # while preserving the original exception as the cause
        return CaseResult(
            profile_id=profile_id,
            case_id=case_id,
            passed=False,
            message=str(error),
            cause=error.cause,
            harness_setup_failed=True,
        )
    if isinstance(error, CaseCheckError):
        return CaseResult(
            profile_id=profile_id,
            case_id=case_id,
            passed=False,
            message=str(error),
            cause=error.cause if error.cause is not None else error,
        )
    return CaseResult(
        profile_id=profile_id,
        case_id=case_id,
        passed=False,
        message=f"unexpected {type(error).__name__}: {error}",
        cause=error,
    )


def _teardown_sync(harness: SyncAdapterHarness, ctx: SyncCaseContext) -> Optional[BaseException]:
    first_error: Optional[BaseException] = None
    for commands in ctx.created_commands:
        try:
            harness.teardown_commands(commands)
        except Exception as error:  # noqa: BLE001 - retained as structured cleanup info
            if first_error is None:
                first_error = error
    return first_error


async def _teardown_async(harness: AsyncAdapterHarness, ctx: AsyncCaseContext) -> Optional[BaseException]:
    first_error: Optional[BaseException] = None
    for commands in ctx.created_commands:
        try:
            await harness.teardown_commands(commands)
        except Exception as error:  # noqa: BLE001 - retained as structured cleanup info
            if first_error is None:
                first_error = error
    return first_error


def _merge_cleanup(result: CaseResult, cleanup_error: Optional[BaseException]) -> CaseResult:
    if cleanup_error is None:
        return result
    if result.passed:
        return CaseResult(
            profile_id=result.profile_id,
            case_id=result.case_id,
            passed=False,
            message=f"harness teardown failed after a passing case: {cleanup_error}",
            cause=cleanup_error,
            cleanup_error=cleanup_error,
        )
    return CaseResult(
        profile_id=result.profile_id,
        case_id=result.case_id,
        passed=False,
        message=result.message,
        cause=result.cause,
        missing_field=result.missing_field,
        cleanup_error=cleanup_error,
        harness_setup_failed=result.harness_setup_failed,
    )
