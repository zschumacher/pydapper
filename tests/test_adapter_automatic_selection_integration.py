"""Integration coverage for automatic (predicate-based) adapter selection.

Exercises the real public entry points -- ``using(connection)`` and
``using_async(connection)`` without ``adapter=`` -- against the real discovery
catalog, the real ``_load_all_adapter_providers()``, the real
``_resolve_adapter_registration()``, the real ``_load_adapter_provider()``, and
the real predicate-selection logic. Nothing in that composition is ever stubbed;
only installed entry-point metadata is faked, so these tests fail if automatic
selection stops loading installed providers before it evaluates predicates.

Exhaustive discovery, precedence, rollback, hostile-callback, and private
load-all coverage already lives in tests/test_adapter_discovery.py,
tests/test_adapter_loading.py, tests/test_adapter_resolution.py, and
tests/test_adapter_load_all.py and is not duplicated here.
"""

import importlib.metadata
import inspect
import threading
import types

import pytest

import pydapper
import pydapper.main as main
from pydapper import _adapter_discovery
from tests.mocks import MockAsyncCommands
from tests.mocks import MockAsyncConnection
from tests.mocks import MockCommands
from tests.mocks import MockConnection

pytestmark = pytest.mark.core

GROUP = "pydapper.adapters"


class FakeDistribution:
    def __init__(self, name):
        self.name = name


class FakeEntryPoint:
    """Passes real discovery *and* really loads a callback.

    Discovery reads ``name``/``value``/``group``/``dist``; the loader calls
    ``load()``. One fake for both halves keeps these tests on the real catalog +
    loader path instead of a hand-built stand-in.
    """

    def __init__(self, name, *, loaded=None, distribution="acme-adapter", group=GROUP, load_error=None):
        self.name = name
        self.loaded = loaded
        self.value = f"pydapper_should_not_import_{distribution}:register"
        self.group = group
        self.dist = FakeDistribution(distribution)
        self.load_error = load_error
        self.load_calls = 0

    def load(self):
        self.load_calls += 1
        if self.load_error is not None:
            raise self.load_error
        return self.loaded


def never_matches(connection):
    return False


def provider(
    name,
    *,
    distribution="acme-adapter",
    commands=MockCommands,
    async_commands=None,
    predicate=never_matches,
    event_log=None,
):
    """Build an entry point whose callback really registers ``name``, plus its call log.

    When ``event_log`` is supplied the callback and the registered predicate both
    append to it, so a test can assert the observable order of provider loading
    against predicate evaluation rather than merely their totals.
    """
    calls = []
    recorded_predicate = predicate

    if event_log is not None:

        def recorded_predicate(connection, _name=name, _predicate=predicate):
            event_log.append(f"predicate:{_name}")
            return _predicate(connection)

    def register():
        calls.append("called")
        if event_log is not None:
            event_log.append(f"load:{name}")
        pydapper.register_adapter(
            name,
            commands=commands,
            async_commands=async_commands,
            using_connection_predicate=recorded_predicate,
        )

    return FakeEntryPoint(name, loaded=register, distribution=distribution), calls


def broken_provider(name, *, distribution="broken-adapter", error=None):
    error = error if error is not None else ImportError(f"{name} provider is broken")
    return FakeEntryPoint(name, distribution=distribution, load_error=error), error


def matches_connection(target):
    def predicate(connection):
        return connection is target

    return predicate


def exploding_predicate(connection):  # pragma: no cover - must never run
    raise AssertionError("a mode-ineligible or unreached predicate was evaluated")


def assert_nothing_loaded(entry_points):
    for entry_point in entry_points:
        assert entry_point.load_calls == 0


def error_chain_text(error):
    """Join every message in an exception chain so leaks anywhere in it are visible."""
    messages = []
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        messages.append(str(error))
        error = error.__cause__ or error.__context__
    return " ".join(messages)


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    """Give each test a private registry, provider catalog, and loader cache.

    Every piece of process state these tests touch is swapped through
    monkeypatch, so this is a real snapshot/restore rather than a reset: a
    catalog or loader cache the process had already built is put back verbatim
    at teardown instead of being emptied, and nothing here can decide whether a
    name resolves in another module. Plain import no longer registers anything,
    but another test in this process may already have lazily loaded providers
    into the real registry, so the registry is copied rather than assumed
    empty; any such first-party predicates run during automatic selection here
    and match none of the mock connections below.
    """
    registry = main._adapter_registry.copy()
    monkeypatch.setattr(main, "_adapter_registry", registry)
    monkeypatch.setattr(_adapter_discovery, "_catalog", None)
    monkeypatch.setattr(main, "_loaded_provider_registrations", {})
    yield registry


