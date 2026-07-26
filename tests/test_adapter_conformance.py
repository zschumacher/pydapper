"""Framework self-tests for the reusable adapter conformance suite.

Pytest is allowed here (repository tests), never in the shipped helper. Coverage in
this module is service-free: mock harnesses over a pure-Python fake driver, a real
in-memory SQLite harness, instrumented concrete first-party classes, negative
broken-adapter tests, packaging/drift invariants, and import hygiene.
"""

import dataclasses
import importlib.metadata
import re
import sqlite3
import subprocess
import sys
import tarfile
import textwrap
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

import pytest

import pydapper
from pydapper import _adapter_discovery
from pydapper import main
from pydapper._context import _AwaitableAsyncContextManager as _RealAwaitableAsyncContextManager
from pydapper.bigquery import GoogleBigqueryClientCommands
from pydapper.capabilities import AdapterCapability
from pydapper.command_options import CommandOptions
from pydapper.commands import Commands
from pydapper.exceptions import MoreThanOneResultException
from pydapper.mssql import PymssqlCommands
from pydapper.mysql import MySqlConnectorPythonCommands
from pydapper.oracle import OracledbCommands
from pydapper.postgresql import AiopgCommands
from pydapper.postgresql import Psycopg2Commands
from pydapper.postgresql import Psycopg3Commands
from pydapper.postgresql import Psycopg3CommandsAsync
from pydapper.sqlite import Sqlite3Commands
from pydapper.testing.adapter_conformance import CORE_ASYNC
from pydapper.testing.adapter_conformance import CORE_SYNC
from pydapper.testing.adapter_conformance import AsyncAdapterHarness
from pydapper.testing.adapter_conformance import AsyncCase
from pydapper.testing.adapter_conformance import CaseResult
from pydapper.testing.adapter_conformance import CaseSelectionError
from pydapper.testing.adapter_conformance import ConformanceFailureError
from pydapper.testing.adapter_conformance import ConformanceProfile
from pydapper.testing.adapter_conformance import ConformanceReport
from pydapper.testing.adapter_conformance import HarnessDefinitionError
from pydapper.testing.adapter_conformance import ProfileDefinitionError
from pydapper.testing.adapter_conformance import SyncAdapterHarness
from pydapper.testing.adapter_conformance import SyncCase
from pydapper.testing.adapter_conformance import capability_profiles
from pydapper.testing.adapter_conformance import core_async_profile
from pydapper.testing.adapter_conformance import core_sync_profile
from pydapper.testing.adapter_conformance import run_core_async
from pydapper.testing.adapter_conformance import run_core_sync
from pydapper.testing.adapter_conformance._checks import SyncCaseContext
from pydapper.testing.adapter_conformance._instrumentation import CursorScript
from pydapper.testing.adapter_conformance._instrumentation import RecordingAsyncConnection
from pydapper.testing.adapter_conformance._instrumentation import RecordingConnection
from pydapper.testing.adapter_conformance._instrumentation import SynchronousCursorRecordingAsyncConnection
from pydapper.testing.adapter_conformance._profiles import validate_capability_catalog
from pydapper.testing.adapter_conformance._results import CaseCheckError
from pydapper.testing.adapter_conformance._sqlspec import render_statement
from pydapper.testing.adapter_conformance._sqlspec import statement_ids
from tests.conformance_support import FIRST_PARTY_CONFORMANCE_ENTRIES
from tests.conformance_support import MOCK_ASYNC_ADAPTER_NAME
from tests.conformance_support import MOCK_SYNC_ADAPTER_NAME
from tests.conformance_support import FakeAsyncConnection
from tests.conformance_support import FakeSyncConnection
from tests.conformance_support import MockAsyncConformanceCommands
from tests.conformance_support import MockAsyncConformanceHarness
from tests.conformance_support import MockSyncConformanceCommands
from tests.conformance_support import MockSyncConformanceHarness
from tests.conformance_support import Sqlite3ConformanceHarness
from tests.conformance_support import seed_sqlite_connection
from tests.conformance_support import seeded_mini_db

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parent.parent
GROUP = "pydapper.adapters"

#: The shipped ``transactions`` inventory, in declared order. This is deliberately a literal
#: rather than something derived from ``capability_profiles()``: an expectation computed from
#: the profile can never notice the profile shrinking, and this profile is the third-party
#: contract for "implements transactions correctly".
TRANSACTION_CASE_IDS = (
    "transactions.commit-persists",
    "transactions.rollback-discards",
    "transactions.context-commits-on-exit",
    "transactions.context-rolls-back-on-error",
    "transactions.commit-delegates-once",
    "transactions.rollback-delegates-once",
    "transactions.context-lifecycle-order",
    "transactions.context-error-precedence",
    "transactions.commit-failure-propagates",
    "transactions.context-base-exception-rollback",
    "transactions.context-not-reentrant",
)


def _canonicalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@pytest.fixture
def isolated_registry(monkeypatch):
    """Snapshot-and-restore isolation for the global adapter registry state."""
    registry = main._adapter_registry.copy()
    monkeypatch.setattr(main, "_adapter_registry", registry)
    monkeypatch.setattr(_adapter_discovery, "_catalog", None)
    monkeypatch.setattr(main, "_loaded_provider_registrations", {})
    yield registry


def _register_mock_sync(name=MOCK_SYNC_ADAPTER_NAME, commands=MockSyncConformanceCommands):
    pydapper.register_adapter(
        name,
        commands=commands,
        using_connection_predicate=lambda connection: isinstance(connection, FakeSyncConnection),
    )


def _register_mock_async(name=MOCK_ASYNC_ADAPTER_NAME, async_commands=MockAsyncConformanceCommands):
    pydapper.register_adapter(
        name,
        async_commands=async_commands,
        using_connection_predicate=lambda connection: isinstance(connection, FakeAsyncConnection),
    )


# ------------------------------------------------------------------ import surface


def test_documented_helper_imports():
    import pydapper.testing.adapter_conformance as helper

    for symbol in helper.__all__:
        assert getattr(helper, symbol, None) is not None, symbol
    assert helper.CORE_SYNC == "core-sync"
    assert helper.CORE_ASYNC == "core-async"


def test_no_conformance_symbol_on_package_root():
    for name in (
        "run_core_sync",
        "run_core_async",
        "SyncAdapterHarness",
        "AsyncAdapterHarness",
        "ConformanceReport",
        "ConformanceError",
        "adapter_conformance",
    ):
        assert name not in vars(pydapper), f"package root must not re-export {name}"

    script = textwrap.dedent("""
        import pydapper
        import sys
        assert "pydapper.testing" not in sys.modules, "plain import pydapper must not import pydapper.testing"
        assert not hasattr(pydapper, "run_core_sync")
        print("OK")
        """)
    completed = subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert "OK" in completed.stdout


def test_helper_import_is_dependency_clean():
    """Importing the shipped helper must not load pytest, tests, testcontainers, or drivers."""
    script = textwrap.dedent("""
        import sys

        BANNED = {
            "pytest",
            "_pytest",
            "tests",
            "testcontainers",
            "faker",
            "psycopg2",
            "psycopg",
            "aiopg",
            "mysql",
            "pymssql",
            "oracledb",
            "google",
            "sqlalchemy",
            "typing_extensions",
        }

        class Guard:
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".")[0] in BANNED:
                    raise ImportError(f"forbidden import during conformance-helper import: {fullname}")
                return None

        sys.meta_path.insert(0, Guard())
        import pydapper.testing.adapter_conformance  # noqa: F401

        loaded = sorted(name for name in sys.modules if name.split(".")[0] in BANNED)
        assert not loaded, f"banned modules loaded: {loaded}"
        print("OK")
        """)
    completed = subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    assert "OK" in completed.stdout


# ------------------------------------------------------------------ passing harnesses


def test_mock_sync_harness_passes(isolated_registry):
    _register_mock_sync()
    report = run_core_sync(MockSyncConformanceHarness())
    assert report.passed, [(f.case_id, f.message) for f in report.failures]
    assert report.profile_id == CORE_SYNC
    assert report.adapter_name == MOCK_SYNC_ADAPTER_NAME
    assert len(report.results) == len(core_sync_profile().sync_cases)


@pytest.mark.asyncio
async def test_mock_async_harness_passes(isolated_registry):
    _register_mock_async()
    report = await run_core_async(MockAsyncConformanceHarness())
    assert report.passed, [(f.case_id, f.message) for f in report.failures]
    assert report.profile_id == CORE_ASYNC
    assert len(report.results) == len(core_async_profile().async_cases)


def test_sqlite_in_memory_core_sync_harness_passes(isolated_registry, tmp_path):
    report = run_core_sync(Sqlite3ConformanceHarness(tmp_path))
    assert report.passed, [(f.case_id, f.message) for f in report.failures]
    assert report.adapter_name == "sqlite3"
    assert report.command_class_name.endswith("Sqlite3Commands")
    # Sqlite3Commands declares TRANSACTIONS, so the runner appends the production
    # transactions profile after the core inventory — live supported-adapter coverage.
    # The expectation is the literal inventory, never one derived from the profile itself.
    transaction_results = [result for result in report.results if result.profile_id == "transactions"]
    assert [result.case_id for result in transaction_results] == list(TRANSACTION_CASE_IDS)
    assert all(result.passed for result in transaction_results)


def test_non_declaring_adapter_is_never_run_against_the_transactions_profile(isolated_registry):
    """The unsupported half of the capability contract: an adapter that does not declare
    TRANSACTIONS passes core conformance without the transactions profile ever running."""
    _register_mock_sync()
    report = run_core_sync(MockSyncConformanceHarness())
    assert report.passed, [(f.case_id, f.message) for f in report.failures]
    assert MockSyncConformanceCommands.capabilities == frozenset()
    assert [result for result in report.results if result.profile_id == "transactions"] == []
    assert len(report.results) == len(core_sync_profile().sync_cases)


def test_pass_fail_ordering_is_deterministic(isolated_registry):
    _register_mock_sync()
    first = run_core_sync(MockSyncConformanceHarness())
    second = run_core_sync(MockSyncConformanceHarness())
    declared_order = [case.case_id for case in core_sync_profile().sync_cases]
    assert [result.case_id for result in first.results] == declared_order
    assert [result.case_id for result in second.results] == declared_order


def test_raise_for_failures_raises_structured_error(isolated_registry):
    class _NoFactoryHarness(SyncAdapterHarness):
        adapter_name = MOCK_SYNC_ADAPTER_NAME
        command_class = MockSyncConformanceCommands
        connect_dsn = MockSyncConformanceHarness.connect_dsn

    _register_mock_sync()
    report = run_core_sync(_NoFactoryHarness())
    with pytest.raises(ConformanceFailureError) as exc_info:
        report.raise_for_failures()
    assert exc_info.value.report is report
    assert exc_info.value.failures == report.failures
    assert exc_info.value.failures


# ------------------------------------------------------------------ broken adapters fail named cases


class _BrokenRowMappingCommands(MockSyncConformanceCommands):
    """Deliberately corrupts row mapping while keeping row counts intact."""

    def query(self, sql, *args, **kwargs):
        result = super().query(sql, *args, **kwargs)
        if isinstance(result, list):
            return [{"broken": index} for index, _ in enumerate(result)]
        return result


def test_broken_row_mapper_fails_named_case(isolated_registry):
    name = "conformance-mock-broken-rows"
    _register_mock_sync(name=name, commands=_BrokenRowMappingCommands)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _BrokenRowMappingCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _BrokenRowMappingCommands(FakeSyncConnection(seeded_mini_db()))

    report = run_core_sync(_Harness())
    failed_ids = {failure.case_id for failure in report.failures}
    assert "rows.query-buffered" in failed_ids
    assert not report.passed
    passed_ids = {result.case_id for result in report.results if result.passed}
    assert "execute.rowcount" in passed_ids, "unrelated cases must still pass so failures stay named and narrow"
    named = next(failure for failure in report.failures if failure.case_id == "rows.query-buffered")
    assert named.profile_id == CORE_SYNC
    assert named.message


class _LeakingCursorCommands(MockSyncConformanceCommands):
    """Deliberately leaks every command-owned cursor."""

    @contextmanager
    def _cursor_context_proxy(self):
        cursor = self.cursor()
        enter = getattr(type(cursor), "__enter__", None)
        if callable(enter):
            yield enter(cursor)
        else:
            yield cursor
        # no close, no __exit__: the cursor leaks


def test_leaking_cursor_fails_named_lifecycle_case(isolated_registry):
    name = "conformance-mock-leaky"
    _register_mock_sync(name=name, commands=_LeakingCursorCommands)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _LeakingCursorCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _LeakingCursorCommands(FakeSyncConnection(seeded_mini_db()))

    report = run_core_sync(_Harness())
    named = next(result for result in report.results if result.case_id == "lifecycle.context-cursor-success")
    assert not named.passed
    assert "cleanup" in named.message


class _CleanupMask(Exception):
    pass


class _MaskingCleanupCommands(MockSyncConformanceCommands):
    """Deliberately replaces an active command error with a cleanup failure."""

    @contextmanager
    def _cursor_context_proxy(self):
        with super()._cursor_context_proxy() as cursor:
            try:
                yield cursor
            except Exception:
                raise _CleanupMask("cleanup failure replaced the active error") from None


def test_error_masking_adapter_fails_named_case(isolated_registry):
    name = "conformance-mock-masking"
    _register_mock_sync(name=name, commands=_MaskingCleanupCommands)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _MaskingCleanupCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _MaskingCleanupCommands(FakeSyncConnection(seeded_mini_db()))

    report = run_core_sync(_Harness())
    named = next(result for result in report.results if result.case_id == "lifecycle.active-error-precedence")
    assert not named.passed
    assert isinstance(named.cause, _CleanupMask)


# ---------------------------------------------- hook-ordering mutants fail the named query-path cases
#
# The query-path hook-ordering cases are only worth shipping if they can fail, so each is pinned here by
# a deliberately non-conformant adapter. Every mutant keeps the real command body *and* the real hook
# implementations and rewires only *when* the body's two hook calls reach them, so it differs from a
# conformant adapter in preparation-hook ordering alone -- nothing else can be what fails the case.


@contextmanager
def _swapped_hooks(commands, cursor_hook_name, command_hook_name, awaitable):
    """Defer the prepare-cursor hook until just after the prepare-command hook."""
    real_cursor_hook = getattr(commands, cursor_hook_name)
    real_command_hook = getattr(commands, command_hook_name)
    deferred = []

    def prepare_cursor(cursor, *, options):
        deferred.append((cursor, options))

    def prepare_command(cursor, handler, *, options):
        real_command_hook(cursor, handler, options=options)
        while deferred:
            deferred_cursor, deferred_options = deferred.pop(0)
            real_cursor_hook(deferred_cursor, options=deferred_options)

    async def prepare_cursor_async(cursor, *, options):
        deferred.append((cursor, options))

    async def prepare_command_async(cursor, handler, *, options):
        await real_command_hook(cursor, handler, options=options)
        while deferred:
            deferred_cursor, deferred_options = deferred.pop(0)
            await real_cursor_hook(deferred_cursor, options=deferred_options)

    setattr(commands, cursor_hook_name, prepare_cursor_async if awaitable else prepare_cursor)
    setattr(commands, command_hook_name, prepare_command_async if awaitable else prepare_command)
    try:
        yield
    finally:
        setattr(commands, cursor_hook_name, real_cursor_hook)
        setattr(commands, command_hook_name, real_command_hook)


@contextmanager
def _skipped_hooks(commands, cursor_hook_name, command_hook_name, awaitable):
    """Never let either hook call reach its implementation."""
    real_cursor_hook = getattr(commands, cursor_hook_name)
    real_command_hook = getattr(commands, command_hook_name)

    def prepare_cursor(cursor, *, options):
        return None

    def prepare_command(cursor, handler, *, options):
        return None

    async def prepare_cursor_async(cursor, *, options):
        return None

    async def prepare_command_async(cursor, handler, *, options):
        return None

    setattr(commands, cursor_hook_name, prepare_cursor_async if awaitable else prepare_cursor)
    setattr(commands, command_hook_name, prepare_command_async if awaitable else prepare_command)
    try:
        yield
    finally:
        setattr(commands, cursor_hook_name, real_cursor_hook)
        setattr(commands, command_hook_name, real_command_hook)


@contextmanager
def _prepare_cursor_moved_into_the_query_loop(commands, cursor_hook_name, command_hook_name, awaitable):
    """Drop the once-per-cursor prepare-cursor call and re-run it before every handler instead."""
    real_cursor_hook = getattr(commands, cursor_hook_name)
    real_command_hook = getattr(commands, command_hook_name)

    def prepare_cursor(cursor, *, options):
        return None

    def prepare_command(cursor, handler, *, options):
        real_cursor_hook(cursor, options=options)
        real_command_hook(cursor, handler, options=options)

    async def prepare_cursor_async(cursor, *, options):
        return None

    async def prepare_command_async(cursor, handler, *, options):
        await real_cursor_hook(cursor, options=options)
        await real_command_hook(cursor, handler, options=options)

    setattr(commands, cursor_hook_name, prepare_cursor_async if awaitable else prepare_cursor)
    setattr(commands, command_hook_name, prepare_command_async if awaitable else prepare_command)
    try:
        yield
    finally:
        setattr(commands, cursor_hook_name, real_cursor_hook)
        setattr(commands, command_hook_name, real_command_hook)


class _CursorStandIn:
    """A forwarding stand-in that is *not* the object the command body entered."""

    def __init__(self, cursor):
        self._cursor = cursor

    def __getattr__(self, name):
        return getattr(self._cursor, name)


@contextmanager
def _non_entered_cursor_for_hook(commands, hook_name, awaitable):
    """Hand one hook a stand-in instead of the cursor the command body entered.

    Only one hook is mis-targeted per mutant so each entered-cursor assertion is pinned on
    its own rather than by its sibling.
    """
    real_hook = getattr(commands, hook_name)

    def hook(cursor, *args, **kwargs):
        return real_hook(_CursorStandIn(cursor), *args, **kwargs)

    async def hook_async(cursor, *args, **kwargs):
        await real_hook(_CursorStandIn(cursor), *args, **kwargs)

    setattr(commands, hook_name, hook_async if awaitable else hook)
    try:
        yield
    finally:
        setattr(commands, hook_name, real_hook)


@contextmanager
def _recorded_hook_calls(commands, hook_name):
    """Let one hook through untouched while capturing its arguments for a later replay."""
    real_hook = getattr(commands, hook_name)
    calls = []

    def hook(*args, **kwargs):
        calls.append((args, kwargs))
        return real_hook(*args, **kwargs)

    setattr(commands, hook_name, hook)
    try:
        yield calls
    finally:
        setattr(commands, hook_name, real_hook)


