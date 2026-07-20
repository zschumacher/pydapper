"""Structured results and exceptions for adapter conformance runs.

Every failure is identified by structured attributes (profile id, case id, original
cause, and — for harness validation failures — the missing harness field) so callers
never need to parse exception prose.
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
    """

    profile_id: str
    case_id: str
    passed: bool
    message: str = ""
    cause: Optional[BaseException] = field(default=None, repr=False)
    missing_field: Optional[str] = None
    cleanup_error: Optional[BaseException] = field(default=None, repr=False)


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
        if first is not None:
            summary = f"{summary}; first failure: {first.case_id!r}: {first.message}"
        super().__init__(summary)


@dataclass(frozen=True)
class ConformanceReport:
    """A deterministic record of one profile run against one adapter mode.

    ``results`` preserves the declared profile/case order, so pass/fail output is
    stable across runs.
    """

    profile_id: str
    adapter_name: str
    command_class_name: str
    results: Tuple[CaseResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def failures(self) -> Tuple[CaseResult, ...]:
        return tuple(result for result in self.results if not result.passed)

    def raise_for_failures(self) -> None:
        """Raise :class:`ConformanceFailureError` if any case in this run failed."""
        if not self.passed:
            raise ConformanceFailureError(self)