@pytest.fixture
def install_entry_points(monkeypatch):
    """Install fake installed distributions and force a fresh catalog build."""

    def install(entries):
        entries = list(entries)
        monkeypatch.setattr(
            importlib.metadata,
            "entry_points",
            lambda *, group: [ep for ep in entries if ep.group == group],
        )
        _adapter_discovery._reset_provider_catalog_for_tests()
        return entries

    return install


# ---------------------------------------------------------------------------- installed providers participate


def test_using_loads_an_unregistered_sync_provider_and_uses_its_predicate(install_entry_points):
    connection = MockConnection()
    seen = []

    def predicate(candidate):
        seen.append(candidate)
        return candidate is connection

    class AcmeCommands(MockCommands): ...

    entry_point, calls = provider("acmedb", commands=AcmeCommands, predicate=predicate)
    install_entry_points([entry_point])
    assert "acmedb" not in main._adapter_registry

    commands = pydapper.using(connection)

    assert isinstance(commands, AcmeCommands)
    assert calls == ["called"]
    assert entry_point.load_calls == 1
    # the original connection object -- not a copy or a wrapper -- reaches both the predicate that
    # selected the adapter and the command class that was constructed from it
    assert seen == [connection]
    assert commands.connection is connection


def test_using_async_loads_an_unregistered_async_provider_and_uses_its_predicate(install_entry_points):
    connection = MockAsyncConnection()
    seen = []

    def predicate(candidate):
        seen.append(candidate)
        return candidate is connection

    class AcmeCommandsAsync(MockAsyncCommands): ...

    entry_point, calls = provider("acmedb", commands=None, async_commands=AcmeCommandsAsync, predicate=predicate)
    install_entry_points([entry_point])
    assert "acmedb" not in main._adapter_registry

    commands = pydapper.using_async(connection)

    assert isinstance(commands, AcmeCommandsAsync)
    assert calls == ["called"]
    assert entry_point.load_calls == 1
    assert seen == [connection]
    assert commands.connection is connection


def test_every_provider_loads_before_the_first_predicate_runs(install_entry_points):
    # the directly registered name sorts ahead of every provider name, so a registry-only fast
    # path or any interleaving of loading with predicate evaluation would put its predicate
    # before at least one load: entry
    connection = MockConnection()
    events = []

    def direct_predicate(candidate):
        events.append("predicate:aaa-direct")
        return False

    pydapper.register_adapter(
        "aaa-direct",
        commands=MockCommands,
        async_commands=MockAsyncCommands,
        using_connection_predicate=direct_predicate,
    )
    middle, _ = provider("mmm", distribution="mmm-dist", event_log=events)
    last, _ = provider(
        "zzz",
        distribution="zzz-dist",
        predicate=matches_connection(connection),
        event_log=events,
    )
    install_entry_points([last, middle])

    assert isinstance(pydapper.using(connection), MockCommands)

    loads = [event for event in events if event.startswith("load:")]
    predicates = [event for event in events if event.startswith("predicate:")]
    assert loads == ["load:mmm", "load:zzz"]
    assert predicates == ["predicate:aaa-direct", "predicate:mmm", "predicate:zzz"]
    # every load precedes every predicate, and the first predicate belongs to the adapter that was
    # already registered before the call
    assert events.index("load:zzz") < events.index("predicate:aaa-direct")


# ---------------------------------------------------------------------------- loading ignores the requested mode


def test_sync_selection_loads_async_only_providers_without_evaluating_them(install_entry_points):
    connection = MockConnection()
    async_entry, async_calls = provider(
        "asyncdb",
        distribution="async-dist",
        commands=None,
        async_commands=MockAsyncCommands,
        predicate=exploding_predicate,
    )
    sync_entry, sync_calls = provider(
        "syncdb", distribution="sync-dist", commands=MockCommands, predicate=matches_connection(connection)
    )
    install_entry_points([async_entry, sync_entry])

    assert isinstance(pydapper.using(connection), MockCommands)

    # the async-only provider really was loaded, and its predicate really was skipped
    assert async_calls == sync_calls == ["called"]
    assert async_entry.load_calls == 1
    assert main._adapter_registry["asyncdb"].async_commands is MockAsyncCommands