class _OtherHandlerStandIn:
    """A forwarding handler stand-in reporting SQL the driver never executes."""

    def __init__(self, handler):
        self._handler = handler

    def __getattr__(self, name):
        return getattr(self._handler, name)

    @property
    def prepared_sql(self):
        return f"{self._handler.prepared_sql} -- never executed"


@contextmanager
def _other_handler_for_prepare_command(commands, hook_name, awaitable):
    """Show the prepare-command hook a handler other than the one the driver executes.

    Hook call counts, driver event order, options and cursor identity all stay conformant,
    so the prepared-handler pairing assertion is the only thing that can catch this one.
    """
    real_hook = getattr(commands, hook_name)

    def hook(cursor, handler, **kwargs):
        return real_hook(cursor, _OtherHandlerStandIn(handler), **kwargs)

    async def hook_async(cursor, handler, **kwargs):
        await real_hook(cursor, _OtherHandlerStandIn(handler), **kwargs)

    setattr(commands, hook_name, hook_async if awaitable else hook)
    try:
        yield
    finally:
        setattr(commands, hook_name, real_hook)


@contextmanager
def _handlers_prepared_one_query_late(commands, hook_name, awaitable):
    """Prepare handler i+1 immediately before executing handler i.

    Every hook call count, the full driver event order, the options and the entered-cursor
    identity stay exactly conformant: only the pairing between the handler a hook observes
    and the statement the driver runs next is wrong. That is the ``query_multiple``
    mis-pairing a false certificate would otherwise hide, and the pairing assertion is the
    only check in the whole inventory that can see it.
    """
    real_hook = getattr(commands, hook_name)
    real_handler_class = commands.SqlParamHandler
    handlers = []

    def handler_class(*args, **kwargs):
        handler = real_handler_class(*args, **kwargs)
        handlers.append(handler)
        return handler

    def rotated(handler):
        return handlers[(handlers.index(handler) + 1) % len(handlers)]

    def hook(cursor, handler, **kwargs):
        return real_hook(cursor, rotated(handler), **kwargs)

    async def hook_async(cursor, handler, **kwargs):
        await real_hook(cursor, rotated(handler), **kwargs)

    commands.SqlParamHandler = handler_class
    setattr(commands, hook_name, hook_async if awaitable else hook)
    try:
        yield
    finally:
        del commands.SqlParamHandler
        setattr(commands, hook_name, real_hook)


@contextmanager
def _denormalized_options_for_hook(commands, hook_name, awaitable):
    """Hand one hook options the caller never asked for instead of the normalized instance."""
    real_hook = getattr(commands, hook_name)
    substitute = CommandOptions(max_rows=5)

    def hook(cursor, *args, **kwargs):
        kwargs["options"] = substitute
        return real_hook(cursor, *args, **kwargs)

    async def hook_async(cursor, *args, **kwargs):
        kwargs["options"] = substitute
        await real_hook(cursor, *args, **kwargs)

    setattr(commands, hook_name, hook_async if awaitable else hook)
    try:
        yield
    finally:
        setattr(commands, hook_name, real_hook)


@contextmanager
def _statement_executed_twice(commands, hook_name, awaitable):
    """Run the whole prepare-command-then-execute pair twice for every handler.

    Everything else stays conformant: one cursor, one prepare-cursor call, the preparation
    hooks still run in order on the entered cursor before any row is fetched, every execution
    is still immediately preceded by a prepare-command call observing the handler that runs
    next, and the rows are still drained exactly once. Only the statement runs twice, which
    is invisible to a case that pins the preparation *prefix* and leaves the drain unpinned.
    """
    real_hook = getattr(commands, hook_name)

    def hook(cursor, handler, **kwargs):
        real_hook(cursor, handler, **kwargs)
        handler.execute(cursor)
        return real_hook(cursor, handler, **kwargs)

    async def hook_async(cursor, handler, **kwargs):
        await real_hook(cursor, handler, **kwargs)
        await handler.execute_async(cursor)
        await real_hook(cursor, handler, **kwargs)

    setattr(commands, hook_name, hook_async if awaitable else hook)
    try:
        yield
    finally:
        setattr(commands, hook_name, real_hook)


def _sync_mutation(commands, mutation):
    return mutation(commands, "_prepare_cursor", "_prepare_command", False)


def _async_mutation(commands, mutation):
    return mutation(commands, "_prepare_cursor_async", "_prepare_command_async", True)


class _SwappedHooksInBufferedQueryCommands(MockSyncConformanceCommands):
    def _buffered_query(self, *args, **kwargs):
        with _sync_mutation(self, _swapped_hooks):
            return super()._buffered_query(*args, **kwargs)


class _NoHooksInUnbufferedQueryCommands(MockSyncConformanceCommands):
    def _unbuffered_query(self, *args, **kwargs):
        with _sync_mutation(self, _skipped_hooks):
            yield from super()._unbuffered_query(*args, **kwargs)


class _SwappedHooksInUnbufferedQueryCommands(MockSyncConformanceCommands):
    def _unbuffered_query(self, *args, **kwargs):
        with _sync_mutation(self, _swapped_hooks):
            yield from super()._unbuffered_query(*args, **kwargs)


class _DoubleExecuteInUnbufferedQueryCommands(MockSyncConformanceCommands):
    """Prepares and runs the same statement twice before draining the result set once."""

    def _unbuffered_query(self, *args, **kwargs):
        with _statement_executed_twice(self, "_prepare_command", False):
            yield from super()._unbuffered_query(*args, **kwargs)


class _ExtraCursorAfterUnbufferedQueryCommands(MockSyncConformanceCommands):
    """Acquires a second, never-prepared cursor once the streamed result set is exhausted."""

    def _unbuffered_query(self, *args, **kwargs):
        yield from super()._unbuffered_query(*args, **kwargs)
        self.cursor()


class _NonEnteredHooksInUnbufferedQueryCommands(MockSyncConformanceCommands):
    def _unbuffered_query(self, *args, **kwargs):
        with _non_entered_cursor_for_hook(self, "_prepare_cursor", False):
            yield from super()._unbuffered_query(*args, **kwargs)


class _OtherHandlerInUnbufferedQueryCommands(MockSyncConformanceCommands):
    def _unbuffered_query(self, *args, **kwargs):
        with _other_handler_for_prepare_command(self, "_prepare_command", False):
            yield from super()._unbuffered_query(*args, **kwargs)


class _NoHooksInQueryFirstCommands(MockSyncConformanceCommands):
    def query_first(self, *args, **kwargs):
        with _sync_mutation(self, _skipped_hooks):
            return super().query_first(*args, **kwargs)


class _DoubleExecuteInQueryFirstCommands(MockSyncConformanceCommands):
    """Prepares and runs the same statement twice before reading the first row once."""

    def query_first(self, *args, **kwargs):
        with _statement_executed_twice(self, "_prepare_command", False):
            return super().query_first(*args, **kwargs)


class _NoHooksInQuerySingleCommands(MockSyncConformanceCommands):
    def query_single(self, *args, **kwargs):
        with _sync_mutation(self, _skipped_hooks):
            return super().query_single(*args, **kwargs)


class _NoHooksInExecuteScalarCommands(MockSyncConformanceCommands):
    def execute_scalar(self, *args, **kwargs):
        with _sync_mutation(self, _skipped_hooks):
            return super().execute_scalar(*args, **kwargs)


class _PerQueryPrepareCursorCommands(MockSyncConformanceCommands):
    def query_multiple(self, *args, **kwargs):
        with _sync_mutation(self, _prepare_cursor_moved_into_the_query_loop):
            return super().query_multiple(*args, **kwargs)


class _SwappedHooksInQueryMultipleCommands(MockSyncConformanceCommands):
    def query_multiple(self, *args, **kwargs):
        with _sync_mutation(self, _swapped_hooks):
            return super().query_multiple(*args, **kwargs)


class _NonEnteredHooksInQueryMultipleCommands(MockSyncConformanceCommands):
    def query_multiple(self, *args, **kwargs):
        with _non_entered_cursor_for_hook(self, "_prepare_cursor", False):
            return super().query_multiple(*args, **kwargs)


class _MispairedHandlersInQueryMultipleCommands(MockSyncConformanceCommands):
    def query_multiple(self, *args, **kwargs):
        with _handlers_prepared_one_query_late(self, "_prepare_command", False):
            return super().query_multiple(*args, **kwargs)


class _TruncatedQueryMultipleResultsCommands(MockSyncConformanceCommands):
    """Runs every query but drops all but the first result set from the return value."""

    def query_multiple(self, *args, **kwargs):
        return super().query_multiple(*args, **kwargs)[:1]


class _NonEnteredPrepareCursorCommands(MockSyncConformanceCommands):
    def _buffered_query(self, *args, **kwargs):
        with _non_entered_cursor_for_hook(self, "_prepare_cursor", False):
            return super()._buffered_query(*args, **kwargs)


class _NonEnteredPrepareCommandCommands(MockSyncConformanceCommands):
    def _buffered_query(self, *args, **kwargs):
        with _non_entered_cursor_for_hook(self, "_prepare_command", False):
            return super()._buffered_query(*args, **kwargs)


class _DenormalizedOptionsForPrepareCursorCommands(MockSyncConformanceCommands):
    def _buffered_query(self, *args, **kwargs):
        with _denormalized_options_for_hook(self, "_prepare_cursor", False):
            return super()._buffered_query(*args, **kwargs)


class _DenormalizedOptionsForPrepareCommandCommands(MockSyncConformanceCommands):
    def _buffered_query(self, *args, **kwargs):
        with _denormalized_options_for_hook(self, "_prepare_command", False):
            return super()._buffered_query(*args, **kwargs)


class _OtherHandlerInBufferedQueryCommands(MockSyncConformanceCommands):
    def _buffered_query(self, *args, **kwargs):
        with _other_handler_for_prepare_command(self, "_prepare_command", False):
            return super()._buffered_query(*args, **kwargs)


class _SwappedHooksInQueryFirstCommands(MockSyncConformanceCommands):
    def query_first(self, *args, **kwargs):
        with _sync_mutation(self, _swapped_hooks):
            return super().query_first(*args, **kwargs)


class _LatePrepareCursorInQueryFirstCommands(MockSyncConformanceCommands):
    """Repeats the prepare-cursor hook once the cursor block has already closed."""

    def query_first(self, *args, **kwargs):
        with _recorded_hook_calls(self, "_prepare_cursor") as calls:
            result = super().query_first(*args, **kwargs)
        for call_args, call_kwargs in calls:
            self._prepare_cursor(*call_args, **call_kwargs)
        return result


class _LatePrepareCommandInQueryFirstCommands(MockSyncConformanceCommands):
    """Repeats the prepare-command hook for a handler that is never executed again."""

    def query_first(self, *args, **kwargs):
        with _recorded_hook_calls(self, "_prepare_command") as calls:
            result = super().query_first(*args, **kwargs)
        for call_args, call_kwargs in calls:
            self._prepare_command(*call_args, **call_kwargs)
        return result


class _SwappedHooksInAsyncBufferedQueryCommands(MockAsyncConformanceCommands):
    async def _buffered_query(self, *args, **kwargs):
        with _async_mutation(self, _swapped_hooks):
            return await super()._buffered_query(*args, **kwargs)


class _NoHooksInAsyncUnbufferedQueryCommands(MockAsyncConformanceCommands):
    async def _unbuffered_query(self, *args, **kwargs):
        # the inner generator is aclosed explicitly so wrapping it stays invisible to the
        # unbuffered cleanup cases; only the hook calls differ from a conformant adapter
        inner = super()._unbuffered_query(*args, **kwargs)
        try:
            with _async_mutation(self, _skipped_hooks):
                async for row in inner:
                    yield row
        finally:
            await inner.aclose()


class _SwappedHooksInAsyncUnbufferedQueryCommands(MockAsyncConformanceCommands):
    async def _unbuffered_query(self, *args, **kwargs):
        inner = super()._unbuffered_query(*args, **kwargs)
        try:
            with _async_mutation(self, _swapped_hooks):
                async for row in inner:
                    yield row
        finally:
            await inner.aclose()


class _DoubleExecuteInAsyncUnbufferedQueryCommands(MockAsyncConformanceCommands):
    """Prepares and runs the same statement twice before draining the result set once."""

    async def _unbuffered_query(self, *args, **kwargs):
        inner = super()._unbuffered_query(*args, **kwargs)
        try:
            with _statement_executed_twice(self, "_prepare_command_async", True):
                async for row in inner:
                    yield row
        finally:
            await inner.aclose()


class _ExtraCursorAfterAsyncUnbufferedQueryCommands(MockAsyncConformanceCommands):
    """Acquires a second, never-prepared cursor once the streamed result set is exhausted."""

    async def _unbuffered_query(self, *args, **kwargs):
        inner = super()._unbuffered_query(*args, **kwargs)
        try:
            async for row in inner:
                yield row
        finally:
            await inner.aclose()
        await self.cursor()


class _NonEnteredHooksInAsyncUnbufferedQueryCommands(MockAsyncConformanceCommands):
    async def _unbuffered_query(self, *args, **kwargs):
        inner = super()._unbuffered_query(*args, **kwargs)
        try:
            with _non_entered_cursor_for_hook(self, "_prepare_cursor_async", True):
                async for row in inner:
                    yield row
        finally:
            await inner.aclose()


class _OtherHandlerInAsyncUnbufferedQueryCommands(MockAsyncConformanceCommands):
    async def _unbuffered_query(self, *args, **kwargs):
        inner = super()._unbuffered_query(*args, **kwargs)
        try:
            with _other_handler_for_prepare_command(self, "_prepare_command_async", True):
                async for row in inner:
                    yield row
        finally:
            await inner.aclose()


class _NoHooksInAsyncQueryFirstCommands(MockAsyncConformanceCommands):
    async def query_first_async(self, *args, **kwargs):
        with _async_mutation(self, _skipped_hooks):
            return await super().query_first_async(*args, **kwargs)


class _DoubleExecuteInAsyncQueryFirstCommands(MockAsyncConformanceCommands):
    """Prepares and runs the same statement twice before reading the first row once."""

    async def query_first_async(self, *args, **kwargs):
        with _statement_executed_twice(self, "_prepare_command_async", True):
            return await super().query_first_async(*args, **kwargs)


class _NoHooksInAsyncQuerySingleCommands(MockAsyncConformanceCommands):
    async def query_single_async(self, *args, **kwargs):
        with _async_mutation(self, _skipped_hooks):
            return await super().query_single_async(*args, **kwargs)


class _NoHooksInAsyncExecuteScalarCommands(MockAsyncConformanceCommands):
    async def execute_scalar_async(self, *args, **kwargs):
        with _async_mutation(self, _skipped_hooks):
            return await super().execute_scalar_async(*args, **kwargs)


class _PerQueryPrepareCursorAsyncCommands(MockAsyncConformanceCommands):
    async def query_multiple_async(self, *args, **kwargs):
        with _async_mutation(self, _prepare_cursor_moved_into_the_query_loop):
            return await super().query_multiple_async(*args, **kwargs)


class _SwappedHooksInAsyncQueryMultipleCommands(MockAsyncConformanceCommands):
    async def query_multiple_async(self, *args, **kwargs):
        with _async_mutation(self, _swapped_hooks):
            return await super().query_multiple_async(*args, **kwargs)


class _NonEnteredHooksInAsyncQueryMultipleCommands(MockAsyncConformanceCommands):
    async def query_multiple_async(self, *args, **kwargs):
        with _non_entered_cursor_for_hook(self, "_prepare_cursor_async", True):
            return await super().query_multiple_async(*args, **kwargs)


class _MispairedHandlersInAsyncQueryMultipleCommands(MockAsyncConformanceCommands):
    async def query_multiple_async(self, *args, **kwargs):
        with _handlers_prepared_one_query_late(self, "_prepare_command_async", True):
            return await super().query_multiple_async(*args, **kwargs)


class _TruncatedAsyncQueryMultipleResultsCommands(MockAsyncConformanceCommands):
    """Runs every query but drops all but the first result set from the return value."""

    async def query_multiple_async(self, *args, **kwargs):
        return (await super().query_multiple_async(*args, **kwargs))[:1]


class _NonEnteredPrepareCursorAsyncCommands(MockAsyncConformanceCommands):
    async def _buffered_query(self, *args, **kwargs):
        with _non_entered_cursor_for_hook(self, "_prepare_cursor_async", True):
            return await super()._buffered_query(*args, **kwargs)


class _NonEnteredPrepareCommandAsyncCommands(MockAsyncConformanceCommands):
    async def _buffered_query(self, *args, **kwargs):
        with _non_entered_cursor_for_hook(self, "_prepare_command_async", True):
            return await super()._buffered_query(*args, **kwargs)


class _DenormalizedOptionsForPrepareCursorAsyncCommands(MockAsyncConformanceCommands):
    async def _buffered_query(self, *args, **kwargs):
        with _denormalized_options_for_hook(self, "_prepare_cursor_async", True):
            return await super()._buffered_query(*args, **kwargs)


class _DenormalizedOptionsForPrepareCommandAsyncCommands(MockAsyncConformanceCommands):
    async def _buffered_query(self, *args, **kwargs):
        with _denormalized_options_for_hook(self, "_prepare_command_async", True):
            return await super()._buffered_query(*args, **kwargs)


class _OtherHandlerInAsyncBufferedQueryCommands(MockAsyncConformanceCommands):
    async def _buffered_query(self, *args, **kwargs):
        with _other_handler_for_prepare_command(self, "_prepare_command_async", True):
            return await super()._buffered_query(*args, **kwargs)


class _SwappedHooksInAsyncQueryFirstCommands(MockAsyncConformanceCommands):
    async def query_first_async(self, *args, **kwargs):
        with _async_mutation(self, _swapped_hooks):
            return await super().query_first_async(*args, **kwargs)


class _LatePrepareCursorInAsyncQueryFirstCommands(MockAsyncConformanceCommands):
    async def query_first_async(self, *args, **kwargs):
        with _recorded_hook_calls(self, "_prepare_cursor_async") as calls:
            result = await super().query_first_async(*args, **kwargs)
        for call_args, call_kwargs in calls:
            await self._prepare_cursor_async(*call_args, **call_kwargs)
        return result


class _LatePrepareCommandInAsyncQueryFirstCommands(MockAsyncConformanceCommands):
    async def query_first_async(self, *args, **kwargs):
        with _recorded_hook_calls(self, "_prepare_command_async") as calls:
            result = await super().query_first_async(*args, **kwargs)
        for call_args, call_kwargs in calls:
            await self._prepare_command_async(*call_args, **call_kwargs)
        return result


class _Assertion(NamedTuple):
    """One assertion the new cases make, plus the text that identifies it in a failure message.

    ``fragment`` is what turns the ``assertion`` column of the table below from a comment into
    a checked claim: the negative tests require it to appear in the failure the mutant
    produces, so a row naming the wrong assertion fails instead of quietly drifting.
    """

    label: str
    fragment: str


