"""Structured results and exceptions for adapter conformance runs.

Every failure is identified by structured attributes (profile id, case id, original
cause, whether the harness's own setup raised, and — for harness validation failures
— the missing harness field) so callers never need to parse exception prose.
"""

from dataclasses import dataclass
from dataclasses import field
from typing import Optional
from typing import Tuple


class ConformanceError(Exception):
    """Base class for every error raised by the adapter conformance framework."""


class ProfileDefinitionError(ConformanceError):
    """A conformance profile definition is invalid (zero cases or duplicate case ids)."""

    def __init__(self, profile_id: str, message: str) -> None:
        self.profile_id = profile_id
        super().__init__(f"Invalid conformance profile {profile_id!r}: {message}")


class HarnessDefinitionError(ConformanceError):
    """A harness does not supply a field a conformance case requires.

    Carries the profile id, the case id that needed the field, and the missing
    harness field name as structured attributes.
    """

    def __init__(self, profile_id: str, case_id: str, missing_field: str, message: Optional[str] = None) -> None:
        self.profile_id = profile_id
        self.case_id = case_id
        self.missing_field = missing_field
        detail = message or (
            f"Harness is missing required field {missing_field!r} "
            f"needed by conformance case {profile_id!r}/{case_id!r}"
        )
        super().__init__(detail)


class HarnessSetupError(ConformanceError):
    """The harness's own ``create_commands()`` raised while preparing a case.

    This is a harness failure — a broken connection factory or a broken seeding
    statement — and not a verdict on the adapter, whose behavior under test never got
    to run. Raised by the case context around the harness call only, and converted by
    the runner into a failed :class:`CaseResult` with ``harness_setup_failed=True``
    whose ``cause`` is the original :attr:`cause` exception, so it never reaches
    callers itself.
    """

    def __init__(self, profile_id: str, case_id: str, cause: BaseException) -> None:
        self.profile_id = profile_id
        self.case_id = case_id
        self.cause = cause
        super().__init__(
            f"harness setup failed: the harness's own create_commands() raised "
            f"{type(cause).__name__}: {cause} while preparing conformance case {profile_id!r}/{case_id!r}. "
            "This is a harness failure (connection factory or dataset seeding), not adapter behavior "
            "under test; fix the harness before reading anything into this run."
        )


class CaseSelectionError(ConformanceError):
    """A ``case_ids`` selection does not name a runnable subset of the planned cases.

    Raised before any case runs, so a mistyped id can never be silently reduced to a
    vacuous "everything selected passed" run. Carries the profile id, the requested
    ids, and the unknown ids as structured attributes; ``unknown_case_ids`` is empty
    when the selection itself was empty.
    """

    def __init__(
        self,
        profile_id: str,
        requested_case_ids: Tuple[str, ...],
        unknown_case_ids: Tuple[str, ...],
    ) -> None:
        self.profile_id = profile_id
        self.requested_case_ids = requested_case_ids
        self.unknown_case_ids = unknown_case_ids
        if unknown_case_ids:
            detail = (
                f"case_ids named {len(unknown_case_ids)} case(s) that profile {profile_id!r} does not plan: "
                f"{', '.join(repr(case_id) for case_id in unknown_case_ids)}. "
                "List the planned ids with core_sync_profile().sync_cases / core_async_profile().async_cases "
                "plus any declared-capability profile cases."
            )
        else:
            detail = (
                f"case_ids selected no conformance cases for profile {profile_id!r}; "
                "an empty selection is not a conformance run. Pass case_ids=None to run the full profile."
            )
        super().__init__(detail)


class CaseCheckError(ConformanceError):
    """A conformance assertion made by the framework runner failed.

    Raised internally by case implementations and converted by the runner into a
    failed :class:`CaseResult`. The optional ``cause`` preserves the adapter-raised
    exception that triggered the failure, when there is one.
    """

    def __init__(self, message: str, cause: Optional[BaseException] = None) -> None:
        self.cause = cause
        super().__init__(message)