def test_async_selection_loads_sync_only_providers_without_evaluating_them(install_entry_points):
    connection = MockAsyncConnection()
    sync_entry, sync_calls = provider(
        "syncdb", distribution="sync-dist", commands=MockCommands, predicate=exploding_predicate
    )
    async_entry, async_calls = provider(
        "asyncdb",
        distribution="async-dist",
        commands=None,
        async_commands=MockAsyncCommands,
        predicate=matches_connection(connection),
    )
    install_entry_points([sync_entry, async_entry])

    assert isinstance(pydapper.using_async(connection), MockAsyncCommands)

    assert sync_calls == async_calls == ["called"]
    assert sync_entry.load_calls == 1
    assert main._adapter_registry["syncdb"].commands is MockCommands


# ---------------------------------------------------------------------------- zero / one / multiple is unchanged


@pytest.mark.parametrize(
    ("factory", "connection_class", "mode"),
    [
        (pydapper.using, MockConnection, "sync"),
        (pydapper.using_async, MockAsyncConnection, "async"),
    ],
)
def test_zero_matches_still_raises_the_no_match_error_after_loading(
    install_entry_points, factory, connection_class, mode
):
    entry_point, calls = provider(
        "acmedb", commands=MockCommands, async_commands=MockAsyncCommands, predicate=never_matches
    )
    install_entry_points([entry_point])

    with pytest.raises(ValueError, match="adapter=") as excinfo:
        factory(connection_class())

    message = str(excinfo.value)
    assert f"No registered {mode} adapter" in message
    assert "register an adapter" in message
    # the provider was still loaded; it simply did not claim the connection
    assert calls == ["called"]
    assert entry_point.load_calls == 1


def test_multiple_matches_across_registry_and_providers_stay_deterministically_ambiguous(install_entry_points):
    connection = MockConnection()
    pydapper.register_adapter(
        "aaa-direct",
        commands=MockCommands,
        using_connection_predicate=matches_connection(connection),
    )
    entry_point, calls = provider(
        "zzz-provider",
        distribution="zzz-dist",
        commands=MockCommands,
        predicate=matches_connection(connection),
    )
    install_entry_points([entry_point])

    with pytest.raises(ValueError, match="adapter=") as excinfo:
        pydapper.using(connection)

    message = str(excinfo.value)
    # a directly registered adapter and a freshly loaded provider are both candidates, named in
    # adapter-name order rather than load order
    assert "aaa-direct" in message
    assert "zzz-provider" in message
    assert message.index("aaa-direct") < message.index("zzz-provider")
    assert calls == ["called"]


def test_a_directly_registered_name_suppresses_its_provider_but_still_matches(install_entry_points):
    connection = MockConnection()

    class DirectCommands(MockCommands): ...

    pydapper.register_adapter(
        "acmedb",
        commands=DirectCommands,
        using_connection_predicate=matches_connection(connection),
    )
    direct_record = main._adapter_registry["acmedb"]
    same_name, same_name_calls = provider(
        "acmedb", distribution="external-dist", commands=MockCommands, predicate=exploding_predicate
    )
    install_entry_points([same_name])

    commands = pydapper.using(connection)

    # the suppressed provider never loaded, so only the directly registered predicate could have
    # produced this match
    assert isinstance(commands, DirectCommands)
    assert commands.connection is connection
    assert main._adapter_registry["acmedb"] is direct_record
    assert same_name_calls == []
    assert_nothing_loaded([same_name])


def test_predicate_errors_still_wrap_the_original_cause_after_loading(install_entry_points):
    cause = RuntimeError("predicate failed")

    def raises(connection):
        raise cause

    entry_point, calls = provider("acmedb", commands=MockCommands, predicate=raises)
    install_entry_points([entry_point])

    with pytest.raises(ValueError, match="acmedb") as excinfo:
        pydapper.using(MockConnection())

    assert "sync" in str(excinfo.value)
    assert excinfo.value.__cause__ is cause
    assert calls == ["called"]


# ---------------------------------------------------------------------------- provider failures come first


@pytest.mark.parametrize(
    ("factory", "connection_class"),
    [
        (pydapper.using, MockConnection),
        (pydapper.using_async, MockAsyncConnection),
    ],
)
def test_a_broken_provider_fails_before_any_predicate_runs(install_entry_points, factory, connection_class):
    connection = connection_class()
    # this adapter would match, and sorts ahead of the broken provider: automatic selection must
    # still fail rather than settle for the match it could already see
    pydapper.register_adapter(
        "aaa-direct",
        commands=MockCommands,
        async_commands=MockAsyncCommands,
        using_connection_predicate=exploding_predicate,
    )
    broken, boom = broken_provider("brokendb")
    install_entry_points([broken])

    with pytest.raises(ValueError) as excinfo:
        factory(connection)

    assert "brokendb" in str(excinfo.value)
    # the original provider failure survives in the cause chain, and the failure is reported as a
    # provider problem rather than re-wrapped with the connection under inspection
    assert excinfo.value.__cause__ is boom
    assert repr(connection) not in error_chain_text(excinfo.value)