_EVENT_ORDER = _Assertion("full driver event order", "expected driver interaction order")
_PREPARATION_PREFIX = _Assertion(
    "preparation prefix",
    "must acquire and enter a cursor, run the preparation hooks in order",
)
_ONE_COMMAND_CURSOR = _Assertion("one command-owned cursor", "must acquire exactly one command-owned cursor")
_PREPARE_CURSOR_ONCE = _Assertion(
    "once-per-cursor prepare-cursor count",
    "must run the prepare-cursor hook exactly once per cursor",
)
_PREPARE_COMMAND_ONCE = _Assertion(
    "once-per-handler prepare-command count",
    "must run the prepare-command hook exactly once per executed handler",
)
_STATEMENT_EXECUTED_ONCE = _Assertion(
    "exactly-one-execution count",
    "must execute its statement exactly once",
)
_PREPARE_CURSOR_ENTERED_CURSOR = _Assertion(
    "prepare-cursor entered-cursor identity",
    "prepare-cursor hook must receive the entered cursor object",
)
_PREPARE_COMMAND_ENTERED_CURSOR = _Assertion(
    "prepare-command entered-cursor identity",
    "prepare-command hook must receive the entered cursor object",
)
_PREPARE_CURSOR_NORMALIZED_OPTIONS = _Assertion(
    "prepare-cursor normalized options",
    "prepare-cursor hook must receive normalized default CommandOptions",
)
_PREPARE_COMMAND_NORMALIZED_OPTIONS = _Assertion(
    "prepare-command normalized options",
    "prepare-command hook must receive normalized default CommandOptions",
)
_PREPARED_HANDLER_PAIRING = _Assertion(
    "prepared-handler pairing",
    "must observe the handler whose prepared SQL is executed next",
)
_ONE_RESULT_SET_PER_QUERY = _Assertion(
    "one result set per query",
    "must return one result set per query",
)


class _HookOrderMutant(NamedTuple):
    """One non-conformant adapter, the case it must fail, and the assertion that must fail it."""

    slug: str
    case_id: str
    assertion: _Assertion
    sync_commands: type
    async_commands: type
    #: command path whose name must also appear in the failure message, which is what pins the
    #: individual legs of the single-row case; empty for the framework's own event-order
    #: assertion, whose message names no path
    path: str = ""


#: Every row is one deliberately non-conformant adapter. The negative tests require it to fail
#: exactly one case, on exactly the assertion named here (checked against the failure message),
#: while every other case in the profile still passes.
#:
#: Between them these rows pin every assertion-helper invocation the four new cases add and every
#: check inside those helpers: delete any one of them from ``_cases_sync.py``/``_cases_async.py``
#: and at least one row below stops failing. The remaining checks in the four cases are
#: defence-in-depth and are deliberately *not* pinned here, because a violation that reaches them
#: is already rejected by a case that predates this change:
#:
#: * the unconsumed-unbuffered ``kinds() == ()`` check -- both hooks run inside the cursor block,
#:   so running them before consumption means acquiring a cursor before consumption, which
#:   ``lifecycle.unbuffered-exhaustion-cleanup`` already rejects (an adapter that violates it
#:   therefore fails two cases, which is why no row here can pin it narrowly);
#: * the projection checks in the buffered and unbuffered cases -- ``rows.query-buffered`` and
#:   ``rows.query-unbuffered`` own row mapping, so the same is true of them.
_HOOK_ORDER_MUTANTS = (
    _HookOrderMutant(
        slug="swapped-hooks-buffered",
        case_id="lifecycle.hook-order-buffered-query",
        assertion=_EVENT_ORDER,
        sync_commands=_SwappedHooksInBufferedQueryCommands,
        async_commands=_SwappedHooksInAsyncBufferedQueryCommands,
    ),
    _HookOrderMutant(
        slug="non-entered-prepare-cursor",
        case_id="lifecycle.hook-order-buffered-query",
        assertion=_PREPARE_CURSOR_ENTERED_CURSOR,
        sync_commands=_NonEnteredPrepareCursorCommands,
        async_commands=_NonEnteredPrepareCursorAsyncCommands,
        path="buffered query",
    ),
    _HookOrderMutant(
        slug="non-entered-prepare-command",
        case_id="lifecycle.hook-order-buffered-query",
        assertion=_PREPARE_COMMAND_ENTERED_CURSOR,
        sync_commands=_NonEnteredPrepareCommandCommands,
        async_commands=_NonEnteredPrepareCommandAsyncCommands,
        path="buffered query",
    ),
    _HookOrderMutant(
        slug="denormalized-options-prepare-cursor",
        case_id="lifecycle.hook-order-buffered-query",
        assertion=_PREPARE_CURSOR_NORMALIZED_OPTIONS,
        sync_commands=_DenormalizedOptionsForPrepareCursorCommands,
        async_commands=_DenormalizedOptionsForPrepareCursorAsyncCommands,
        path="buffered query",
    ),
    _HookOrderMutant(
        slug="denormalized-options-prepare-command",
        case_id="lifecycle.hook-order-buffered-query",
        assertion=_PREPARE_COMMAND_NORMALIZED_OPTIONS,
        sync_commands=_DenormalizedOptionsForPrepareCommandCommands,
        async_commands=_DenormalizedOptionsForPrepareCommandAsyncCommands,
        path="buffered query",
    ),
    _HookOrderMutant(
        slug="other-handler-buffered",
        case_id="lifecycle.hook-order-buffered-query",
        assertion=_PREPARED_HANDLER_PAIRING,
        sync_commands=_OtherHandlerInBufferedQueryCommands,
        async_commands=_OtherHandlerInAsyncBufferedQueryCommands,
        path="buffered query",
    ),
    _HookOrderMutant(
        slug="no-hooks-unbuffered",
        case_id="lifecycle.hook-order-unbuffered-query",
        assertion=_PREPARATION_PREFIX,
        sync_commands=_NoHooksInUnbufferedQueryCommands,
        async_commands=_NoHooksInAsyncUnbufferedQueryCommands,
        path="unbuffered query",
    ),
    _HookOrderMutant(
        slug="swapped-hooks-unbuffered",
        case_id="lifecycle.hook-order-unbuffered-query",
        assertion=_PREPARATION_PREFIX,
        sync_commands=_SwappedHooksInUnbufferedQueryCommands,
        async_commands=_SwappedHooksInAsyncUnbufferedQueryCommands,
        path="unbuffered query",
    ),
    _HookOrderMutant(
        slug="double-execute-unbuffered",
        case_id="lifecycle.hook-order-unbuffered-query",
        assertion=_STATEMENT_EXECUTED_ONCE,
        sync_commands=_DoubleExecuteInUnbufferedQueryCommands,
        async_commands=_DoubleExecuteInAsyncUnbufferedQueryCommands,
        path="unbuffered query",
    ),
    _HookOrderMutant(
        slug="extra-cursor-unbuffered",
        case_id="lifecycle.hook-order-unbuffered-query",
        assertion=_ONE_COMMAND_CURSOR,
        sync_commands=_ExtraCursorAfterUnbufferedQueryCommands,
        async_commands=_ExtraCursorAfterAsyncUnbufferedQueryCommands,
        path="unbuffered query",
    ),
    _HookOrderMutant(
        slug="non-entered-hooks-unbuffered",
        case_id="lifecycle.hook-order-unbuffered-query",
        assertion=_PREPARE_CURSOR_ENTERED_CURSOR,
        sync_commands=_NonEnteredHooksInUnbufferedQueryCommands,
        async_commands=_NonEnteredHooksInAsyncUnbufferedQueryCommands,
        path="unbuffered query",
    ),
    _HookOrderMutant(
        slug="other-handler-unbuffered",
        case_id="lifecycle.hook-order-unbuffered-query",
        assertion=_PREPARED_HANDLER_PAIRING,
        sync_commands=_OtherHandlerInUnbufferedQueryCommands,
        async_commands=_OtherHandlerInAsyncUnbufferedQueryCommands,
        path="unbuffered query",
    ),
    _HookOrderMutant(
        slug="no-hooks-query-first",
        case_id="lifecycle.hook-order-single-row-commands",
        assertion=_PREPARATION_PREFIX,
        sync_commands=_NoHooksInQueryFirstCommands,
        async_commands=_NoHooksInAsyncQueryFirstCommands,
        path="query_first",
    ),
    _HookOrderMutant(
        slug="swapped-hooks-query-first",
        case_id="lifecycle.hook-order-single-row-commands",
        assertion=_PREPARATION_PREFIX,
        sync_commands=_SwappedHooksInQueryFirstCommands,
        async_commands=_SwappedHooksInAsyncQueryFirstCommands,
        path="query_first",
    ),
    _HookOrderMutant(
        slug="double-execute-query-first",
        case_id="lifecycle.hook-order-single-row-commands",
        assertion=_STATEMENT_EXECUTED_ONCE,
        sync_commands=_DoubleExecuteInQueryFirstCommands,
        async_commands=_DoubleExecuteInAsyncQueryFirstCommands,
        path="query_first",
    ),
    _HookOrderMutant(
        slug="late-prepare-cursor-query-first",
        case_id="lifecycle.hook-order-single-row-commands",
        assertion=_PREPARE_CURSOR_ONCE,
        sync_commands=_LatePrepareCursorInQueryFirstCommands,
        async_commands=_LatePrepareCursorInAsyncQueryFirstCommands,
        path="query_first",
    ),
    _HookOrderMutant(
        slug="late-prepare-command-query-first",
        case_id="lifecycle.hook-order-single-row-commands",
        assertion=_PREPARE_COMMAND_ONCE,
        sync_commands=_LatePrepareCommandInQueryFirstCommands,
        async_commands=_LatePrepareCommandInAsyncQueryFirstCommands,
        path="query_first",
    ),
    _HookOrderMutant(
        slug="no-hooks-query-single",
        case_id="lifecycle.hook-order-single-row-commands",
        assertion=_PREPARATION_PREFIX,
        sync_commands=_NoHooksInQuerySingleCommands,
        async_commands=_NoHooksInAsyncQuerySingleCommands,
        path="query_single",
    ),
    _HookOrderMutant(
        slug="no-hooks-execute-scalar",
        case_id="lifecycle.hook-order-single-row-commands",
        assertion=_PREPARATION_PREFIX,
        sync_commands=_NoHooksInExecuteScalarCommands,
        async_commands=_NoHooksInAsyncExecuteScalarCommands,
        path="execute_scalar",
    ),
    _HookOrderMutant(
        slug="per-query-prepare-cursor",
        case_id="lifecycle.hook-order-query-multiple",
        assertion=_EVENT_ORDER,
        sync_commands=_PerQueryPrepareCursorCommands,
        async_commands=_PerQueryPrepareCursorAsyncCommands,
    ),
    _HookOrderMutant(
        slug="swapped-hooks-query-multiple",
        case_id="lifecycle.hook-order-query-multiple",
        assertion=_EVENT_ORDER,
        sync_commands=_SwappedHooksInQueryMultipleCommands,
        async_commands=_SwappedHooksInAsyncQueryMultipleCommands,
    ),
    _HookOrderMutant(
        slug="non-entered-hooks-query-multiple",
        case_id="lifecycle.hook-order-query-multiple",
        assertion=_PREPARE_CURSOR_ENTERED_CURSOR,
        sync_commands=_NonEnteredHooksInQueryMultipleCommands,
        async_commands=_NonEnteredHooksInAsyncQueryMultipleCommands,
        path="query_multiple",
    ),
    _HookOrderMutant(
        slug="mispaired-handlers-query-multiple",
        case_id="lifecycle.hook-order-query-multiple",
        assertion=_PREPARED_HANDLER_PAIRING,
        sync_commands=_MispairedHandlersInQueryMultipleCommands,
        async_commands=_MispairedHandlersInAsyncQueryMultipleCommands,
        path="query_multiple",
    ),
    _HookOrderMutant(
        slug="truncated-query-multiple-results",
        case_id="lifecycle.hook-order-query-multiple",
        assertion=_ONE_RESULT_SET_PER_QUERY,
        sync_commands=_TruncatedQueryMultipleResultsCommands,
        async_commands=_TruncatedAsyncQueryMultipleResultsCommands,
        path="query_multiple",
    ),
)


_HOOK_ORDER_MUTANT_IDS = [mutant.slug for mutant in _HOOK_ORDER_MUTANTS]


def _expected_message_fragments(mutant):
    if mutant.path:
        return (mutant.assertion.fragment, mutant.path)
    return (mutant.assertion.fragment,)


def _assert_only_the_named_hook_case_failed(report, mutant):
    failed_ids = {failure.case_id for failure in report.failures}
    assert failed_ids == {mutant.case_id}, "the mutant must be caught, and caught narrowly, by its own case"
    passed_ids = {result.case_id for result in report.results if result.passed}
    assert "lifecycle.hook-order" in passed_ids, "the pre-existing execute-path case cannot see query-path hooks"
    named = next(failure for failure in report.failures if failure.case_id == mutant.case_id)
    for fragment in _expected_message_fragments(mutant):
        # failing the right case on the *wrong* assertion proves nothing about the assertion the
        # table says this row pins, so the failure message has to match it too
        assert fragment in named.message, (
            f"{mutant.slug} must fail {mutant.case_id} on the {mutant.assertion.label} assertion "
            f"the table names for it: expected {fragment!r} in {named.message!r}"
        )


@pytest.mark.parametrize("mutant", _HOOK_ORDER_MUTANTS, ids=_HOOK_ORDER_MUTANT_IDS)
def test_query_path_hook_ordering_mutant_fails_its_named_case(isolated_registry, mutant):
    name = f"conformance-mock-{mutant.slug}"
    commands_class = mutant.sync_commands
    _register_mock_sync(name=name, commands=commands_class)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = commands_class
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return commands_class(FakeSyncConnection(seeded_mini_db()))

    _assert_only_the_named_hook_case_failed(run_core_sync(_Harness()), mutant)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutant", _HOOK_ORDER_MUTANTS, ids=_HOOK_ORDER_MUTANT_IDS)
async def test_async_query_path_hook_ordering_mutant_fails_its_named_case(isolated_registry, mutant):
    name = f"conformance-mock-{mutant.slug}-async"
    commands_class = mutant.async_commands
    _register_mock_async(name=name, async_commands=commands_class)

    class _Harness(MockAsyncConformanceHarness):
        adapter_name = name
        command_class = commands_class
        connect_dsn = f"sqlite+{name}://mock"

        async def create_commands(self):
            return commands_class(FakeAsyncConnection(seeded_mini_db()))

    _assert_only_the_named_hook_case_failed(await run_core_async(_Harness()), mutant)


# ------------------------------------------------------------------ transactions profile mutants
#
# The `transactions` profile is the shipped, third-party-facing definition of "implements
# transactions correctly". Everything below exists so that definition cannot be weakened
# silently: every assertion the profile makes is pinned by a deliberately non-conformant
# adapter that must fail one named case on one named assertion.


class _ProxyMutantCommands(Sqlite3Commands):
    """Base for mutants that replace the ``transaction()`` block body itself.

    It reimplements the real proxy — nesting guard, rollback-on-error, commit-on-clean-exit,
    discarded rollback failure — behind three seams, so each subclass changes exactly one thing
    and nothing incidental can be what fails a case. The base is itself run against the whole
    profile below, which is what makes that claim checkable.
    """

    #: cleared to leave the nesting guard out entirely
    _guards_nesting = True
    #: cleared to leak the guard past the end of the block
    _clears_guard = True

    def _on_entry(self) -> None:
        """Runs when the block is entered. The contract is: emit no SQL."""

    def _on_error(self, error: BaseException) -> None:
        """Runs while the block's error is being handled; the error is re-raised after."""
        try:
            self.rollback()
        except Exception:
            pass

    def _on_clean_exit(self) -> None:
        self.commit()

    @contextmanager
    def _transaction_proxy(self):
        if self._guards_nesting and self._in_transaction:
            raise RuntimeError("transaction() blocks cannot be nested")
        self._in_transaction = True
        try:
            self._on_entry()
            try:
                yield
            except BaseException as error:
                self._on_error(error)
                raise
            else:
                self._on_clean_exit()
        finally:
            if self._clears_guard:
                self._in_transaction = False


class _NoOpCommitCommands(Sqlite3Commands):
    """commit() never reaches the connection."""

    def commit(self) -> None:
        pass


class _NoOpRollbackCommands(Sqlite3Commands):
    """rollback() never reaches the connection."""

    def rollback(self) -> None:
        pass


class _CommitReturnsValueCommands(Sqlite3Commands):
    """commit() delegates correctly but returns a value the contract pins to None."""

    def commit(self):
        super().commit()
        return True


class _RollbackReturnsValueCommands(Sqlite3Commands):
    """rollback() delegates correctly but returns a value the contract pins to None."""

    def rollback(self):
        super().rollback()
        return True


class _CommitAlsoRollsBackCommands(Sqlite3Commands):
    """commit() rolls back first, discarding work the caller asked to keep."""

    def commit(self) -> None:
        self.connection.rollback()
        super().commit()


class _RollbackAlsoCommitsCommands(Sqlite3Commands):
    """rollback() commits first, making work durable the caller asked to discard."""

    def rollback(self) -> None:
        self.connection.commit()
        super().rollback()


class _CommitAcquiresCursorCommands(Sqlite3Commands):
    """commit() takes a cursor it does not need."""

    def commit(self) -> None:
        self.connection.cursor()
        super().commit()


class _RollbackAcquiresCursorCommands(Sqlite3Commands):
    """rollback() takes a cursor it does not need."""

    def rollback(self) -> None:
        self.connection.cursor()
        super().rollback()


class _CommitTranslatesFailureCommands(Sqlite3Commands):
    """A driver commit failure is re-raised as an equal-but-different exception object."""

    def commit(self) -> None:
        try:
            super().commit()
        except Exception as error:
            raise type(error)(*error.args) from None


class _RollbackTranslatesFailureCommands(Sqlite3Commands):
    """A driver rollback failure is re-raised as an equal-but-different exception object."""

    def rollback(self) -> None:
        try:
            super().rollback()
        except Exception as error:
            raise type(error)(*error.args) from None


class _CommitRetriesOnFailureCommands(Sqlite3Commands):
    """A failed commit is retried against a connection in a driver-defined state."""

    def commit(self) -> None:
        try:
            super().commit()
        except Exception:
            super().commit()


class _RollbackRetriesOnFailureCommands(Sqlite3Commands):
    """A failed rollback is retried against a connection in a driver-defined state."""

    def rollback(self) -> None:
        try:
            super().rollback()
        except Exception:
            super().rollback()


class _CommitRollsBackOnFailureCommands(Sqlite3Commands):
    """A failed commit triggers a rollback the contract forbids."""

    def commit(self) -> None:
        try:
            super().commit()
        except Exception:
            self.connection.rollback()
            raise


class _RollbackCommitsOnFailureCommands(Sqlite3Commands):
    """A failed rollback falls back to a commit — the worst possible recovery."""

    def rollback(self) -> None:
        try:
            super().rollback()
        except Exception:
            self.connection.commit()
            raise