@dataclass(frozen=True)
class CaseResult:
    """The outcome of one named conformance case in one profile run.

    ``cause`` preserves the original exception behind a failure when one exists, and
    ``missing_field`` names the absent harness field when harness validation failed.
    ``cleanup_error`` retains a harness teardown failure as structured secondary
    information; it never replaces an active case failure.

    ``harness_setup_failed`` is ``True`` only when the harness's own
    ``create_commands()`` raised — the connection factory or the dataset seeding
    broke — so this result says nothing about the adapter's behavior. It is
    ``repr``-visible on purpose: a printed result must show at a glance that the
    harness, not the adapter, is what failed. It defaults to ``False``, so every
    other failure kind keeps its existing shape.
    """

    profile_id: str
    case_id: str
    passed: bool
    message: str = ""
    cause: Optional[BaseException] = field(default=None, repr=False)
    missing_field: Optional[str] = None
    cleanup_error: Optional[BaseException] = field(default=None, repr=False)
    harness_setup_failed: bool = False


class ConformanceFailureError(ConformanceError):
    """Raised by :meth:`ConformanceReport.raise_for_failures` when any case failed.

    ``failures`` is the deterministic, profile-ordered tuple of failed case results;
    ``report`` is the full run report.
    """

    def __init__(self, report: "ConformanceReport") -> None:
        self.report = report
        self.failures: Tuple[CaseResult, ...] = report.failures
        first = self.failures[0] if self.failures else None
        summary = (
            f"{len(self.failures)} conformance case(s) failed for profile {report.profile_id!r} "
            f"({report.adapter_name!r} / {report.command_class_name})"
        )
        setup_failures = tuple(failure for failure in self.failures if failure.harness_setup_failed)
        if setup_failures:
            summary = (
                f"{summary} [HARNESS SETUP FAILED: {len(setup_failures)} of {len(self.failures)} failure(s) "
                f"came from the harness's own create_commands(), not adapter behavior; fix the harness first]"
            )
        if not report.covers_full_inventory:
            summary = (
                f"{summary} [PARTIAL RUN: a case_ids filter was applied, so this run "
                f"covered only {len(report.results)} planned case(s) and is not a conformance run]"
            )
        if first is not None:
            summary = f"{summary}; first failure: {first.case_id!r}: {first.message}"
        super().__init__(summary)


@dataclass(frozen=True)
class ConformanceReport:
    """A deterministic record of one profile run against one adapter mode.

    ``results`` preserves the declared profile/case order, so pass/fail output is
    stable across runs.

    ``covers_full_inventory`` records completeness: it is ``True`` only when the run
    executed every planned case (the profile's cases plus any declared-capability
    profile cases), and ``False`` when a ``case_ids`` filter narrowed the run. It is a
    separate axis from :attr:`passed` — a filtered run can pass every case it ran and
    still not be a conformance run — so anything that claims conformance (a CI gate, a
    published report) must require ``report.passed and report.covers_full_inventory``.
    It defaults to ``True`` because every report produced without a filter, including
    every report produced before filtering existed, covered its full inventory.
    """

    profile_id: str
    adapter_name: str
    command_class_name: str
    results: Tuple[CaseResult, ...]
    covers_full_inventory: bool = True

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def failures(self) -> Tuple[CaseResult, ...]:
        return tuple(result for result in self.results if not result.passed)

    @property
    def harness_setup_failed(self) -> bool:
        """``True`` when any case failed inside the harness's own ``create_commands()``.

        One broken harness setup call fails every case that needs a fixture, so a run
        with this set is not a verdict on the adapter: treat the whole run as suspect
        and fix the harness first. Callers should not parse messages to discover this.
        """
        return any(result.harness_setup_failed for result in self.results)

    def raise_for_failures(self) -> None:
        """Raise :class:`ConformanceFailureError` if any case in this run failed."""
        if not self.passed:
            raise ConformanceFailureError(self)
