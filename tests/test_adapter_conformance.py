"""Framework self-tests for the reusable adapter conformance suite.

Pytest is allowed here (repository tests), never in the shipped helper. Coverage in
this module is service-free: mock harnesses over a pure-Python fake driver, a real
in-memory SQLite harness, instrumented concrete first-party classes, negative
broken-adapter tests, packaging/drift invariants, and import hygiene.
"""

import dataclasses
import importlib.metadata
import re
import subprocess
import sys
import tarfile
import textwrap
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest

import pydapper
from pydapper import _adapter_discovery
from pydapper import main
from pydapper._context import _AwaitableAsyncContextManager as _RealAwaitableAsyncContextManager
from pydapper.bigquery import GoogleBigqueryClientCommands
from pydapper.capabilities import AdapterCapability
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
from pydapper.testing.adapter_conformance import CaseResult
from pydapper.testing.adapter_conformance import ConformanceFailureError
from pydapper.testing.adapter_conformance import ConformanceProfile
from pydapper.testing.adapter_conformance import HarnessDefinitionError
from pydapper.testing.adapter_conformance import ProfileDefinitionError
from pydapper.testing.adapter_conformance import SyncAdapterHarness
from pydapper.testing.adapter_conformance import SyncCase
from pydapper.testing.adapter_conformance import capability_profiles
from pydapper.testing.adapter_conformance import core_async_profile
from pydapper.testing.adapter_conformance import core_sync_profile
from pydapper.testing.adapter_conformance import run_core_async
from pydapper.testing.adapter_conformance import run_core_sync
from pydapper.testing.adapter_conformance._instrumentation import CursorScript
from pydapper.testing.adapter_conformance._instrumentation import RecordingAsyncConnection
from pydapper.testing.adapter_conformance._instrumentation import RecordingConnection
from pydapper.testing.adapter_conformance._instrumentation import SynchronousCursorRecordingAsyncConnection
from pydapper.testing.adapter_conformance._profiles import validate_capability_catalog
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
from tests.conformance_support import seeded_mini_db

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parent.parent
GROUP = "pydapper.adapters"


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


def test_declared_capability_without_profile_fails_clearly(isolated_registry):
    name = "conformance-mock-declared-txn"
    _register_mock_sync(name=name, commands=_DeclaredTransactionsCommands)

    class _Harness(MockSyncConformanceHarness):
        adapter_name = name
        command_class = _DeclaredTransactionsCommands
        connect_dsn = f"sqlite+{name}://mock"

        def create_commands(self):
            return _DeclaredTransactionsCommands(FakeSyncConnection(seeded_mini_db()))

    report = run_core_sync(_Harness())
    failed_ids = [failure.case_id for failure in report.failures]
    assert failed_ids == ["capabilities.declared-profile-populated"], failed_ids
    named = report.failures[0]
    assert "transactions" in named.message
    assert named.profile_id == CORE_SYNC


def test_synthetic_capability_profile_runs_but_cannot_cover_a_declaration(isolated_registry):
    """A test-local synthetic profile runs its cases, but only the production catalog
    can satisfy the declared-capability honesty check — injection is not a bypass."""
    name = "conformance-mock-synth-txn"
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
        commands = ctx.command_class(FakeSyncConnection())
        ctx.check(commands.supports(AdapterCapability.TRANSACTIONS), "declared capability must be supported")

    synthetic = ConformanceProfile(
        profile_id="transactions",
        capability=AdapterCapability.TRANSACTIONS,
        sync_cases=(SyncCase("transactions.smoke", "synthetic transactions case", "instrumented", _txn_case),),
    )
    report = run_core_sync(_Harness(), capability_catalog={AdapterCapability.TRANSACTIONS: synthetic})
    assert ran == ["transactions.smoke"], "the injected profile's cases must actually run"
    synthetic_results = [result for result in report.results if result.profile_id == "transactions"]
    assert [result.case_id for result in synthetic_results] == ["transactions.smoke"]
    assert synthetic_results[0].passed
    # the declaration honesty case still fails: the production catalog has no
    # transactions profile, and an injected catalog can never make one appear covered
    failed_ids = [failure.case_id for failure in report.failures]
    assert failed_ids == ["capabilities.declared-profile-populated"], failed_ids
    assert capability_profiles() == {}, "the production catalog must stay empty until a capability ships"


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


def test_production_capability_catalog_is_empty_and_immutable():
    catalog = capability_profiles()
    assert dict(catalog) == {}
    with pytest.raises(TypeError):
        catalog[AdapterCapability.TRANSACTIONS] = None  # type: ignore[index]


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