class _RollbackDiscardsCommittedRowsCommands(Sqlite3Commands):
    """rollback() discards the uncommitted work *and* the durable baseline."""

    def rollback(self) -> None:
        super().rollback()
        execute = getattr(self.connection, "execute", None)
        if execute is not None:  # a live DBAPI connection; the recording connection has none
            execute("DELETE FROM pydapper_conformance")
            super().commit()


class _NoCommitOnExitCommands(_ProxyMutantCommands):
    """A block that forgets to commit on clean exit."""

    def _on_clean_exit(self) -> None:
        pass


class _CommitsTwiceOnExitCommands(_ProxyMutantCommands):
    """A block that commits twice on clean exit."""

    def _on_clean_exit(self) -> None:
        self.commit()
        self.commit()


class _RollsBackAfterCommitCommands(_ProxyMutantCommands):
    """A block that rolls back after committing on clean exit."""

    def _on_clean_exit(self) -> None:
        self.commit()
        self.rollback()


class _EmitsBeginOnEntryCommands(_ProxyMutantCommands):
    """A block that emits explicit BEGIN SQL on entry instead of relying on the DBAPI."""

    def _on_entry(self) -> None:
        self.execute("BEGIN")


class _ReRaisesACopyCommands(_ProxyMutantCommands):
    """A block that rolls back correctly but re-raises a copy of the caller's exception."""

    def _on_error(self, error: BaseException) -> None:
        super()._on_error(error)
        raise type(error)(*error.args)


class _NeverRollsBackCommands(_ProxyMutantCommands):
    """A block that re-raises without rolling anything back."""

    def _on_error(self, error: BaseException) -> None:
        pass


class _CommitsAfterRollbackOnErrorCommands(_ProxyMutantCommands):
    """A block that rolls back and then commits anyway when its body raised."""

    def _on_error(self, error: BaseException) -> None:
        super()._on_error(error)
        self.commit()


class _TranslatesRollbackFailureCommands(_ProxyMutantCommands):
    """A rollback failure replaces the block's error with a copy of it."""

    def _on_error(self, error: BaseException) -> None:
        try:
            self.rollback()
        except Exception:
            raise type(error)(*error.args) from None


class _RetriesRollbackOnFailureCommands(_ProxyMutantCommands):
    """A failed rollback inside the block is retried."""

    def _on_error(self, error: BaseException) -> None:
        try:
            self.rollback()
        except Exception:
            try:
                self.rollback()
            except Exception:
                pass


class _TranslatesExitCommitFailureCommands(_ProxyMutantCommands):
    """A failed exit commit is re-raised as an equal-but-different exception object."""

    def _on_clean_exit(self) -> None:
        try:
            self.commit()
        except Exception as error:
            raise type(error)(*error.args) from None


class _RetriesExitCommitCommands(_ProxyMutantCommands):
    """A failed exit commit is retried."""

    def _on_clean_exit(self) -> None:
        try:
            self.commit()
        except Exception:
            self.commit()


class _RollsBackAfterFailedExitCommitCommands(_ProxyMutantCommands):
    """A failed exit commit triggers a rollback against a driver-defined connection state."""

    def _on_clean_exit(self) -> None:
        try:
            self.commit()
        except Exception:
            self.rollback()
            raise


class _RollsBackOnlyOrdinaryErrorsCommands(_ProxyMutantCommands):
    """The #572 defect class: a BaseException that is not an Exception skips the rollback."""

    def _on_error(self, error: BaseException) -> None:
        if isinstance(error, Exception):
            super()._on_error(error)


class _TranslatesInterruptedRollbackCommands(_ProxyMutantCommands):
    """An interrupt raised by rollback propagates as a copy, losing the original object."""

    def _on_error(self, error: BaseException) -> None:
        try:
            self.rollback()
        except Exception:
            pass
        except BaseException as interrupt:
            raise type(interrupt)(*interrupt.args)


class _CommitsAfterInterruptedRollbackCommands(_ProxyMutantCommands):
    """An interrupt raised by rollback is answered with a commit before it propagates."""

    def _on_error(self, error: BaseException) -> None:
        try:
            self.rollback()
        except Exception:
            pass
        except BaseException:
            self.commit()
            raise


class _CommitSwallowsFailureCommands(Sqlite3Commands):
    """commit() reports success after the driver refused to commit."""

    def commit(self) -> None:
        try:
            super().commit()
        except Exception:
            pass


class _RollbackSwallowsFailureCommands(Sqlite3Commands):
    """rollback() reports success after the driver refused to roll back."""

    def rollback(self) -> None:
        try:
            super().rollback()
        except Exception:
            pass


class _SuppressesExitCommitFailureCommands(_ProxyMutantCommands):
    """A block that exits normally after its exit commit failed."""

    def _on_clean_exit(self) -> None:
        try:
            self.commit()
        except Exception:
            pass


class _SuppressesTheBlockErrorCommands(Sqlite3Commands):
    """A block that rolls back and then swallows the caller's exception."""

    @contextmanager
    def _transaction_proxy(self):
        if self._in_transaction:
            raise RuntimeError("transaction() blocks cannot be nested")
        self._in_transaction = True
        try:
            try:
                yield
            except BaseException:
                try:
                    self.rollback()
                except Exception:
                    pass
                return
            self.commit()
        finally:
            self._in_transaction = False


class _SuppressesAfterFailedRollbackCommands(Sqlite3Commands):
    """A block that gives up and swallows the caller's exception when its rollback fails."""

    @contextmanager
    def _transaction_proxy(self):
        if self._in_transaction:
            raise RuntimeError("transaction() blocks cannot be nested")
        self._in_transaction = True
        try:
            try:
                yield
            except BaseException:
                try:
                    self.rollback()
                except BaseException:
                    return
                raise
            else:
                self.commit()
        finally:
            self._in_transaction = False


class _ReentrantTransactionCommands(_ProxyMutantCommands):
    """No nesting guard at all: a nested block on the same instance is entered."""

    _guards_nesting = False


class _LeakedTransactionGuardCommands(_ProxyMutantCommands):
    """The nesting guard never clears, so the instance can only ever run one block."""

    _clears_guard = False


class _TransactionMutant(NamedTuple):
    """One non-conformant adapter, the profile case it must fail, and the assertion inside
    that case which must be the one to fail it.

    ``fragment`` is what makes ``assertion`` a checked claim rather than a comment: the test
    requires that text in the failure message, so a mutant caught by some *other* assertion
    of the same case is not credited with a catch it did not cause.
    """

    slug: str
    case_id: str
    assertion: str
    fragment: str
    commands: type


#: Every assertion in ``_cases_transactions.py`` is pinned by a row below: neuter any one of
#: them and the row naming it stops seeing its failure. That includes the framework's own
#: ``expect_raises`` assertions, pinned by the rows whose fragment is ExpectedRaise's "nothing
#: was raised" text; where a case makes two of them, the *mutant* is what distinguishes the
#: two rows, since the two messages are identical. Two assertions are deliberately *not*
#: pinned here, because no adapter behavior can reach them:
#:
#: * the ``check_event_order(log, ("commit",))`` in ``transactions.commit-delegates-once`` and
#:   its ``("rollback",)`` twin in ``transactions.rollback-delegates-once``. The recording
#:   connection logs an event only when it counts one, so with `commit_calls == 1`,
#:   `rollback_calls == 0` and `cursor_calls == 0` already asserted, the observed log is
#:   necessarily exactly that one event. They are defence-in-depth against a future
#:   instrumentation change that records something those counters do not cover.
_TRANSACTION_MUTANTS = (
    _TransactionMutant(
        slug="no-op-commit-loses-the-write",
        case_id="transactions.commit-persists",
        assertion="committed work survives a later rollback",
        fragment="a committed insert must survive a subsequent rollback()",
        commands=_NoOpCommitCommands,
    ),
    _TransactionMutant(
        slug="no-op-rollback-keeps-the-write",
        case_id="transactions.rollback-discards",
        assertion="uncommitted work is discarded",
        fragment="rollback() must discard the uncommitted insert",
        commands=_NoOpRollbackCommands,
    ),
    _TransactionMutant(
        slug="rollback-discards-committed-rows",
        case_id="transactions.rollback-discards",
        assertion="committed rows survive a rollback",
        fragment="committed baseline rows intact",
        commands=_RollbackDiscardsCommittedRowsCommands,
    ),
    _TransactionMutant(
        slug="block-never-commits-on-exit",
        case_id="transactions.context-commits-on-exit",
        assertion="a clean block commits",
        fragment="a clean transaction() exit must commit",
        commands=_NoCommitOnExitCommands,
    ),
    _TransactionMutant(
        slug="block-re-raises-a-copy",
        case_id="transactions.context-rolls-back-on-error",
        assertion="the block's exception propagates unchanged",
        fragment="the block's exception must propagate as the same exception object",
        commands=_ReRaisesACopyCommands,
    ),
    _TransactionMutant(
        slug="block-never-rolls-back",
        case_id="transactions.context-rolls-back-on-error",
        assertion="a raising block undoes its write",
        fragment="must roll its insert back",
        commands=_NeverRollsBackCommands,
    ),
    _TransactionMutant(
        slug="block-swallows-the-error",
        case_id="transactions.context-rolls-back-on-error",
        assertion="the block re-raises at all",
        fragment="to be raised, but nothing was raised",
        commands=_SuppressesTheBlockErrorCommands,
    ),
    _TransactionMutant(
        slug="commit-returns-a-value",
        case_id="transactions.commit-delegates-once",
        assertion="commit() returns None",
        fragment="commit() must return None",
        commands=_CommitReturnsValueCommands,
    ),
    _TransactionMutant(
        slug="commit-does-not-delegate",
        case_id="transactions.commit-delegates-once",
        assertion="commit() delegates exactly once",
        fragment="expected exactly one connection commit",
        commands=_NoOpCommitCommands,
    ),
    _TransactionMutant(
        slug="commit-also-rolls-back",
        case_id="transactions.commit-delegates-once",
        assertion="commit() does not roll back",
        fragment="commit() must not roll back",
        commands=_CommitAlsoRollsBackCommands,
    ),
    _TransactionMutant(
        slug="commit-acquires-a-cursor",
        case_id="transactions.commit-delegates-once",
        assertion="commit() acquires no cursor",
        fragment="commit() must not acquire a cursor",
        commands=_CommitAcquiresCursorCommands,
    ),
    _TransactionMutant(
        slug="commit-translates-its-failure",
        case_id="transactions.commit-delegates-once",
        assertion="a commit failure propagates unchanged",
        fragment="must propagate from commit() unchanged",
        commands=_CommitTranslatesFailureCommands,
    ),
    _TransactionMutant(
        slug="commit-retries-after-failure",
        case_id="transactions.commit-delegates-once",
        assertion="exactly one commit attempt on failure",
        fragment="expected exactly one commit attempt",
        commands=_CommitRetriesOnFailureCommands,
    ),
    _TransactionMutant(
        slug="failed-commit-rolls-back",
        case_id="transactions.commit-delegates-once",
        assertion="a failed commit triggers no rollback",
        fragment="a failed commit() must not trigger a rollback",
        commands=_CommitRollsBackOnFailureCommands,
    ),
    _TransactionMutant(
        slug="commit-swallows-its-failure",
        case_id="transactions.commit-delegates-once",
        assertion="a commit failure is raised at all",
        fragment="to be raised, but nothing was raised",
        commands=_CommitSwallowsFailureCommands,
    ),
    _TransactionMutant(
        slug="rollback-returns-a-value",
        case_id="transactions.rollback-delegates-once",
        assertion="rollback() returns None",
        fragment="rollback() must return None",
        commands=_RollbackReturnsValueCommands,
    ),
    _TransactionMutant(
        slug="rollback-does-not-delegate",
        case_id="transactions.rollback-delegates-once",
        assertion="rollback() delegates exactly once",
        fragment="expected exactly one connection rollback",
        commands=_NoOpRollbackCommands,
    ),
    _TransactionMutant(
        slug="rollback-also-commits",
        case_id="transactions.rollback-delegates-once",
        assertion="rollback() does not commit",
        fragment="rollback() must not commit",
        commands=_RollbackAlsoCommitsCommands,
    ),
    _TransactionMutant(
        slug="rollback-acquires-a-cursor",
        case_id="transactions.rollback-delegates-once",
        assertion="rollback() acquires no cursor",
        fragment="rollback() must not acquire a cursor",
        commands=_RollbackAcquiresCursorCommands,
    ),
    _TransactionMutant(
        slug="rollback-translates-its-failure",
        case_id="transactions.rollback-delegates-once",
        assertion="a rollback failure propagates unchanged",
        fragment="must propagate from rollback() unchanged",
        commands=_RollbackTranslatesFailureCommands,
    ),
    _TransactionMutant(
        slug="rollback-retries-after-failure",
        case_id="transactions.rollback-delegates-once",
        assertion="exactly one rollback attempt on failure",
        fragment="expected exactly one rollback attempt",
        commands=_RollbackRetriesOnFailureCommands,
    ),
    _TransactionMutant(
        slug="failed-rollback-commits",
        case_id="transactions.rollback-delegates-once",
        assertion="a failed rollback triggers no commit",
        fragment="a failed rollback() must not trigger a commit",
        commands=_RollbackCommitsOnFailureCommands,
    ),
    _TransactionMutant(
        slug="rollback-swallows-its-failure",
        case_id="transactions.rollback-delegates-once",
        assertion="a rollback failure is raised at all",
        fragment="to be raised, but nothing was raised",
        commands=_RollbackSwallowsFailureCommands,
    ),
    _TransactionMutant(
        slug="block-commits-twice",
        case_id="transactions.context-lifecycle-order",
        assertion="a clean block commits exactly once",
        fragment="expected exactly one commit,",
        commands=_CommitsTwiceOnExitCommands,
    ),
    _TransactionMutant(
        slug="clean-block-also-rolls-back",
        case_id="transactions.context-lifecycle-order",
        assertion="a clean block does not roll back",
        fragment="a clean transaction() block must not roll back",
        commands=_RollsBackAfterCommitCommands,
    ),
    _TransactionMutant(
        slug="block-emits-begin-on-entry",
        case_id="transactions.context-lifecycle-order",
        assertion="the block's driver interaction order",
        fragment="expected driver interaction order",
        commands=_EmitsBeginOnEntryCommands,
    ),
    _TransactionMutant(
        slug="block-re-raises-a-copy-instrumented",
        case_id="transactions.context-error-precedence",
        assertion="the block's exception propagates unchanged",
        fragment="the block's exception must propagate as the same exception object",
        commands=_ReRaisesACopyCommands,
    ),
    _TransactionMutant(
        slug="block-never-rolls-back-instrumented",
        case_id="transactions.context-error-precedence",
        assertion="a raising block rolls back exactly once",
        fragment="expected exactly one connection rollback",
        commands=_NeverRollsBackCommands,
    ),
    _TransactionMutant(
        slug="failed-block-commits-anyway",
        case_id="transactions.context-error-precedence",
        assertion="a raising block never commits",
        fragment="a failed transaction() block must not commit",
        commands=_CommitsAfterRollbackOnErrorCommands,
    ),
    _TransactionMutant(
        slug="rollback-failure-masks-the-block-error",
        case_id="transactions.context-error-precedence",
        assertion="the block's error beats a rollback failure",
        fragment="the block's exception must win over a rollback failure",
        commands=_TranslatesRollbackFailureCommands,
    ),
    _TransactionMutant(
        slug="block-retries-a-failed-rollback",
        case_id="transactions.context-error-precedence",
        assertion="exactly one rollback attempt on failure",
        fragment="expected exactly one rollback attempt",
        commands=_RetriesRollbackOnFailureCommands,
    ),
    _TransactionMutant(
        slug="block-swallows-the-error-instrumented",
        case_id="transactions.context-error-precedence",
        assertion="the block re-raises at all",
        fragment="to be raised, but nothing was raised",
        commands=_SuppressesTheBlockErrorCommands,
    ),
    _TransactionMutant(
        slug="failed-rollback-swallows-the-block-error",
        case_id="transactions.context-error-precedence",
        assertion="the block re-raises even when its rollback failed",
        fragment="to be raised, but nothing was raised",
        commands=_SuppressesAfterFailedRollbackCommands,
    ),
    _TransactionMutant(
        slug="exit-commit-failure-translated",
        case_id="transactions.commit-failure-propagates",
        assertion="the exit commit failure propagates unchanged",
        fragment="the commit failure must propagate as the same exception object",
        commands=_TranslatesExitCommitFailureCommands,
    ),
    _TransactionMutant(
        slug="exit-commit-retried",
        case_id="transactions.commit-failure-propagates",
        assertion="exactly one exit commit attempt",
        fragment="expected exactly one commit attempt",
        commands=_RetriesExitCommitCommands,
    ),
    _TransactionMutant(
        slug="failed-exit-commit-rolls-back",
        case_id="transactions.commit-failure-propagates",
        assertion="no rollback after a failed exit commit",
        fragment="no rollback may be attempted after a failed commit",
        commands=_RollsBackAfterFailedExitCommitCommands,
    ),
    _TransactionMutant(
        slug="exit-commit-failure-swallowed",
        case_id="transactions.commit-failure-propagates",
        assertion="an exit commit failure is raised at all",
        fragment="to be raised, but nothing was raised",
        commands=_SuppressesExitCommitFailureCommands,
    ),
    _TransactionMutant(
        slug="base-exception-re-raised-as-a-copy",
        case_id="transactions.context-base-exception-rollback",
        assertion="a BaseException propagates unchanged",
        fragment="must propagate as the same exception object",
        commands=_ReRaisesACopyCommands,
    ),
    _TransactionMutant(
        slug="base-exception-skips-the-rollback",
        case_id="transactions.context-base-exception-rollback",
        assertion="a BaseException still rolls back",
        fragment="a block abandoned by a BaseException must roll back exactly once",
        commands=_RollsBackOnlyOrdinaryErrorsCommands,
    ),
    _TransactionMutant(
        slug="base-exception-commits-anyway",
        case_id="transactions.context-base-exception-rollback",
        assertion="a BaseException never commits",
        fragment="a block abandoned by a BaseException must not commit",
        commands=_CommitsAfterRollbackOnErrorCommands,
    ),
    _TransactionMutant(
        slug="interrupted-rollback-loses-the-interrupt",
        case_id="transactions.context-base-exception-rollback",
        assertion="an interrupt from rollback wins, unchanged",
        fragment="an interrupt raised by rollback must win over the block's ordinary error",
        commands=_TranslatesInterruptedRollbackCommands,
    ),
    _TransactionMutant(
        slug="interrupted-rollback-commits",
        case_id="transactions.context-base-exception-rollback",
        assertion="an interrupted rollback never commits",
        fragment="a block whose rollback was interrupted must not commit",
        commands=_CommitsAfterInterruptedRollbackCommands,
    ),
    _TransactionMutant(
        slug="base-exception-swallowed",
        case_id="transactions.context-base-exception-rollback",
        assertion="a BaseException is re-raised at all",
        fragment="to be raised, but nothing was raised",
        commands=_SuppressesTheBlockErrorCommands,
    ),
    _TransactionMutant(
        slug="interrupted-rollback-swallows-the-error",
        case_id="transactions.context-base-exception-rollback",
        assertion="an interrupted rollback still lets something propagate",
        fragment="to be raised, but nothing was raised",
        commands=_SuppressesAfterFailedRollbackCommands,
    ),
    _TransactionMutant(
        slug="nested-block-is-entered",
        case_id="transactions.context-not-reentrant",
        assertion="a nested block is refused",
        fragment="a nested transaction() block on the same Commands instance must not be entered",
        commands=_ReentrantTransactionCommands,
    ),
    _TransactionMutant(
        slug="nesting-error-commits-anyway",
        case_id="transactions.context-not-reentrant",
        assertion="a block abandoned by a nesting error never commits",
        fragment="a block abandoned by a nesting error must not commit",
        commands=_CommitsAfterRollbackOnErrorCommands,
    ),
    _TransactionMutant(
        slug="nesting-error-skips-the-rollback",
        case_id="transactions.context-not-reentrant",
        assertion="a block abandoned by a nesting error rolls back",
        fragment="a block abandoned by a nesting error must roll back exactly once",
        commands=_NeverRollsBackCommands,
    ),
    _TransactionMutant(
        slug="nesting-guard-never-clears",
        case_id="transactions.context-not-reentrant",
        assertion="the guard clears when the block exits",
        fragment="the nesting guard must clear when a block exits",
        commands=_LeakedTransactionGuardCommands,
    ),
    _TransactionMutant(
        slug="sequential-block-never-commits",
        case_id="transactions.context-not-reentrant",
        assertion="the next sequential block still commits",
        fragment="a sequential transaction() block must commit on clean exit",
        commands=_NoCommitOnExitCommands,
    ),
    _TransactionMutant(
        slug="sequential-block-also-rolls-back",
        case_id="transactions.context-not-reentrant",
        assertion="the next sequential block does not roll back",
        fragment="a clean sequential transaction() block must not roll back",
        commands=_RollsBackAfterCommitCommands,
    ),
    _TransactionMutant(
        slug="nesting-error-swallowed",
        case_id="transactions.context-not-reentrant",
        assertion="the nesting error reaches the caller",
        fragment="to be raised, but nothing was raised",
        commands=_SuppressesTheBlockErrorCommands,
    ),
)