def test_a_broken_provider_lacking_the_requested_mode_still_fails_selection(install_entry_points):
    # the broken provider is not even a sync candidate -- it is the async-only provider's name that
    # is installed -- but loading is deliberately mode-independent, so sync selection fails too
    pydapper.register_adapter(
        "sync-match",
        commands=MockCommands,
        using_connection_predicate=exploding_predicate,
    )
    async_only, async_calls = provider(
        "asyncdb",
        distribution="async-dist",
        commands=None,
        async_commands=MockAsyncCommands,
        predicate=exploding_predicate,
    )
    broken, boom = broken_provider("brokenasyncdb")
    install_entry_points([async_only, broken])

    with pytest.raises(ValueError) as excinfo:
        pydapper.using(MockConnection())

    assert "brokenasyncdb" in str(excinfo.value)
    assert excinfo.value.__cause__ is boom
    # the healthy async-only provider sorts first and really did load before the failure
    assert async_calls == ["called"]


def test_duplicate_unregistered_providers_fail_before_predicates(install_entry_points):
    pydapper.register_adapter(
        "aaa-direct",
        commands=MockCommands,
        using_connection_predicate=exploding_predicate,
    )
    first, first_calls = provider("dupedb", distribution="one-dist")
    second, second_calls = provider("dupedb", distribution="two-dist")
    install_entry_points([first, second])

    with pytest.raises(ValueError) as excinfo:
        pydapper.using(MockConnection())

    message = str(excinfo.value)
    assert "'dupedb'" in message
    assert "'one-dist'" in message
    assert "'two-dist'" in message
    assert first_calls == second_calls == []
    assert_nothing_loaded([first, second])


def test_repairing_a_provider_and_retrying_loads_the_rest_before_predicates(install_entry_points):
    connection = MockConnection()
    events = []
    earlier, earlier_calls = provider("aaa", distribution="earlier-dist", event_log=events)
    broken, _ = broken_provider("mmm")
    later, later_calls = provider(
        "zzz",
        distribution="later-dist",
        predicate=matches_connection(connection),
        event_log=events,
    )
    install_entry_points([earlier, broken, later])

    with pytest.raises(ValueError, match="mmm"):
        pydapper.using(connection)
    # fail-fast: the earlier provider loaded, the later one was never reached, no predicate ran
    assert earlier_calls == ["called"]
    assert later_calls == []
    assert events == ["load:aaa"]

    repaired, repaired_calls = provider("mmm", distribution="broken-adapter", event_log=events)
    install_entry_points([earlier, repaired, later])

    commands = pydapper.using(connection)

    assert isinstance(commands, MockCommands)
    assert commands.connection is connection
    # the earlier success is reused rather than reloaded, the repaired and remaining providers load,
    # and only then do predicates run
    assert earlier_calls == repaired_calls == later_calls == ["called"]
    assert earlier.load_calls == 1
    assert events[:3] == ["load:aaa", "load:mmm", "load:zzz"]
    assert all(event.startswith("predicate:") for event in events[3:])


# ---------------------------------------------------------------------------- callbacks run at most once


def test_repeated_sync_and_async_selection_never_reinvokes_a_provider(install_entry_points):
    connection = MockConnection()
    async_connection = MockAsyncConnection()
    entry_point, calls = provider(
        "acmedb",
        commands=MockCommands,
        async_commands=MockAsyncCommands,
        predicate=lambda candidate: candidate in (connection, async_connection),
    )
    install_entry_points([entry_point])

    for _ in range(3):
        assert isinstance(pydapper.using(connection), MockCommands)
        assert isinstance(pydapper.using_async(async_connection), MockAsyncCommands)

    assert calls == ["called"]
    assert entry_point.load_calls == 1