_TRANSACTION_MUTANT_IDS = [f"{mutant.slug}::{mutant.case_id.split('.', 1)[1]}" for mutant in _TRANSACTION_MUTANTS]


def _run_transactions_profile(commands_class, workdir):
    """Run only the ``transactions`` profile against a live sqlite3 harness.

    ``case_ids`` keeps the run to the profile under test — and doubles as a tripwire, since
    a deleted or renamed case makes every mutant test fail with ``CaseSelectionError``.
    """

    class _Harness(Sqlite3ConformanceHarness):
        command_class = commands_class

        def create_commands(self):
            connection = sqlite3.connect(":memory:")
            seed_sqlite_connection(connection)
            return commands_class(connection)

    return run_core_sync(_Harness(workdir), case_ids=list(TRANSACTION_CASE_IDS))


def test_transaction_mutant_base_is_itself_conformant(tmp_path):
    """The mutants' shared scaffolding passes the whole profile unmodified, so each mutant's
    failure is attributable to the single behavior its subclass overrides."""
    report = _run_transactions_profile(_ProxyMutantCommands, tmp_path)
    assert report.passed, [(f.case_id, f.message) for f in report.failures]
    assert [result.case_id for result in report.results] == list(TRANSACTION_CASE_IDS)


@pytest.mark.parametrize("mutant", _TRANSACTION_MUTANTS, ids=_TRANSACTION_MUTANT_IDS)
def test_transaction_mutant_fails_its_named_case_on_its_named_assertion(mutant, tmp_path):
    report = _run_transactions_profile(mutant.commands, tmp_path)
    failed = {failure.case_id: failure.message for failure in report.failures}
    assert mutant.case_id in failed, (
        f"{mutant.slug} must be caught by {mutant.case_id}, which passed; "
        f"the cases it did fail were {sorted(failed)}"
    )
    # failing the right case on the *wrong* assertion proves nothing about the assertion the
    # table says this row pins, so the failure message has to match it too
    assert mutant.fragment in failed[mutant.case_id], (
        f"{mutant.slug} must fail {mutant.case_id} on the {mutant.assertion!r} assertion the table "
        f"names for it: expected {mutant.fragment!r} in {failed[mutant.case_id]!r}"
    )


def test_every_transactions_case_is_pinned_by_a_mutant():
    """No case may ship without a mutant proving at least one of its assertions bites."""
    pinned = {mutant.case_id for mutant in _TRANSACTION_MUTANTS}
    assert pinned == set(TRANSACTION_CASE_IDS)


class _InvalidCapabilityCommands(MockSyncConformanceCommands):
    capabilities = {"transactions"}  # type: ignore[assignment]  # deliberately wrong: set of str


def test_invalid_capability_declaration_fails_clearly(isolated_registry):
    class _Harness(MockSyncConformanceHarness):
        adapter_name = "conformance-mock-invalid-caps"
        command_class = _InvalidCapabilityCommands

        def create_commands(self):
            return _InvalidCapabilityCommands(FakeSyncConnection(seeded_mini_db()))

    report = run_core_sync(_Harness())
    named = next(result for result in report.results if result.case_id == "capabilities.declaration-valid")
    assert not named.passed
    assert "frozenset" in named.message


class _DeclaredTransactionsCommands(MockSyncConformanceCommands):
    capabilities = frozenset({AdapterCapability.TRANSACTIONS})


class _DeclaredRawReaderCommands(MockSyncConformanceCommands):
    capabilities = frozenset({AdapterCapability.RAW_READER})


def test_declared_capability_without_profile_fails_clearly(isolated_registry):
    name = "conformance-mock-declared-raw"
    _register_mock_sync(name=name, commands=_DeclaredRawReaderCommands)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _DeclaredRawReaderCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _DeclaredRawReaderCommands(FakeSyncConnection(seeded_mini_db()))

    report = run_core_sync(_Harness())
    failed_ids = [failure.case_id for failure in report.failures]
    assert failed_ids == ["capabilities.declared-profile-populated"], failed_ids
    named = report.failures[0]
    assert "raw_reader" in named.message
    assert named.profile_id == CORE_SYNC


def test_synthetic_capability_profile_runs_but_cannot_cover_a_declaration(isolated_registry):
    """A test-local synthetic profile runs its cases, but only the production catalog
    can satisfy the declared-capability honesty check — injection is not a bypass."""
    name = "conformance-mock-synth-raw"
    _register_mock_sync(name=name, commands=_DeclaredRawReaderCommands)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _DeclaredRawReaderCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _DeclaredRawReaderCommands(FakeSyncConnection(seeded_mini_db()))

    ran = []

    def _raw_case(ctx):
        ran.append(ctx.case_id)
        commands = ctx.command_class(FakeSyncConnection())
        ctx.check(commands.supports(AdapterCapability.RAW_READER), "declared capability must be supported")

    synthetic = ConformanceProfile(
        profile_id="raw_reader",
        capability=AdapterCapability.RAW_READER,
        sync_cases=(SyncCase("raw_reader.smoke", "synthetic raw reader case", "instrumented", _raw_case),),
    )
    report = run_core_sync(_Harness(), capability_catalog={AdapterCapability.RAW_READER: synthetic})
    assert ran == ["raw_reader.smoke"], "the injected profile's cases must actually run"
    synthetic_results = [result for result in report.results if result.profile_id == "raw_reader"]
    assert [result.case_id for result in synthetic_results] == ["raw_reader.smoke"]
    assert synthetic_results[0].passed
    # the declaration honesty case still fails: the production catalog has no
    # raw_reader profile, and an injected catalog can never make one appear covered
    failed_ids = [failure.case_id for failure in report.failures]
    assert failed_ids == ["capabilities.declared-profile-populated"], failed_ids
    assert (
        AdapterCapability.RAW_READER not in capability_profiles()
    ), "the production catalog must not cover a capability until its feature ships"


def test_option_probes_cannot_be_waived_by_declaration_alone(isolated_registry):
    """A falsely declared capability must still fail the option-honesty probes, even
    with an injected catalog claiming coverage (the adversarial-audit bypass)."""
    name = "conformance-mock-false-caps"

    class _FalselyDeclaringCommands(MockSyncConformanceCommands):
        capabilities = frozenset(AdapterCapability)

        @staticmethod
        def _resolve_options(options=None):
            # deliberately dishonest: accepts every option and applies none of them,
            # returning the caller's instance so hook-identity checks stay quiet
            from pydapper.command_options import CommandOptions

            return options if options is not None else CommandOptions()

    _register_mock_sync(name=name, commands=_FalselyDeclaringCommands)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _FalselyDeclaringCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _FalselyDeclaringCommands(FakeSyncConnection(seeded_mini_db()))

    def _noop(ctx):
        return None

    injected = {
        member: ConformanceProfile(
            profile_id=member.value,
            capability=member,
            sync_cases=(SyncCase(f"{member.value}.noop", "attacker no-op", "instrumented", _noop),),
        )
        for member in AdapterCapability
    }
    report = run_core_sync(_Harness(), capability_catalog=injected)
    failed_ids = {failure.case_id for failure in report.failures}
    assert "options.unsupported-raises" in failed_ids, "option probes must not be waived by declaration alone"
    assert "options.unsupported-before-driver-work" in failed_ids
    assert "capabilities.declared-profile-populated" in failed_ids
    assert not report.passed


def test_production_capability_catalog_ships_transactions_and_is_immutable():
    catalog = capability_profiles()
    assert set(catalog) == {AdapterCapability.TRANSACTIONS}
    profile = catalog[AdapterCapability.TRANSACTIONS]
    assert profile.profile_id == "transactions"
    assert profile.capability is AdapterCapability.TRANSACTIONS
    assert profile.sync_cases, "the transactions profile must ship real sync cases"
    # async transaction APIs have not landed; async cases arrive with that feature
    assert profile.async_cases == ()
    validate_capability_catalog(catalog)
    with pytest.raises(TypeError):
        catalog[AdapterCapability.TRANSACTIONS] = None  # type: ignore[index]


def test_transactions_profile_inventory_is_exactly_the_named_cases():
    """The inventory is spelled out, so deleting, renaming, or reordering a shipped case has
    to fail here instead of quietly redefining what the capability certifies."""
    profile = capability_profiles()[AdapterCapability.TRANSACTIONS]
    assert tuple(case.case_id for case in profile.sync_cases) == TRANSACTION_CASE_IDS
    assert len(profile.sync_cases) == 11
    assert {case.kind for case in profile.sync_cases} == {"live", "instrumented"}
    assert all(case.description for case in profile.sync_cases)


def test_documented_transactions_cases_match_the_shipped_profile():
    """The docs table is the public contract; it may not drift from the shipped inventory."""
    text = (REPO_ROOT / "docs" / "adapter_conformance.md").read_text(encoding="utf-8")
    documented = tuple(re.findall(r"^\| `(transactions\.[a-z-]+)` \|", text, flags=re.MULTILINE))
    assert documented == TRANSACTION_CASE_IDS
    assert f"{len(TRANSACTION_CASE_IDS)} sync cases" in text


def test_zero_case_profile_is_rejected():
    with pytest.raises(ProfileDefinitionError) as exc_info:
        ConformanceProfile(profile_id="transactions", capability=AdapterCapability.TRANSACTIONS)
    assert exc_info.value.profile_id == "transactions"


def test_duplicate_case_ids_are_rejected():
    def _noop(ctx):
        return None

    cases = (
        SyncCase("dup.case", "first", "instrumented", _noop),
        SyncCase("dup.case", "second", "instrumented", _noop),
    )
    with pytest.raises(ProfileDefinitionError):
        ConformanceProfile(profile_id="core-sync", capability=None, sync_cases=cases)


def test_mismatched_capability_catalog_key_is_rejected(isolated_registry):
    _register_mock_sync()

    def _noop(ctx):
        return None

    profile = ConformanceProfile(
        profile_id="raw-reader",
        capability=AdapterCapability.RAW_READER,
        sync_cases=(SyncCase("raw.smoke", "d", "instrumented", _noop),),
    )
    with pytest.raises(ProfileDefinitionError):
        validate_capability_catalog({AdapterCapability.TRANSACTIONS: profile})
    with pytest.raises(ProfileDefinitionError):
        run_core_sync(MockSyncConformanceHarness(), capability_catalog={AdapterCapability.TRANSACTIONS: profile})


# ------------------------------------------------------------------ harness validation


def test_missing_factory_reports_profile_case_and_field(isolated_registry):
    class _NoFactoryHarness(SyncAdapterHarness):
        adapter_name = MOCK_SYNC_ADAPTER_NAME
        command_class = MockSyncConformanceCommands
        connect_dsn = MockSyncConformanceHarness.connect_dsn

    _register_mock_sync()
    report = run_core_sync(_NoFactoryHarness())
    factory_failures = [failure for failure in report.failures if failure.missing_field == "create_commands"]
    assert factory_failures, "live cases must fail with the missing harness field"
    sample = factory_failures[0]
    assert sample.profile_id == CORE_SYNC
    assert sample.case_id
    assert "create_commands" in sample.message
    for failure in factory_failures:
        assert failure.missing_field == "create_commands"


def test_missing_teardown_reports_missing_field(isolated_registry):
    class _NoTeardownHarness(SyncAdapterHarness):
        adapter_name = MOCK_SYNC_ADAPTER_NAME
        command_class = MockSyncConformanceCommands
        connect_dsn = MockSyncConformanceHarness.connect_dsn

        def create_commands(self):
            return MockSyncConformanceCommands(FakeSyncConnection(seeded_mini_db()))

    _register_mock_sync()
    report = run_core_sync(_NoTeardownHarness())
    assert any(failure.missing_field == "teardown_commands" for failure in report.failures)


def test_missing_connect_dsn_reports_missing_field(isolated_registry):
    class _NoDsnHarness(MockSyncConformanceHarness):
        connect_dsn = None

    _register_mock_sync()
    report = run_core_sync(_NoDsnHarness())
    named = next(result for result in report.results if result.case_id == "registration.dsn-connect")
    assert not named.passed
    assert named.missing_field == "connect_dsn"


def test_missing_adapter_name_fails_before_any_case():
    class _AnonymousHarness(SyncAdapterHarness):
        command_class = MockSyncConformanceCommands

    with pytest.raises(HarnessDefinitionError) as exc_info:
        run_core_sync(_AnonymousHarness())
    assert exc_info.value.missing_field == "adapter_name"
    assert exc_info.value.profile_id == CORE_SYNC


def test_missing_command_class_fails_before_any_case():
    class _ClasslessHarness(SyncAdapterHarness):
        adapter_name = MOCK_SYNC_ADAPTER_NAME

    with pytest.raises(HarnessDefinitionError) as exc_info:
        run_core_sync(_ClasslessHarness())
    assert exc_info.value.missing_field == "command_class"
    assert exc_info.value.profile_id == CORE_SYNC


def test_sync_and_async_harnesses_do_not_require_the_opposite_mode():
    assert not hasattr(SyncAdapterHarness, "cursor_factory_style")
    sync_members = set(vars(SyncAdapterHarness))
    assert "create_commands" in sync_members and "teardown_commands" in sync_members
    # the mock sync harness defines no async member and still passes (see above); the
    # runners also reject a harness of the opposite mode outright:
    with pytest.raises(TypeError):
        run_core_sync(MockAsyncConformanceHarness())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_async_runner_rejects_sync_harness():
    with pytest.raises(TypeError):
        await run_core_async(MockSyncConformanceHarness())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_cancellation_propagates_and_still_tears_down(isolated_registry):
    """Task cancellation must abort the run promptly, not be recorded as a failed case,
    and the active case's live resources must still be released first."""
    import asyncio

    _register_mock_async()
    torn_down = []

    class _HangingHarness(MockAsyncConformanceHarness):
        async def create_commands(self):
            commands = await super().create_commands()
            await asyncio.sleep(3600)
            return commands

        async def teardown_commands(self, commands):
            torn_down.append(commands)
            await super().teardown_commands(commands)

    task = asyncio.get_running_loop().create_task(run_core_async(_HangingHarness()))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled(), "run_core_async must not swallow cancellation into a report"


# ------------------------------------------------------------------ isolation, cleanup, precedence


class _TrackingHarness(MockSyncConformanceHarness):
    def __init__(self):
        self.created = []
        self.torn_down = []

    def create_commands(self):
        commands = super().create_commands()
        self.created.append(commands)
        return commands

    def teardown_commands(self, commands):
        self.torn_down.append(commands)
        super().teardown_commands(commands)


def test_fresh_case_isolation_and_teardown_after_success(isolated_registry):
    _register_mock_sync()
    harness = _TrackingHarness()
    report = run_core_sync(harness)
    assert report.passed, [(f.case_id, f.message) for f in report.failures]
    assert harness.created, "live cases must create commands"
    assert len(set(map(id, harness.created))) == len(harness.created), "every case must get a fresh command"
    assert sorted(map(id, harness.torn_down)) == sorted(map(id, harness.created)), "every created command is torn down"
    # every live case except registration.dsn-connect (which exercises connect() instead
    # of the factory) creates at least one fresh command instance
    live_case_count = sum(1 for case in core_sync_profile().sync_cases if case.kind == "live")
    assert len(harness.created) >= live_case_count - 1


def test_teardown_failure_fails_a_passing_case(isolated_registry):
    class _FailingTeardownHarness(MockSyncConformanceHarness):
        def teardown_commands(self, commands):
            raise RuntimeError("teardown boom")

    _register_mock_sync()
    report = run_core_sync(_FailingTeardownHarness())
    named = next(result for result in report.results if result.case_id == "params.params-keyword")
    assert not named.passed
    assert isinstance(named.cause, RuntimeError)
    assert "teardown" in named.message


def test_case_failure_takes_precedence_over_teardown_failure(isolated_registry):
    name = "conformance-mock-broken-and-leaky-teardown"
    _register_mock_sync(name=name, commands=_BrokenRowMappingCommands)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _BrokenRowMappingCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _BrokenRowMappingCommands(FakeSyncConnection(seeded_mini_db()))

        def teardown_commands(self, commands):
            raise RuntimeError("teardown boom")

    report = run_core_sync(_Harness())
    named = next(result for result in report.results if result.case_id == "rows.query-buffered")
    assert not named.passed
    assert "teardown" not in named.message, "the active case failure must be preserved"
    assert isinstance(named.cleanup_error, RuntimeError), "the teardown failure is retained as structured info"