def test_concurrent_sync_and_async_selection_invokes_each_provider_once(install_entry_points, monkeypatch):
    # the winning thread blocks inside the first provider's callback until every other worker is
    # provably parked on the shared lock, so an unserialized pass would invoke a callback twice or
    # trip an incidental duplicate-registration error rather than merely running fast. The lock is
    # injected into the real helper's default rather than replacing the helper, so the whole
    # composition under test stays real.
    thread_count = 4
    # the winner acquires three times before it blocks (the pass, the nested resolution, the
    # nested load); every other worker is then parked at the pass's own acquire
    expected_attempts = 3 + (thread_count - 1)
    start_barrier = threading.Barrier(thread_count + 1)
    first_entered = threading.Event()
    all_workers_at_lock = threading.Event()
    release = threading.Event()
    alpha_calls = []

    class CountingRLock:
        def __init__(self):
            self._inner = threading.RLock()
            self._count_guard = threading.Lock()
            self._acquire_attempts = 0

        def __enter__(self):
            with self._count_guard:
                self._acquire_attempts += 1
                if self._acquire_attempts >= expected_attempts:
                    all_workers_at_lock.set()
            self._inner.acquire()
            return self

        def __exit__(self, *exc_info):
            self._inner.release()

    def register_alpha():
        alpha_calls.append("called")
        first_entered.set()
        assert release.wait(timeout=30)
        pydapper.register_adapter("alpha", commands=MockCommands, using_connection_predicate=never_matches)

    connection = MockConnection()
    async_connection = MockAsyncConnection()
    pydapper.register_adapter(
        "matchdb",
        commands=MockCommands,
        async_commands=MockAsyncCommands,
        using_connection_predicate=lambda candidate: candidate in (connection, async_connection),
    )
    alpha = FakeEntryPoint("alpha", loaded=register_alpha, distribution="one-dist")
    bravo, bravo_calls = provider("bravo", distribution="two-dist")
    install_entry_points([alpha, bravo])
    shared_lock = CountingRLock()
    monkeypatch.setitem(main._load_all_adapter_providers.__kwdefaults__, "_lock", shared_lock)

    results = []
    errors = []

    def worker(index):
        try:
            start_barrier.wait(timeout=30)
            if index % 2:
                results.append(pydapper.using_async(async_connection))
            else:
                results.append(pydapper.using(connection))
        except Exception as exc:  # pragma: no cover - failure reporting only
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(thread_count)]
    for thread in threads:
        thread.start()
    start_barrier.wait(timeout=30)
    assert first_entered.wait(timeout=30)
    assert all_workers_at_lock.wait(timeout=30)
    release.set()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)

    assert not errors
    assert alpha_calls == bravo_calls == ["called"]
    assert alpha.load_calls == bravo.load_calls == 1
    assert len(results) == thread_count
    assert {type(result) for result in results} == {MockCommands, MockAsyncCommands}


# ---------------------------------------------------------------------------- name-based paths stay isolated


def test_name_based_paths_still_ignore_an_unrelated_broken_provider(install_entry_points):
    good, good_calls = provider("acmedb", commands=MockCommands, async_commands=MockAsyncCommands)
    broken, _ = broken_provider("brokendb")
    install_entry_points([good, broken])

    assert isinstance(pydapper.connect("somedb+acmedb://localhost/database"), MockCommands)
    assert isinstance(pydapper.using(MockConnection(), adapter="acmedb"), MockCommands)
    assert isinstance(pydapper.using_async(MockAsyncConnection(), adapter="acmedb"), MockAsyncCommands)

    # only automatic selection loads everything; the name-based paths still load exactly one
    # provider and leave the broken one untouched
    assert good_calls == ["called"]
    assert good.load_calls == 1
    assert_nothing_loaded([broken])
    assert "brokendb" not in main._adapter_registry


# ---------------------------------------------------------------------------- public surface


def test_automatic_selection_integration_adds_no_public_api():
    public_names = {
        name
        for name, value in vars(pydapper).items()
        if not name.startswith("_") and not isinstance(value, types.ModuleType)
    }
    assert public_names == {
        "AdapterCapability",
        "CommandKind",
        "CommandOptions",
        "Mapper",
        "RawRow",
        "connect",
        "connect_async",
        "register_adapter",
        "using",
        "using_async",
    }
    assert list(inspect.signature(pydapper.using).parameters) == ["connection", "adapter"]
    assert list(inspect.signature(pydapper.using_async).parameters) == ["connection", "adapter"]
    for function in (pydapper.using, pydapper.using_async):
        assert inspect.signature(function).parameters["adapter"].kind is inspect.Parameter.KEYWORD_ONLY
        assert inspect.signature(function).parameters["adapter"].default is None