def test_adapter_code_cannot_declare_its_own_case_passed(isolated_registry):
    from pydapper.testing.adapter_conformance._results import CaseCheckError

    class _SelfPassingHarness(MockSyncConformanceHarness):
        def create_commands(self):
            raise CaseCheckError("adapter pretends everything is fine")

    _register_mock_sync()
    report = run_core_sync(_SelfPassingHarness())
    live_case_ids = {case.case_id for case in core_sync_profile().sync_cases if case.kind == "live"}
    live_case_ids.discard("registration.dsn-connect")  # exercises connect(), not the factory
    live_results = [result for result in report.results if result.case_id in live_case_ids]
    assert live_results
    assert all(not result.passed for result in live_results), "raising framework errors must never mark a case passed"

    with pytest.raises(dataclasses.FrozenInstanceError):
        report.results[0].passed = True  # type: ignore[misc]


# ------------------------------------------------------------------ concrete first-party classes (service-free)


# derived from the single conformance source of truth so this list cannot go stale
_SYNC_CONCRETE_CLASSES = [
    entry.command_class for entry in FIRST_PARTY_CONFORMANCE_ENTRIES.values() if entry.mode == "sync"
]


@pytest.mark.parametrize("command_class", _SYNC_CONCRETE_CLASSES, ids=lambda cls: cls.__name__)
def test_concrete_sync_class_lifecycle_over_instrumented_connection(command_class):
    connection = RecordingConnection(CursorScript(rows=((1, "alpha"), (2, "beta"))))
    commands = command_class(connection)
    rows = commands.query("SELECT id, label FROM t")
    assert rows == [{"id": 1, "label": "alpha"}, {"id": 2, "label": "beta"}]
    assert connection.cursor_calls == 1
    recorder = connection.recorders[0]
    assert recorder.exit_calls + recorder.close_calls == 1

    fault = RuntimeError("boom")
    failing = RecordingConnection(CursorScript(execute_error=fault, exit_error=ValueError("cleanup")))
    commands = command_class(failing)
    with pytest.raises(RuntimeError) as exc_info:
        commands.query("SELECT id, label FROM t")
    assert exc_info.value is fault
    assert failing.recorders[0].exit_calls == 1


def test_mysql_query_first_lifecycle_is_exercised_not_bypassed():
    """The MySQL override must keep its documented drain inside the shared lifecycle."""
    connection = RecordingConnection(CursorScript(rows=((1, "alpha"), (2, "beta"))))
    commands = MySqlConnectorPythonCommands(connection)
    row = commands.query_first("SELECT id, label FROM t")
    assert row == {"id": 1, "label": "alpha"}
    kinds = connection.log.kinds()
    assert kinds == ("cursor", "enter", "execute", "fetchone", "fetchall", "exit"), kinds

    fault = RuntimeError("execute boom")
    failing = RecordingConnection(CursorScript(execute_error=fault, exit_error=ValueError("cleanup")))
    commands = MySqlConnectorPythonCommands(failing)
    with pytest.raises(RuntimeError) as exc_info:
        commands.query_first("SELECT id, label FROM t")
    assert exc_info.value is fault, "the MySQL override must preserve active-error precedence"
    exit_event = failing.log.first("exit")
    assert exit_event is not None and exit_event.exc_value is fault


class _MySqlUnreadResultCursor:
    """Plain cursor emulating mysql-connector's unread-result surface."""

    def __init__(self):
        self.rows = [(1, "a"), (2, "b"), (3, "c")]
        self.unread_result = True
        self.drained = False
        self.reset_calls = []
        self.rowcount = -1
        self.closed = 0

    @property
    def description(self):
        return (("id", None, None, None, None, None, None), ("label", None, None, None, None, None, None))

    def execute(self, sql, parameters=None):
        return None

    def executemany(self, sql, seq_of_parameters=None):
        return None

    def reset(self, free=False):
        self.reset_calls.append(free)
        raise TypeError("emulates drivers whose reset() takes no arguments on retry")

    def fetchmany(self, size=1):
        taken = self.rows[:size]
        del self.rows[:size]
        return taken

    def fetchone(self):
        if not self.rows:
            return None
        return self.rows.pop(0)

    def fetchall(self):
        self.drained = True
        self.unread_result = False
        remaining = self.rows
        self.rows = []
        return remaining

    def close(self):
        self.closed += 1


def test_mysql_query_single_drains_unread_results_before_raising():
    cursor = _MySqlUnreadResultCursor()

    class _Connection:
        def cursor(self, *args, **kwargs):
            return cursor

    commands = MySqlConnectorPythonCommands(_Connection())
    with pytest.raises(MoreThanOneResultException):
        commands.query_single("SELECT id, label FROM t")
    assert cursor.drained, "the documented unread-result drain must run before the cardinality error"
    assert cursor.closed == 1


@pytest.mark.asyncio
async def test_psycopg3_async_cursor_normalization_over_instrumented_connection():
    connection = SynchronousCursorRecordingAsyncConnection(CursorScript(rows=((1, "alpha"),)))
    commands = Psycopg3CommandsAsync(connection)
    wrapper = commands.cursor()
    assert isinstance(wrapper, _RealAwaitableAsyncContextManager)
    cursor = await wrapper
    assert cursor is connection.cursors[0]

    connection = SynchronousCursorRecordingAsyncConnection(CursorScript(rows=((1, "alpha"), (2, "beta"))))
    commands = Psycopg3CommandsAsync(connection)
    rows = await commands.query_async("SELECT id, label FROM t")
    assert rows == [{"id": 1, "label": "alpha"}, {"id": 2, "label": "beta"}]
    assert connection.recorders[0].exit_calls == 1

    fault = RuntimeError("boom")
    failing = SynchronousCursorRecordingAsyncConnection(CursorScript(execute_error=fault, exit_error=ValueError("x")))
    commands = Psycopg3CommandsAsync(failing)
    with pytest.raises(RuntimeError) as exc_info:
        await commands.query_async("SELECT id, label FROM t")
    assert exc_info.value is fault


@pytest.mark.asyncio
async def test_aiopg_commands_over_instrumented_connection():
    connection = RecordingAsyncConnection(CursorScript(rows=((1, "alpha"), (2, "beta"))))
    commands = AiopgCommands(connection)
    rows = await commands.query_async("SELECT id, label FROM t")
    assert rows == [{"id": 1, "label": "alpha"}, {"id": 2, "label": "beta"}]
    assert connection.recorders[0].exit_calls == 1

    # aiopg emulates executemany by looping execute and summing rowcounts
    connection = RecordingAsyncConnection(CursorScript(rowcount=1))
    commands = AiopgCommands(connection)
    count = await commands.execute_async(
        "INSERT INTO t (id) VALUES (?id?)",
        params=[{"id": 1}, {"id": 2}],
    )
    assert count == 2
    assert connection.log.count("execute") == 2
    assert connection.log.count("executemany") == 0


# ------------------------------------------------------------------ first-party drift invariants


def _installed_first_party_registrations(isolated_registry):
    entry_points = [
        entry_point
        for entry_point in importlib.metadata.entry_points(group=GROUP)
        if entry_point.dist is not None and _canonicalize(entry_point.dist.name) == "pydapper"
    ]
    assert entry_points, "the pydapper distribution must declare installed adapter entry points"
    for entry_point in entry_points:
        callback = entry_point.load()
        callback()
    registrations = {}
    for entry_point in entry_points:
        record = isolated_registry[entry_point.name]
        if record.commands is not None:
            registrations[(entry_point.name, "sync")] = record.commands
        if record.async_commands is not None:
            registrations[(entry_point.name, "async")] = record.async_commands
    return registrations


def test_every_installed_first_party_mode_has_a_conformance_entry(isolated_registry):
    installed = _installed_first_party_registrations(isolated_registry)
    assert set(installed) == set(FIRST_PARTY_CONFORMANCE_ENTRIES), (
        "every installed first-party adapter mode must have exactly one conformance entry; "
        f"installed={sorted(installed)}, entries={sorted(FIRST_PARTY_CONFORMANCE_ENTRIES)}"
    )
    for key, command_class in installed.items():
        entry = FIRST_PARTY_CONFORMANCE_ENTRIES[key]
        assert entry.command_class is command_class, key
        assert entry.adapter_name == key[0]
        assert entry.mode == key[1]


def test_every_conformance_entry_module_exists_and_targets_its_adapter():
    for (name, mode), entry in FIRST_PARTY_CONFORMANCE_ENTRIES.items():
        module_path = REPO_ROOT / entry.test_module
        assert module_path.is_file(), f"missing conformance entry module {entry.test_module}"
        text = module_path.read_text()
        assert f'"{name}"' in text, (name, mode)
        expected_runner = "run_core_sync" if mode == "sync" else "run_core_async"
        assert expected_runner in text, (name, mode)
        assert "FIRST_PARTY_CONFORMANCE_ENTRIES" in text, (name, mode)
        assert re.search(r"^def test_|^async def test_", text, re.MULTILINE), (name, mode)
        assert "raise_for_failures" in text, (name, mode)


def test_every_declared_first_party_capability_has_a_populated_profile(isolated_registry):
    installed = _installed_first_party_registrations(isolated_registry)
    catalog = capability_profiles()
    for (name, mode), command_class in installed.items():
        declared = command_class.capabilities
        assert isinstance(declared, frozenset), (name, mode)
        for member in declared:
            assert member in catalog, f"{name}/{mode} declares {member.value!r} without a conformance profile"
            profile = catalog[member]
            cases = profile.sync_cases if mode == "sync" else profile.async_cases
            assert cases, f"{name}/{mode} declares {member.value!r} but its profile has no {mode} cases"


# ------------------------------------------------------------------ built artifacts carry the helper


def _expected_helper_members():
    """Derive the shipped helper file list from the source tree, so a renamed or new
    module is covered automatically instead of silently dropping out of the check."""
    members = {str(path.relative_to(REPO_ROOT)) for path in (REPO_ROOT / "pydapper" / "testing").rglob("*.py")}
    assert len(members) >= 11, members
    return members


def test_built_wheel_and_sdist_ship_the_conformance_helper(tmp_path):
    import shutil

    poetry = shutil.which("poetry")
    assert poetry is not None, "the poetry executable is required to build the artifacts under test"
    completed = subprocess.run(
        [poetry, "build", "--output", str(tmp_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, f"poetry build failed:\n{completed.stdout}\n{completed.stderr}"

    expected = _expected_helper_members()

    [wheel_path] = tmp_path.glob("pydapper-*.whl")
    wheel_extract = tmp_path / "wheel-extract"
    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())
        wheel.extractall(wheel_extract)
    missing = expected - names
    assert not missing, f"wheel is missing helper files: {sorted(missing)}"

    [sdist_path] = tmp_path.glob("pydapper-*.tar.gz")
    sdist_extract = tmp_path / "sdist-extract"
    with tarfile.open(sdist_path) as sdist:
        sdist_names = {"/".join(name.split("/")[1:]) for name in sdist.getnames()}
        sdist.extractall(sdist_extract)
    missing = expected - sdist_names
    assert not missing, f"sdist is missing helper files: {sorted(missing)}"

    # the packaged helper must IMPORT from each built artifact, not just be listed in
    # it: run a hermetic interpreter whose sys.path is only the extracted artifact
    [sdist_root] = sdist_extract.glob("pydapper-*")
    for artifact_root in (wheel_extract, sdist_root):
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "import pydapper.testing.adapter_conformance as helper; "
                "assert helper.CORE_SYNC == 'core-sync' and helper.CORE_ASYNC == 'core-async'; "
                "assert callable(helper.run_core_sync) and callable(helper.run_core_async); "
                "print('ARTIFACT-IMPORT-OK')",
                str(artifact_root),
            ],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, f"import from {artifact_root} failed:\n{completed.stderr}"
        assert "ARTIFACT-IMPORT-OK" in completed.stdout


# ------------------------------------------------------------------ documented examples actually run


@pytest.mark.parametrize(
    "example",
    ["docs_src/adapter_conformance/sync_example.py", "docs_src/adapter_conformance/async_example.py"],
)
def test_documented_third_party_examples_run_as_shown(example):
    path = REPO_ROOT / example
    assert path.is_file(), f"documented example {example} is missing"
    completed = subprocess.run([sys.executable, str(path)], cwd=REPO_ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, f"{example} failed:\n{completed.stdout}\n{completed.stderr}"
    assert "import pytest" not in path.read_text(), "documented examples must not require pytest"


# ------------------------------------------------------------------ statement catalog


def _noop_case(ctx):
    return None


def test_statement_catalog_exposes_ids_and_rejects_unknown_statements():
    ids = statement_ids()
    assert ids == tuple(sorted(ids)), "statement ids must be reported in a stable sorted order"
    assert {"select_all", "insert_row", "update_label"} <= set(ids)
    assert render_statement("select_all", "t") == "SELECT id, label, score, note FROM t ORDER BY id"
    assert render_statement("select_all", "t", {"select_all": "SELECT 1 FROM {table}"}) == "SELECT 1 FROM t"
    with pytest.raises(KeyError) as exc_info:
        render_statement("no_such_statement", "t")
    assert "no_such_statement" in str(exc_info.value)


# ------------------------------------------------------------------ profile definition validation


def test_invalid_case_kind_is_rejected():
    with pytest.raises(ProfileDefinitionError) as exc_info:
        ConformanceProfile(
            profile_id=CORE_SYNC,
            capability=None,
            sync_cases=(SyncCase("bad.kind", "d", "made-up-kind", _noop_case),),
        )
    assert "invalid kind" in str(exc_info.value)


def test_empty_profile_id_is_rejected():
    with pytest.raises(ProfileDefinitionError):
        ConformanceProfile(
            profile_id="",
            capability=None,
            sync_cases=(SyncCase("x.y", "d", "instrumented", _noop_case),),
        )


def test_non_enum_profile_capability_is_rejected():
    with pytest.raises(ProfileDefinitionError) as exc_info:
        ConformanceProfile(
            profile_id="transactions",
            capability="transactions",  # type: ignore[arg-type]
            sync_cases=(SyncCase("x.y", "d", "instrumented", _noop_case),),
        )
    assert "AdapterCapability" in str(exc_info.value)


def test_non_enum_capability_catalog_key_is_rejected():
    profile = ConformanceProfile(
        profile_id="transactions",
        capability=AdapterCapability.TRANSACTIONS,
        sync_cases=(SyncCase("transactions.smoke", "d", "instrumented", _noop_case),),
    )
    with pytest.raises(ProfileDefinitionError) as exc_info:
        validate_capability_catalog({"transactions": profile})  # type: ignore[dict-item]
    assert "AdapterCapability member" in str(exc_info.value)


# ------------------------------------------------------------------ framework assertion helpers


def test_check_event_order_helper_reports_the_observed_order(isolated_registry):
    _register_mock_sync()
    ctx = SyncCaseContext(MockSyncConformanceHarness(), CORE_SYNC, "helper.check-order", {})
    connection = RecordingConnection()
    commands = ctx.instrumented_commands(connection)
    commands.query("SELECT id, label FROM t")

    observed = connection.log.kinds()
    ctx.check_event_order(connection.log, observed)

    with pytest.raises(CaseCheckError) as exc_info:
        ctx.check_event_order(connection.log, ("execute",))
    assert "expected driver interaction order" in str(exc_info.value)

    # the helper is an *exact* order assertion, not a prefix one: cases that mean to pin only
    # the preparation prefix say so with their own prefix check, and every other case relies on
    # trailing interactions being rejected here
    with pytest.raises(CaseCheckError) as prefix_info:
        ctx.check_event_order(connection.log, observed[:-1])
    assert "expected driver interaction order" in str(prefix_info.value)


def test_conformance_failure_error_tolerates_a_report_without_failures():
    report = ConformanceReport(
        profile_id=CORE_SYNC,
        adapter_name="mock",
        command_class_name="Mock",
        results=(CaseResult(CORE_SYNC, "some.case", True),),
    )
    error = ConformanceFailureError(report)
    assert error.failures == ()
    assert "0 conformance case(s) failed" in str(error)


# ------------------------------------------------------------------ instrumentation internals


def test_recording_cursor_records_executemany_through_the_command_class(isolated_registry):
    connection = RecordingConnection(CursorScript())
    commands = MockSyncConformanceCommands(connection)
    affected = commands.execute(
        "INSERT INTO t (id, label) VALUES (?id?, ?label?)",
        params=[{"id": 1, "label": "a"}, {"id": 2, "label": "b"}],
    )
    event = connection.log.first("executemany")
    assert event is not None
    assert event.params == [(1, "a"), (2, "b")], "the driver must observe one bound tuple per record"
    assert affected == 2, "the default script derives the rowcount from the executemany length"


def test_recording_cursor_can_script_a_fixed_executemany_rowcount(isolated_registry):
    connection = RecordingConnection(CursorScript(rowcount_from_executemany_length=False, rowcount=7))
    commands = MockSyncConformanceCommands(connection)
    affected = commands.execute("INSERT INTO t (id, label) VALUES (?id?, ?label?)", params=[{"id": 1, "label": "a"}])
    assert affected == 7


def test_recording_cursor_injects_scripted_interaction_failures():
    boom = RuntimeError("scripted failure")
    connection = RecordingConnection(
        CursorScript(executemany_error=boom, fetchone_error=boom, fetchmany_error=boom),
        cursor_style="plain",
    )
    cursor = connection.cursor()
    with pytest.raises(RuntimeError):
        cursor.executemany("INSERT INTO t (id) VALUES (%s)", [(1,)])
    with pytest.raises(RuntimeError):
        cursor.fetchone()
    with pytest.raises(RuntimeError):
        cursor.fetchmany(2)


@pytest.mark.asyncio
async def test_recording_async_cursor_records_executemany_through_the_command_class():
    connection = RecordingAsyncConnection(CursorScript())
    commands = MockAsyncConformanceCommands(connection)
    affected = await commands.execute_async(
        "INSERT INTO t (id, label) VALUES (?id?, ?label?)",
        params=[{"id": 1, "label": "a"}, {"id": 2, "label": "b"}],
    )
    event = connection.log.first("executemany")
    assert event is not None
    assert event.params == [(1, "a"), (2, "b")]
    assert affected == 2


def test_recording_connections_accept_a_sequence_of_scripts():
    """A per-cursor script sequence lets one case drive differently-behaving cursors."""
    scripts = [CursorScript(rowcount=1), CursorScript(rowcount=2)]

    connection = RecordingConnection(scripts)
    connection.cursor()
    connection.cursor()
    assert [recorder.script.rowcount for recorder in connection.recorders] == [1, 2]

    async_connection = RecordingAsyncConnection(scripts)
    assert async_connection.cursor_calls == 0


def test_recording_connection_records_commit_and_rollback():
    connection = RecordingConnection()
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 0

    connection.commit()
    connection.rollback()
    connection.rollback()
    assert connection.commit_calls == 1
    assert connection.rollback_calls == 2
    assert connection.log.kinds() == ("commit", "rollback", "rollback")


def test_recording_connection_injects_commit_and_rollback_faults():
    commit_fault = RuntimeError("commit boom")
    rollback_fault = RuntimeError("rollback boom")
    connection = RecordingConnection(commit_error=commit_fault, rollback_error=rollback_fault)

    with pytest.raises(RuntimeError) as commit_info:
        connection.commit()
    assert commit_info.value is commit_fault
    with pytest.raises(RuntimeError) as rollback_info:
        connection.rollback()
    assert rollback_info.value is rollback_fault
    # the interaction is recorded even when it fails
    assert connection.commit_calls == 1
    assert connection.rollback_calls == 1
    assert connection.log.kinds() == ("commit", "rollback")


# ------------------------------------------------------------------ connect() cleanup tolerance


class _CloselessFakeConnection(FakeSyncConnection):
    """Exposes no callable ``close``, like a pooled/managed connection handle."""

    close = None  # type: ignore[assignment]


class _RaisingCloseFakeConnection(FakeSyncConnection):
    def close(self):
        raise RuntimeError("close boom")


class _CloselessConnectCommands(MockSyncConformanceCommands):
    @classmethod
    def connect(cls, parsed_dsn, **connect_kwargs):
        return cls(_CloselessFakeConnection(seeded_mini_db()))


class _RaisingCloseConnectCommands(MockSyncConformanceCommands):
    @classmethod
    def connect(cls, parsed_dsn, **connect_kwargs):
        return cls(_RaisingCloseFakeConnection(seeded_mini_db()))


@pytest.mark.parametrize(
    "commands_class",
    [_CloselessConnectCommands, _RaisingCloseConnectCommands],
    ids=["no-close", "close-raises"],
)
def test_dsn_connect_case_tolerates_unclosable_connections(isolated_registry, commands_class):
    """The connect() case verifies the adapter, never the connection's close behavior."""
    name = f"conformance-mock-{commands_class.__name__.lstrip('_').lower()}"
    _register_mock_sync(name=name, commands=commands_class)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = commands_class
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return commands_class(FakeSyncConnection(seeded_mini_db()))

    report = run_core_sync(_Harness())
    named = next(result for result in report.results if result.case_id == "registration.dsn-connect")
    assert named.passed, named.message


class _CloselessFakeAsyncConnection(FakeAsyncConnection):
    close = None  # type: ignore[assignment]


class _RaisingCloseFakeAsyncConnection(FakeAsyncConnection):
    def close(self):
        raise RuntimeError("close boom")


class _CloselessConnectAsyncCommands(MockAsyncConformanceCommands):
    @classmethod
    async def connect_async(cls, parsed_dsn, **connect_kwargs):
        return cls(_CloselessFakeAsyncConnection(seeded_mini_db()))


class _RaisingCloseConnectAsyncCommands(MockAsyncConformanceCommands):
    @classmethod
    async def connect_async(cls, parsed_dsn, **connect_kwargs):
        return cls(_RaisingCloseFakeAsyncConnection(seeded_mini_db()))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "commands_class",
    [_CloselessConnectAsyncCommands, _RaisingCloseConnectAsyncCommands],
    ids=["no-close", "close-raises"],
)
async def test_async_dsn_connect_case_tolerates_unclosable_connections(isolated_registry, commands_class):
    name = f"conformance-mock-{commands_class.__name__.lstrip('_').lower()}"
    _register_mock_async(name=name, async_commands=commands_class)

    class _Harness(MockAsyncConformanceHarness):
        adapter_name = name
        command_class = commands_class
        connect_dsn = f"sqlite+{name}://mock"

        async def create_commands(self):
            return commands_class(FakeAsyncConnection(seeded_mini_db()))

    report = await run_core_async(_Harness())
    named = next(result for result in report.results if result.case_id == "registration.dsn-connect")
    assert named.passed, named.message


# ------------------------------------------------------------------ adapters that skip the driver


class _NoDriverWorkCommands(MockSyncConformanceCommands):
    """Returns plausible results without ever reaching the driver."""

    def query(self, *args, **kwargs):
        return []

    def execute(self, *args, **kwargs):
        return 0


class _NoDriverWorkAsyncCommands(MockAsyncConformanceCommands):
    async def query_async(self, *args, **kwargs):
        return []

    async def execute_async(self, *args, **kwargs):
        return 0


def test_adapter_that_never_reaches_the_driver_fails_the_binding_cases(isolated_registry):
    """Binding cases assert on observed driver traffic, so a no-op adapter cannot pass them."""
    name = "conformance-mock-no-driver-work"
    _register_mock_sync(name=name, commands=_NoDriverWorkCommands)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _NoDriverWorkCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _NoDriverWorkCommands(FakeSyncConnection(seeded_mini_db()))

    report = run_core_sync(_Harness())
    failures = {failure.case_id: failure.message for failure in report.failures}
    for case_id in ("params.repeated-placeholders-binding", "execute.nested-list-single-value"):
        assert case_id in failures, sorted(failures)
        assert "execute must reach the driver" in failures[case_id]


@pytest.mark.asyncio
async def test_async_adapter_that_never_reaches_the_driver_fails_the_binding_cases(isolated_registry):
    name = "conformance-mock-no-driver-work-async"
    _register_mock_async(name=name, async_commands=_NoDriverWorkAsyncCommands)

    class _Harness(MockAsyncConformanceHarness):
        adapter_name = name
        command_class = _NoDriverWorkAsyncCommands
        connect_dsn = f"sqlite+{name}://mock"

        async def create_commands(self):
            return _NoDriverWorkAsyncCommands(FakeAsyncConnection(seeded_mini_db()))

    report = await run_core_async(_Harness())
    failures = {failure.case_id: failure.message for failure in report.failures}
    for case_id in ("params.repeated-placeholders-binding", "execute.nested-list-single-value"):
        assert case_id in failures, sorted(failures)
        assert "execute must reach the driver" in failures[case_id]


# ------------------------------------------------------------------ capability declaration honesty


class _NonEnumMemberCommands(MockSyncConformanceCommands):
    capabilities = frozenset({"transactions"})  # type: ignore[assignment]  # right container, wrong members


class _NonEnumMemberAsyncCommands(MockAsyncConformanceCommands):
    capabilities = frozenset({"transactions"})  # type: ignore[assignment]


class _InvalidCapabilityAsyncCommands(MockAsyncConformanceCommands):
    capabilities = {"transactions"}  # type: ignore[assignment]  # not even a frozenset


def test_non_enum_capability_members_fail_both_declaration_cases(isolated_registry):
    """register_adapter() rejects this declaration outright, so the conformance cases are
    the backstop for a class that was never registered through the public path."""

    class _Harness(MockSyncConformanceHarness):
        adapter_name = "conformance-mock-non-enum-caps"
        command_class = _NonEnumMemberCommands

        def create_commands(self):
            return _NonEnumMemberCommands(FakeSyncConnection(seeded_mini_db()))

    report = run_core_sync(_Harness())
    failures = {failure.case_id: failure.message for failure in report.failures}
    assert "non-AdapterCapability member" in failures["capabilities.declaration-valid"]
    assert "non-enum member" in failures["capabilities.declared-profile-populated"]


@pytest.mark.asyncio
async def test_async_non_enum_capability_members_fail_both_declaration_cases(isolated_registry):

    class _Harness(MockAsyncConformanceHarness):
        adapter_name = "conformance-mock-non-enum-caps-async"
        command_class = _NonEnumMemberAsyncCommands

        async def create_commands(self):
            return _NonEnumMemberAsyncCommands(FakeAsyncConnection(seeded_mini_db()))

    report = await run_core_async(_Harness())
    failures = {failure.case_id: failure.message for failure in report.failures}
    assert "non-AdapterCapability member" in failures["capabilities.declaration-valid"]
    assert "non-enum member" in failures["capabilities.declared-profile-populated"]


@pytest.mark.asyncio
async def test_async_invalid_capability_declaration_fails_clearly(isolated_registry):
    """A non-frozenset declaration fails loudly and is ignored by the option probes."""

    class _Harness(MockAsyncConformanceHarness):
        adapter_name = "conformance-mock-invalid-caps-async"
        command_class = _InvalidCapabilityAsyncCommands

        async def create_commands(self):
            return _InvalidCapabilityAsyncCommands(FakeAsyncConnection(seeded_mini_db()))

    report = await run_core_async(_Harness())
    failures = {failure.case_id: failure.message for failure in report.failures}
    assert "frozenset" in failures["capabilities.declaration-valid"]
    assert "invalid declaration" in failures["capabilities.declared-profile-populated"]
    # an unreadable declaration waives nothing: the option probes still ran and passed
    assert "options.unsupported-raises" not in failures
    assert "options.unsupported-before-driver-work" not in failures


# ------------------------------------------------------------------ a shipped capability waives its probe


class _DeclaredTimeoutCommands(MockSyncConformanceCommands):
    capabilities = frozenset({AdapterCapability.COMMAND_TIMEOUT})


class _DeclaredTimeoutAsyncCommands(MockAsyncConformanceCommands):
    capabilities = frozenset({AdapterCapability.COMMAND_TIMEOUT})


class _DeclaredTransactionsAsyncCommands(MockAsyncConformanceCommands):
    capabilities = frozenset({AdapterCapability.TRANSACTIONS})


class _DeclaredRawReaderAsyncCommands(MockAsyncConformanceCommands):
    capabilities = frozenset({AdapterCapability.RAW_READER})


def _profile_for(capability, *, sync=True, async_=True):
    return ConformanceProfile(
        profile_id=capability.value,
        capability=capability,
        sync_cases=(SyncCase(f"{capability.value}.smoke", "d", "instrumented", _noop_case),) if sync else (),
        async_cases=(AsyncCase(f"{capability.value}.smoke", "d", "instrumented", _async_noop_case),) if async_ else (),
    )


async def _async_noop_case(ctx):
    return None


def test_a_shipped_capability_profile_waives_its_option_probe(isolated_registry, monkeypatch):
    """Once a capability ships a real production profile, its option probe is waived —
    the adapter is expected to implement the option rather than reject it."""
    from pydapper.testing.adapter_conformance import _cases_sync

    name = "conformance-mock-shipped-timeout"
    _register_mock_sync(name=name, commands=_DeclaredTimeoutCommands)
    shipped = {AdapterCapability.COMMAND_TIMEOUT: _profile_for(AdapterCapability.COMMAND_TIMEOUT)}
    monkeypatch.setattr(_cases_sync, "capability_profiles", lambda: shipped)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _DeclaredTimeoutCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _DeclaredTimeoutCommands(FakeSyncConnection(seeded_mini_db()))

    report = run_core_sync(_Harness())
    assert report.passed, [(f.case_id, f.message) for f in report.failures]


@pytest.mark.asyncio
async def test_async_shipped_capability_profile_waives_its_option_probe(isolated_registry, monkeypatch):
    from pydapper.testing.adapter_conformance import _cases_async

    name = "conformance-mock-shipped-timeout-async"
    _register_mock_async(name=name, async_commands=_DeclaredTimeoutAsyncCommands)
    shipped = {AdapterCapability.COMMAND_TIMEOUT: _profile_for(AdapterCapability.COMMAND_TIMEOUT)}
    monkeypatch.setattr(_cases_async, "capability_profiles", lambda: shipped)

    class _Harness(MockAsyncConformanceHarness):
        adapter_name = name
        command_class = _DeclaredTimeoutAsyncCommands
        connect_dsn = f"sqlite+{name}://mock"

        async def create_commands(self):
            return _DeclaredTimeoutAsyncCommands(FakeAsyncConnection(seeded_mini_db()))

    report = await run_core_async(_Harness())
    assert report.passed, [(f.case_id, f.message) for f in report.failures]


def test_capability_profile_without_sync_cases_fails_the_sync_declaration(isolated_registry, monkeypatch):
    """A capability covered only in the other mode does not cover this one.

    Uses RAW_READER so the runner's real production catalog plans no capability cases
    against the fake connection — TRANSACTIONS now ships real sync cases.
    """
    from pydapper.testing.adapter_conformance import _cases_sync

    name = "conformance-mock-async-only-profile"
    _register_mock_sync(name=name, commands=_DeclaredRawReaderCommands)
    catalog = {AdapterCapability.RAW_READER: _profile_for(AdapterCapability.RAW_READER, sync=False)}
    monkeypatch.setattr(_cases_sync, "capability_profiles", lambda: catalog)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _DeclaredRawReaderCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _DeclaredRawReaderCommands(FakeSyncConnection(seeded_mini_db()))

    report = run_core_sync(_Harness())
    failures = {failure.case_id: failure.message for failure in report.failures}
    assert "no sync conformance cases" in failures["capabilities.declared-profile-populated"]


@pytest.mark.asyncio
async def test_capability_profile_without_async_cases_fails_the_async_declaration(isolated_registry, monkeypatch):
    from pydapper.testing.adapter_conformance import _cases_async

    name = "conformance-mock-sync-only-profile"
    _register_mock_async(name=name, async_commands=_DeclaredRawReaderAsyncCommands)
    catalog = {AdapterCapability.RAW_READER: _profile_for(AdapterCapability.RAW_READER, async_=False)}
    monkeypatch.setattr(_cases_async, "capability_profiles", lambda: catalog)

    class _Harness(MockAsyncConformanceHarness):
        adapter_name = name
        command_class = _DeclaredRawReaderAsyncCommands
        connect_dsn = f"sqlite+{name}://mock"

        async def create_commands(self):
            return _DeclaredRawReaderAsyncCommands(FakeAsyncConnection(seeded_mini_db()))

    report = await run_core_async(_Harness())
    failures = {failure.case_id: failure.message for failure in report.failures}
    assert "no async conformance cases" in failures["capabilities.declared-profile-populated"]


@pytest.mark.asyncio
async def test_async_empty_string_fallback_value_round_trips(isolated_registry):
    """supports_empty_strings=False swaps in the documented fallback label in async mode too."""
    _register_mock_async()

    class _Harness(MockAsyncConformanceHarness):
        supports_empty_strings = False

        async def create_commands(self):
            return MockAsyncConformanceCommands(FakeAsyncConnection(seeded_mini_db(supports_empty_strings=False)))

    report = await run_core_async(_Harness())
    assert report.passed, [(f.case_id, f.message) for f in report.failures]


# ------------------------------------------------------------------ runner shutdown and teardown paths


def test_sync_runner_propagates_base_exceptions_after_releasing_resources(isolated_registry):
    """A KeyboardInterrupt/shutdown is never recorded as a failed case, and the active
    case's resources are still released before it propagates."""
    name = "conformance-mock-sync-shutdown"
    _register_mock_sync(name=name, commands=_DeclaredTransactionsCommands)
    torn_down = []

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _DeclaredTransactionsCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _DeclaredTransactionsCommands(FakeSyncConnection(seeded_mini_db()))

        def teardown_commands(self, commands):
            torn_down.append(commands)
            super().teardown_commands(commands)

    def _shutdown_case(ctx):
        ctx.create_commands()
        raise KeyboardInterrupt("shutdown")

    profile = ConformanceProfile(
        profile_id="transactions",
        capability=AdapterCapability.TRANSACTIONS,
        sync_cases=(SyncCase("transactions.shutdown", "d", "instrumented", _shutdown_case),),
    )
    with pytest.raises(KeyboardInterrupt):
        run_core_sync(_Harness(), capability_catalog={AdapterCapability.TRANSACTIONS: profile})
    assert torn_down, "the interrupted case's live resources must still be released"


def test_teardown_reports_the_first_error_across_several_commands(isolated_registry):
    """When one case builds several commands and every teardown fails, the first failure
    is the reported one and the remaining commands are still torn down."""
    name = "conformance-mock-multi-teardown"
    _register_mock_sync(name=name, commands=_DeclaredTransactionsCommands)
    attempts = []

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _DeclaredTransactionsCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _DeclaredTransactionsCommands(FakeSyncConnection(seeded_mini_db()))

        def teardown_commands(self, commands):
            attempts.append(commands)
            raise RuntimeError(f"teardown boom {len(attempts)}")

    created = []

    def _two_commands_case(ctx):
        created.append(ctx.create_commands())
        created.append(ctx.create_commands())

    profile = ConformanceProfile(
        profile_id="transactions",
        capability=AdapterCapability.TRANSACTIONS,
        sync_cases=(SyncCase("transactions.two-commands", "d", "instrumented", _two_commands_case),),
    )
    report = run_core_sync(_Harness(), capability_catalog={AdapterCapability.TRANSACTIONS: profile})
    named = next(result for result in report.results if result.case_id == "transactions.two-commands")
    assert not named.passed
    assert len(created) == 2
    torn_down = [command for command in created if any(command is attempt for attempt in attempts)]
    assert len(torn_down) == 2, "every created command must be torn down even after the first failure"
    assert str(named.cause) == f"teardown boom {attempts.index(created[0]) + 1}", "the first failure is reported"


@pytest.mark.asyncio
async def test_async_teardown_failure_fails_a_passing_case(isolated_registry):
    _register_mock_async()

    class _FailingTeardownHarness(MockAsyncConformanceHarness):
        async def teardown_commands(self, commands):
            raise RuntimeError("async teardown boom")

    report = await run_core_async(_FailingTeardownHarness())
    named = next(result for result in report.results if result.case_id == "params.params-keyword")
    assert not named.passed
    assert isinstance(named.cause, RuntimeError)
    assert "teardown" in named.message


def test_capability_catalog_value_must_be_a_profile():
    with pytest.raises(ProfileDefinitionError) as exc_info:
        validate_capability_catalog({AdapterCapability.TRANSACTIONS: object()})  # type: ignore[dict-item]
    assert "must be a ConformanceProfile" in str(exc_info.value)


@pytest.mark.asyncio
async def test_async_declared_capability_without_profile_fails_clearly(isolated_registry):
    """The async twin of the sync declaration-honesty check, against the real catalog."""
    name = "conformance-mock-declared-raw-async"
    _register_mock_async(name=name, async_commands=_DeclaredRawReaderAsyncCommands)

    class _Harness(MockAsyncConformanceHarness):
        adapter_name = name
        command_class = _DeclaredRawReaderAsyncCommands
        connect_dsn = f"sqlite+{name}://mock"

        async def create_commands(self):
            return _DeclaredRawReaderAsyncCommands(FakeAsyncConnection(seeded_mini_db()))

    report = await run_core_async(_Harness())
    failed_ids = [failure.case_id for failure in report.failures]
    assert failed_ids == ["capabilities.declared-profile-populated"], failed_ids
    assert "has no production conformance profile" in report.failures[0].message
    assert report.failures[0].profile_id == CORE_ASYNC


@pytest.mark.asyncio
async def test_async_transactions_declaration_requires_async_cases(isolated_registry):
    """Pins the #464 sequencing contract: the production transactions profile is
    sync-only, so an async class may not declare TRANSACTIONS before the async
    transaction APIs land with their async case inventory."""
    name = "conformance-mock-declared-txn-async"
    _register_mock_async(name=name, async_commands=_DeclaredTransactionsAsyncCommands)

    class _Harness(MockAsyncConformanceHarness):
        adapter_name = name
        command_class = _DeclaredTransactionsAsyncCommands
        connect_dsn = f"sqlite+{name}://mock"

        async def create_commands(self):
            return _DeclaredTransactionsAsyncCommands(FakeAsyncConnection(seeded_mini_db()))

    report = await run_core_async(_Harness())
    failed_ids = [failure.case_id for failure in report.failures]
    assert failed_ids == ["capabilities.declared-profile-populated"], failed_ids
    assert "has no async conformance cases" in report.failures[0].message
    assert report.failures[0].profile_id == CORE_ASYNC


@pytest.mark.asyncio
async def test_async_relaxed_rowcounts_still_require_integer_results(isolated_registry):
    """strict_rowcounts=False relaxes only exact-count equality; the cases still run."""
    _register_mock_async()

    class _Harness(MockAsyncConformanceHarness):
        strict_rowcounts = False

    report = await run_core_async(_Harness())
    assert report.passed, [(f.case_id, f.message) for f in report.failures]


@pytest.mark.asyncio
async def test_async_teardown_reports_the_first_error_across_several_commands(isolated_registry):
    name = "conformance-mock-multi-teardown-async"
    _register_mock_async(name=name, async_commands=_DeclaredTransactionsAsyncCommands)
    attempts = []

    class _Harness(MockAsyncConformanceHarness):
        adapter_name = name
        command_class = _DeclaredTransactionsAsyncCommands
        connect_dsn = f"sqlite+{name}://mock"

        async def create_commands(self):
            return _DeclaredTransactionsAsyncCommands(FakeAsyncConnection(seeded_mini_db()))

        async def teardown_commands(self, commands):
            attempts.append(commands)
            raise RuntimeError(f"async teardown boom {len(attempts)}")

    created = []

    async def _two_commands_case(ctx):
        created.append(await ctx.create_commands())
        created.append(await ctx.create_commands())

    profile = ConformanceProfile(
        profile_id="transactions",
        capability=AdapterCapability.TRANSACTIONS,
        async_cases=(AsyncCase("transactions.two-commands", "d", "instrumented", _two_commands_case),),
    )
    report = await run_core_async(_Harness(), capability_catalog={AdapterCapability.TRANSACTIONS: profile})
    named = next(result for result in report.results if result.case_id == "transactions.two-commands")
    assert not named.passed
    assert len(created) == 2
    torn_down = [command for command in created if any(command is attempt for attempt in attempts)]
    assert len(torn_down) == 2, "every created command must be torn down even after the first failure"


# ------------------------------------------------------------------ sync/async inventory parity

#: The only intentional divergence between the two core inventories: the unbuffered
#: cleanup case is named after the generator-teardown API each mode actually exposes.
#: Every other case id must exist in both modes so a fix can never land in one mode
#: only. Extend these sets in the same change that adds a genuinely mode-specific case.
DOCUMENTED_SYNC_ONLY_CASE_IDS = frozenset({"lifecycle.unbuffered-explicit-close"})
DOCUMENTED_ASYNC_ONLY_CASE_IDS = frozenset({"lifecycle.unbuffered-explicit-aclose"})


def test_core_sync_and_async_case_inventories_stay_in_parity():
    sync_ids = {case.case_id for case in core_sync_profile().sync_cases}
    async_ids = {case.case_id for case in core_async_profile().async_cases}

    sync_only = sync_ids - async_ids
    async_only = async_ids - sync_ids

    assert (sync_only, async_only) == (DOCUMENTED_SYNC_ONLY_CASE_IDS, DOCUMENTED_ASYNC_ONLY_CASE_IDS), (
        "the core-sync and core-async case inventories drifted; every case id must exist in "
        "both modes apart from the documented unbuffered-close pair.\n"
        f"  sync-only, missing an async twin: {sorted(sync_only - DOCUMENTED_SYNC_ONLY_CASE_IDS)}\n"
        f"  async-only, missing a sync twin: {sorted(async_only - DOCUMENTED_ASYNC_ONLY_CASE_IDS)}\n"
        f"  documented sync-only ids no longer sync-only: {sorted(DOCUMENTED_SYNC_ONLY_CASE_IDS - sync_only)}\n"
        f"  documented async-only ids no longer async-only: {sorted(DOCUMENTED_ASYNC_ONLY_CASE_IDS - async_only)}"
    )


# ------------------------------------------------------------------ case_ids filtering

#: Two real ids present in both core inventories, used to prove a narrow debug run.
FILTER_CASE_IDS = ("params.params-keyword", "scalar.null-returns-none")


def test_case_ids_runs_only_the_requested_sync_cases(isolated_registry, tmp_path):
    """A filtered run executes exactly the named cases, in declared order, and says so."""
    declared = [case.case_id for case in core_sync_profile().sync_cases]
    expected = [case_id for case_id in declared if case_id in FILTER_CASE_IDS]

    # duplicates in the request are de-duplicated, never run twice
    report = run_core_sync(Sqlite3ConformanceHarness(tmp_path), case_ids=[*FILTER_CASE_IDS, FILTER_CASE_IDS[0]])

    assert [result.case_id for result in report.results] == expected
    assert report.passed, [(f.case_id, f.message) for f in report.failures]
    assert report.covers_full_inventory is False, "a filtered run must never claim full coverage"
    assert report.profile_id == CORE_SYNC


@pytest.mark.asyncio
async def test_case_ids_runs_only_the_requested_async_cases(isolated_registry):
    _register_mock_async()
    declared = [case.case_id for case in core_async_profile().async_cases]
    expected = [case_id for case_id in declared if case_id in FILTER_CASE_IDS]

    report = await run_core_async(MockAsyncConformanceHarness(), case_ids=list(FILTER_CASE_IDS))

    assert [result.case_id for result in report.results] == expected
    assert report.passed, [(f.case_id, f.message) for f in report.failures]
    assert report.covers_full_inventory is False
    assert report.profile_id == CORE_ASYNC


def test_unfiltered_and_fully_named_sync_runs_both_cover_the_inventory(isolated_registry):
    """``case_ids=None`` and a selection naming every planned case are both complete."""
    _register_mock_sync()
    every_id = [case.case_id for case in core_sync_profile().sync_cases]

    unfiltered = run_core_sync(MockSyncConformanceHarness())
    fully_named = run_core_sync(MockSyncConformanceHarness(), case_ids=every_id)

    assert unfiltered.covers_full_inventory is True
    assert fully_named.covers_full_inventory is True, "naming every planned case is still full coverage"
    assert [result.case_id for result in fully_named.results] == [result.case_id for result in unfiltered.results]


@pytest.mark.asyncio
async def test_unfiltered_and_fully_named_async_runs_both_cover_the_inventory(isolated_registry):
    _register_mock_async()
    every_id = [case.case_id for case in core_async_profile().async_cases]

    unfiltered = await run_core_async(MockAsyncConformanceHarness())
    fully_named = await run_core_async(MockAsyncConformanceHarness(), case_ids=every_id)

    assert unfiltered.covers_full_inventory is True
    assert fully_named.covers_full_inventory is True
    assert [result.case_id for result in fully_named.results] == [result.case_id for result in unfiltered.results]


def test_case_ids_can_select_a_declared_capability_profile_case(isolated_registry):
    """Filtering is applied after planning, so a capability profile's case id selects."""
    name = "conformance-mock-filter-txn"
    _register_mock_sync(name=name, commands=_DeclaredTransactionsCommands)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _DeclaredTransactionsCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _DeclaredTransactionsCommands(FakeSyncConnection(seeded_mini_db()))

    ran = []

    def _txn_case(ctx):
        ran.append(ctx.case_id)

    profile = ConformanceProfile(
        profile_id="transactions",
        capability=AdapterCapability.TRANSACTIONS,
        sync_cases=(SyncCase("transactions.smoke", "synthetic", "instrumented", _txn_case),),
    )
    report = run_core_sync(
        _Harness(),
        capability_catalog={AdapterCapability.TRANSACTIONS: profile},
        case_ids=["transactions.smoke"],
    )

    assert ran == ["transactions.smoke"]
    assert [(result.profile_id, result.case_id) for result in report.results] == [
        ("transactions", "transactions.smoke")
    ]
    assert report.covers_full_inventory is False


def test_case_ids_rejects_unknown_ids_before_running_anything(isolated_registry):
    """A typo raises immediately and names the unknown ids; nothing runs."""
    _register_mock_sync()
    created = []

    class _Harness(MockSyncConformanceHarness):
        def create_commands(self):
            created.append(1)
            return super().create_commands()

    with pytest.raises(CaseSelectionError) as exc_info:
        run_core_sync(_Harness(), case_ids=["params.params-keyword", "params.params-keyord", "nope"])

    error = exc_info.value
    assert error.unknown_case_ids == ("params.params-keyord", "nope")
    assert error.requested_case_ids == ("params.params-keyword", "params.params-keyord", "nope")
    assert error.profile_id == CORE_SYNC
    assert "params.params-keyord" in str(error) and "nope" in str(error)
    assert created == [], "an invalid selection must raise before any case runs"


@pytest.mark.asyncio
async def test_async_case_ids_rejects_unknown_ids(isolated_registry):
    _register_mock_async()

    with pytest.raises(CaseSelectionError) as exc_info:
        await run_core_async(MockAsyncConformanceHarness(), case_ids=["lifecycle.unbuffered-explicit-close"])

    error = exc_info.value
    assert error.unknown_case_ids == ("lifecycle.unbuffered-explicit-close",), "sync-only ids are unknown here"
    assert error.profile_id == CORE_ASYNC


def test_case_ids_empty_selection_is_an_error(isolated_registry):
    _register_mock_sync()

    with pytest.raises(CaseSelectionError) as exc_info:
        run_core_sync(MockSyncConformanceHarness(), case_ids=())

    error = exc_info.value
    assert error.requested_case_ids == ()
    assert error.unknown_case_ids == ()
    assert "empty selection is not a conformance run" in str(error)


@pytest.mark.asyncio
async def test_async_case_ids_empty_selection_is_an_error(isolated_registry):
    _register_mock_async()

    with pytest.raises(CaseSelectionError) as exc_info:
        await run_core_async(MockAsyncConformanceHarness(), case_ids=set())

    assert exc_info.value.profile_id == CORE_ASYNC
    assert "empty selection is not a conformance run" in str(exc_info.value)


def test_case_ids_rejects_a_bare_string(isolated_registry):
    """A single string is a collection of characters; reject it instead of reporting 20 typos."""
    _register_mock_sync()

    with pytest.raises(TypeError) as exc_info:
        run_core_sync(MockSyncConformanceHarness(), case_ids="params.params-keyword")

    assert "not a single string" in str(exc_info.value)


@pytest.mark.asyncio
async def test_async_case_ids_rejects_a_bare_string(isolated_registry):
    _register_mock_async()

    with pytest.raises(TypeError) as exc_info:
        await run_core_async(MockAsyncConformanceHarness(), case_ids="params.params-keyword")

    assert "not a single string" in str(exc_info.value)


def test_conformance_failure_error_marks_a_partial_run():
    """A pasted traceback from a filtered run cannot be mistaken for a full run."""
    failing = CaseResult(CORE_SYNC, "scalar.value", False, message="boom")
    partial = ConformanceReport(
        profile_id=CORE_SYNC,
        adapter_name="mock",
        command_class_name="Mock",
        results=(failing,),
        covers_full_inventory=False,
    )
    full = dataclasses.replace(partial, covers_full_inventory=True)

    with pytest.raises(ConformanceFailureError) as exc_info:
        partial.raise_for_failures()
    assert "PARTIAL RUN" in str(exc_info.value)
    assert "covered only 1 planned case(s)" in str(exc_info.value)
    assert exc_info.value.report.covers_full_inventory is False

    with pytest.raises(ConformanceFailureError) as full_info:
        full.raise_for_failures()
    assert "PARTIAL RUN" not in str(full_info.value)


def test_raise_for_failures_ignores_completeness(isolated_registry, tmp_path):
    """``raise_for_failures`` is about failures only; completeness is a separate axis."""
    report = run_core_sync(Sqlite3ConformanceHarness(tmp_path), case_ids=[FILTER_CASE_IDS[0]])

    assert report.passed
    assert report.covers_full_inventory is False
    assert report.raise_for_failures() is None, "a passing filtered run must not raise"


# ------------------------------------------------------------------ harness setup failures


class _SeedingFailure(RuntimeError):
    """Stands in for a driver error raised while the harness seeds the canonical dataset."""


def test_sync_harness_setup_failure_is_attributed_to_the_harness(isolated_registry):
    """A harness that cannot seed reports a harness failure, not adapter misbehavior.

    This is the BigQuery seeding regression in miniature: one broken ``create_commands()``
    used to surface as dozens of identical "unexpected ProgrammingError" case failures
    indistinguishable from a genuinely broken adapter.
    """
    _register_mock_sync()
    boom = _SeedingFailure("Encountered parameter None with only None values")

    class _BrokenSeedHarness(MockSyncConformanceHarness):
        def create_commands(self):
            raise boom

    report = run_core_sync(_BrokenSeedHarness())
    named = next(result for result in report.results if result.case_id == "params.params-keyword")

    assert not named.passed
    assert named.harness_setup_failed is True
    assert named.cause is boom, "the original exception object must be preserved unchanged"
    assert named.missing_field is None, "a raising factory is not a missing harness field"
    assert "harness setup failed" in named.message
    assert "create_commands()" in named.message
    assert "not adapter behavior" in named.message
    assert str(boom) in named.message, "the underlying driver error is still visible"
    assert "harness_setup_failed=True" in repr(named), "the flag must be visible in a printed result"
    assert report.harness_setup_failed is True
    assert len([failure for failure in report.failures if failure.harness_setup_failed]) > 1


@pytest.mark.asyncio
async def test_async_harness_setup_failure_is_attributed_to_the_harness(isolated_registry):
    _register_mock_async()
    boom = _SeedingFailure("async seeding boom")

    class _BrokenSeedHarness(MockAsyncConformanceHarness):
        async def create_commands(self):
            raise boom

    report = await run_core_async(_BrokenSeedHarness())
    named = next(result for result in report.results if result.case_id == "params.params-keyword")

    assert not named.passed
    assert named.harness_setup_failed is True
    assert named.cause is boom
    assert "harness setup failed" in named.message and "create_commands()" in named.message
    assert f"{CORE_ASYNC!r}/'params.params-keyword'" in named.message
    assert report.harness_setup_failed is True


def test_missing_create_commands_is_not_reported_as_a_setup_failure(isolated_registry):
    """A missing override keeps its own structured path and is never double-wrapped."""

    class _NoFactoryHarness(SyncAdapterHarness):
        adapter_name = MOCK_SYNC_ADAPTER_NAME
        command_class = MockSyncConformanceCommands
        connect_dsn = MockSyncConformanceHarness.connect_dsn

    _register_mock_sync()
    report = run_core_sync(_NoFactoryHarness())
    named = next(failure for failure in report.failures if failure.missing_field == "create_commands")

    assert named.harness_setup_failed is False
    assert isinstance(named.cause, HarnessDefinitionError)
    assert "harness setup failed" not in named.message
    assert report.harness_setup_failed is False, "a missing field is a definition error, not a setup failure"


def test_adapter_failures_are_not_relabelled_as_setup_failures(isolated_registry):
    """A genuine behavioral failure keeps its exact shape and never claims setup broke."""
    name = "conformance-mock-broken-rows-not-setup"
    _register_mock_sync(name=name, commands=_BrokenRowMappingCommands)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _BrokenRowMappingCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _BrokenRowMappingCommands(FakeSyncConnection(seeded_mini_db()))

    report = run_core_sync(_Harness())
    named = next(result for result in report.results if result.case_id == "rows.query-buffered")

    assert not named.passed
    assert named.harness_setup_failed is False
    assert "harness setup failed" not in named.message
    assert report.harness_setup_failed is False


def test_setup_failure_survives_a_teardown_failure(isolated_registry):
    """A later setup failure keeps its attribution when an earlier command's teardown fails."""
    name = "conformance-mock-setup-then-teardown-boom"
    _register_mock_sync(name=name, commands=_DeclaredTransactionsCommands)
    calls = []

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _DeclaredTransactionsCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            calls.append(1)
            if len(calls) > 1:
                raise _SeedingFailure("second seed boom")
            return _DeclaredTransactionsCommands(FakeSyncConnection(seeded_mini_db()))

        def teardown_commands(self, commands):
            raise RuntimeError("teardown boom")

    def _two_commands_case(ctx):
        ctx.create_commands()
        ctx.create_commands()

    profile = ConformanceProfile(
        profile_id="transactions",
        capability=AdapterCapability.TRANSACTIONS,
        sync_cases=(SyncCase("transactions.two-commands", "d", "instrumented", _two_commands_case),),
    )
    report = run_core_sync(
        _Harness(),
        capability_catalog={AdapterCapability.TRANSACTIONS: profile},
        case_ids=["transactions.two-commands"],
    )
    named = next(result for result in report.results if result.case_id == "transactions.two-commands")

    assert named.harness_setup_failed is True, "merging a teardown failure must not lose the attribution"
    assert isinstance(named.cause, _SeedingFailure)
    assert isinstance(named.cleanup_error, RuntimeError)
    assert report.harness_setup_failed is True


def test_conformance_failure_error_flags_a_harness_setup_run(isolated_registry):
    """The raised summary — what CI actually prints — says the harness never got off the ground."""
    _register_mock_sync()

    class _BrokenSeedHarness(MockSyncConformanceHarness):
        def create_commands(self):
            raise _SeedingFailure("seed boom")

    report = run_core_sync(_BrokenSeedHarness())
    with pytest.raises(ConformanceFailureError) as exc_info:
        report.raise_for_failures()

    summary = str(exc_info.value)
    assert "HARNESS SETUP FAILED" in summary
    assert f"{len(report.failures)} of {len(report.failures)} failure(s)" in summary
    assert "fix the harness first" in summary


def test_conformance_failure_error_omits_the_setup_banner_for_ordinary_failures():
    """Every other failure kind keeps the pre-existing summary byte for byte."""
    failing = CaseResult(CORE_SYNC, "scalar.value", False, message="boom")
    report = ConformanceReport(
        profile_id=CORE_SYNC,
        adapter_name="mock",
        command_class_name="Mock",
        results=(failing,),
    )

    with pytest.raises(ConformanceFailureError) as exc_info:
        report.raise_for_failures()

    assert "HARNESS SETUP" not in str(exc_info.value)
    assert str(exc_info.value) == (
        "1 conformance case(s) failed for profile 'core-sync' ('mock' / Mock); first failure: 'scalar.value': boom"
    )
    assert report.harness_setup_failed is False
