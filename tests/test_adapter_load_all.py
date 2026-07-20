"""Focused coverage for the private deterministic load-all-providers pass.

Exercises ``main._load_all_adapter_providers()`` against the real discovery
catalog, the real ``_resolve_adapter_registration()``, and the real
``_load_adapter_provider()``. The resolver is never stubbed; only installed
entry-point metadata is faked, so these tests fail if the pass stops delegating
selection, precedence, or the transactional load.

The helper is private infrastructure for a later automatic-selection slice and
is deliberately not wired into any public path yet.

Callback validation, hostile mutation, rollback internals, exact-name public
integration, and resolver mutation coverage already live in
tests/test_adapter_discovery.py, tests/test_adapter_loading.py,
tests/test_adapter_resolution.py, and
tests/test_adapter_name_resolution_integration.py and are not duplicated here.
"""

import importlib.metadata
import threading
import types
from types import MappingProxyType

import pytest

import pydapper
import pydapper.main as main
from pydapper import _adapter_discovery
from tests.mocks import MockAsyncCommands
from tests.mocks import MockCommands

pytestmark = pytest.mark.core

GROUP = "pydapper.adapters"
FIRST_PARTY = "pydapper"


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


def exploding_predicate(connection):  # pragma: no cover - must never run
    raise AssertionError("loading providers must never evaluate a connection predicate")


class ExplodingCommands(MockCommands):
    """Valid registration content that fails loudly if the pass touches a connection."""

    def __init__(self, *args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("loading providers must never instantiate a command class")

    @classmethod
    def connect(cls, *args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("loading providers must never open a connection")


class ExplodingAsyncCommands(MockAsyncCommands):
    def __init__(self, *args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("loading providers must never instantiate a command class")

    @classmethod
    async def connect_async(cls, *args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("loading providers must never open a connection")


def provider(
    name,
    *,
    distribution="acme-adapter",
    commands=MockCommands,
    async_commands=None,
    predicate=never_matches,
    order_log=None,
):
    """Build an entry point whose callback really registers ``name``, plus its call log."""
    calls = []

    def register():
        calls.append("called")
        if order_log is not None:
            order_log.append(name)
        pydapper.register_adapter(
            name,
            commands=commands,
            async_commands=async_commands,
            using_connection_predicate=predicate,
        )

    return FakeEntryPoint(name, loaded=register, distribution=distribution), calls


def broken_provider(name, *, distribution="broken-adapter", error=None):
    error = error if error is not None else ImportError(f"{name} provider is broken")
    return FakeEntryPoint(name, distribution=distribution, load_error=error), error


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    """Give each test a private registry, provider catalog, and loader cache.

    Every piece of process state these tests touch is swapped through
    monkeypatch, so this is a real snapshot/restore rather than a reset: a
    catalog or loader cache the process had already built is put back verbatim
    at teardown instead of being emptied, and nothing here can decide whether a
    name resolves in another module. First-party adapters are still eagerly
    registered at import time in this slice, so the registry is copied rather
    than emptied.
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


def assert_registry_exactly(before):
    assert list(main._adapter_registry) == list(before)
    for name, registration in before.items():
        assert main._adapter_registry[name] is registration


def assert_preserved_prefix(before):
    """The pre-existing registrations survive unchanged, in order, ahead of new ones."""
    names = list(main._adapter_registry)
    assert names[: len(before)] == list(before)
    for name, registration in before.items():
        assert main._adapter_registry[name] is registration


def assert_nothing_loaded(entry_points):
    for entry_point in entry_points:
        assert entry_point.load_calls == 0


# ---------------------------------------------------------------------------- empty catalog


def test_empty_catalog_is_a_successful_no_op(install_entry_points, isolated_registry):
    install_entry_points([])
    before = dict(isolated_registry)

    assert main._load_all_adapter_providers() is None

    assert_registry_exactly(before)
    assert main._loaded_provider_registrations == {}


# ---------------------------------------------------------------------------- deterministic ordering


def test_providers_load_in_sorted_name_order_despite_reverse_enumeration(install_entry_points, isolated_registry):
    order = []
    names = ["alpha", "bravo", "charlie", "delta"]
    entries = {}
    logs = {}
    for index, name in enumerate(names):
        entries[name], logs[name] = provider(name, distribution=f"dist-{index}", order_log=order)
    # metadata is enumerated in the exact reverse of the required load order
    install_entry_points(reversed(list(entries.values())))
    before = dict(isolated_registry)

    assert main._load_all_adapter_providers() is None

    assert order == sorted(names)
    for name in names:
        assert logs[name] == ["called"]
        assert entries[name].load_calls == 1
        assert main._adapter_registry[name].name == name
    assert_preserved_prefix(before)


def test_pass_sorts_names_instead_of_trusting_catalog_mapping_order(install_entry_points, monkeypatch):
    # the real catalog already emits sorted keys, so mapping order is pinned separately: a catalog
    # whose insertion order is reversed must still be walked in sorted exact-name order
    order = []
    names = ["alpha", "bravo", "charlie"]
    entries = {}
    for index, name in enumerate(names):
        entries[name], _ = provider(name, distribution=f"dist-{index}", order_log=order)
    install_entry_points(entries.values())

    real_catalog = _adapter_discovery._get_provider_catalog()
    reversed_catalog = MappingProxyType({name: real_catalog[name] for name in reversed(names)})
    assert list(reversed_catalog) == list(reversed(names))
    monkeypatch.setattr(main, "_get_provider_catalog", lambda: reversed_catalog)

    main._load_all_adapter_providers()

    assert order == sorted(names)


def test_exact_case_hyphen_and_underscore_variants_are_separate_names(install_entry_points):
    order = []
    names = ["AcmeDB", "acmedb", "acme-db", "acme_db"]
    entries = {}
    for name in names:
        entries[name], _ = provider(name, order_log=order)
    install_entry_points(entries.values())

    main._load_all_adapter_providers()

    # four distinct adapters, walked in exact byte order with no normalization of case,
    # hyphens, or underscores
    assert order == ["AcmeDB", "acme-db", "acme_db", "acmedb"]
    for name in names:
        assert main._adapter_registry[name].name == name


# ---------------------------------------------------------------------------- mode independence


def test_sync_only_async_only_and_dual_mode_providers_all_load(install_entry_points):
    sync_entry, sync_calls = provider("syncdb", distribution="sync-dist", commands=MockCommands)
    async_entry, async_calls = provider(
        "asyncdb", distribution="async-dist", commands=None, async_commands=MockAsyncCommands
    )
    dual_entry, dual_calls = provider(
        "dualdb", distribution="dual-dist", commands=MockCommands, async_commands=MockAsyncCommands
    )
    install_entry_points([sync_entry, async_entry, dual_entry])

    assert main._load_all_adapter_providers() is None

    assert sync_calls == async_calls == dual_calls == ["called"]
    sync_registration = main._adapter_registry["syncdb"]
    async_registration = main._adapter_registry["asyncdb"]
    dual_registration = main._adapter_registry["dualdb"]
    assert (sync_registration.commands, sync_registration.async_commands) == (MockCommands, None)
    assert (async_registration.commands, async_registration.async_commands) == (None, MockAsyncCommands)
    assert (dual_registration.commands, dual_registration.async_commands) == (MockCommands, MockAsyncCommands)


def test_pass_never_runs_predicates_constructors_or_connection_factories(install_entry_points):
    entry, calls = provider(
        "acmedb",
        commands=ExplodingCommands,
        async_commands=ExplodingAsyncCommands,
        predicate=exploding_predicate,
    )
    install_entry_points([entry])

    assert main._load_all_adapter_providers() is None

    # registered, but nothing about the registration was exercised beyond validation
    assert calls == ["called"]
    registration = main._adapter_registry["acmedb"]
    assert registration.commands is ExplodingCommands
    assert registration.async_commands is ExplodingAsyncCommands
    assert registration.using_connection_predicate is exploding_predicate


def test_helper_takes_no_mode_or_connection_argument():
    parameters = main._load_all_adapter_providers.__code__.co_varnames[
        : main._load_all_adapter_providers.__code__.co_argcount
        + main._load_all_adapter_providers.__code__.co_kwonlyargcount
    ]
    assert parameters == ("_lock",)


# ---------------------------------------------------------------------------- existing registrations win


def test_existing_registration_is_preserved_and_its_provider_never_loads(install_entry_points, isolated_registry):
    entry, calls = provider("acmedb")
    other_entry, other_calls = provider("otherdb", distribution="other-dist")
    install_entry_points([entry, other_entry])
    pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
    direct_record = main._adapter_registry["acmedb"]
    before = dict(isolated_registry)

    main._load_all_adapter_providers()

    assert main._adapter_registry["acmedb"] is direct_record
    assert calls == []
    assert_nothing_loaded([entry])
    assert other_calls == ["called"]
    assert_preserved_prefix(before)


def test_registered_name_suppresses_a_same_name_duplicate_provider_conflict(install_entry_points):
    first, first_calls = provider("acmedb", distribution="one-dist")
    second, second_calls = provider("acmedb", distribution="two-dist")
    good, good_calls = provider("otherdb", distribution="other-dist")
    install_entry_points([first, second, good])
    pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
    direct_record = main._adapter_registry["acmedb"]

    # the duplicate is never evaluated, so the pass succeeds instead of raising
    main._load_all_adapter_providers()

    assert main._adapter_registry["acmedb"] is direct_record
    assert first_calls == second_calls == []
    assert_nothing_loaded([first, second])
    assert good_calls == ["called"]


def test_registered_name_suppresses_a_same_name_broken_provider(install_entry_points):
    broken, _ = broken_provider("acmedb")
    good, good_calls = provider("otherdb", distribution="other-dist")
    install_entry_points([broken, good])
    pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
    direct_record = main._adapter_registry["acmedb"]

    main._load_all_adapter_providers()

    assert main._adapter_registry["acmedb"] is direct_record
    assert_nothing_loaded([broken])
    assert good_calls == ["called"]


def test_registrations_absent_from_the_catalog_are_untouched(install_entry_points, isolated_registry):
    entry, _ = provider("acmedb")
    install_entry_points([entry])
    before = dict(isolated_registry)
    # the eagerly bootstrapped built-ins are not in this catalog at all
    assert "sqlite3" in before

    main._load_all_adapter_providers()

    assert_preserved_prefix(before)
    assert list(main._adapter_registry) == list(before) + ["acmedb"]


# ---------------------------------------------------------------------------- reused precedence


def test_first_party_precedence_is_reused_and_ignored_externals_never_load(install_entry_points):
    first_party, first_party_calls = provider("acmedb", distribution=FIRST_PARTY)
    external, external_calls = provider("acmedb", distribution="external-dist")
    install_entry_points([external, first_party])

    main._load_all_adapter_providers()

    assert first_party_calls == ["called"]
    assert first_party.load_calls == 1
    assert external_calls == []
    assert_nothing_loaded([external])
    assert main._adapter_registry["acmedb"].name == "acmedb"


def test_duplicate_external_providers_fail_before_either_candidate_loads(install_entry_points, isolated_registry):
    earlier, earlier_calls = provider("aaa", distribution="earlier-dist")
    first, first_calls = provider("bbb", distribution="one-dist")
    second, second_calls = provider("bbb", distribution="two-dist")
    later, later_calls = provider("ccc", distribution="later-dist")
    install_entry_points([earlier, first, second, later])
    before = dict(isolated_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_all_adapter_providers()

    message = str(excinfo.value)
    assert "'bbb'" in message
    assert "'one-dist'" in message
    assert "'two-dist'" in message
    assert "://" not in message
    assert first_calls == second_calls == []
    assert_nothing_loaded([first, second])
    # fail-fast in sorted order: the earlier name is kept, the later one is never reached
    assert earlier_calls == ["called"]
    assert main._adapter_registry["aaa"].name == "aaa"
    assert later_calls == []
    assert_nothing_loaded([later])
    assert "ccc" not in main._adapter_registry
    assert_preserved_prefix(before)


def test_duplicate_first_party_providers_fail_before_either_candidate_loads(install_entry_points):
    first, first_calls = provider("bbb", distribution=FIRST_PARTY)
    second, second_calls = provider("bbb", distribution="PyDapper")
    install_entry_points([first, second])

    with pytest.raises(ValueError) as excinfo:
        main._load_all_adapter_providers()

    assert "'bbb'" in str(excinfo.value)
    assert first_calls == second_calls == []
    assert_nothing_loaded([first, second])
    assert "bbb" not in main._adapter_registry


# ---------------------------------------------------------------------------- fail-fast and retry


def test_broken_provider_stops_the_pass_without_rolling_back_earlier_successes(install_entry_points, isolated_registry):
    earlier, earlier_calls = provider("aaa", distribution="earlier-dist")
    broken, boom = broken_provider("bbb")
    later, later_calls = provider("ccc", distribution="later-dist")
    install_entry_points([earlier, broken, later])
    before = dict(isolated_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_all_adapter_providers()

    message = str(excinfo.value)
    assert "'bbb'" in message
    assert "://" not in message
    # the original provider failure survives in the cause chain
    assert excinfo.value.__cause__ is boom

    # earlier success kept, later name never reached
    assert earlier_calls == ["called"]
    assert main._adapter_registry["aaa"].name == "aaa"
    assert "bbb" not in main._adapter_registry
    assert later_calls == []
    assert_nothing_loaded([later])
    assert "ccc" not in main._adapter_registry
    assert_preserved_prefix(before)


def test_retry_after_repair_skips_earlier_successes_and_continues(install_entry_points):
    earlier, earlier_calls = provider("aaa", distribution="earlier-dist")
    broken, _ = broken_provider("bbb")
    later, later_calls = provider("ccc", distribution="later-dist")
    install_entry_points([earlier, broken, later])

    with pytest.raises(ValueError):
        main._load_all_adapter_providers()
    assert earlier_calls == ["called"]

    repaired, repaired_calls = provider("bbb", distribution="broken-adapter")
    install_entry_points([earlier, repaired, later])

    assert main._load_all_adapter_providers() is None

    # the already-registered earlier name is skipped rather than reloaded
    assert earlier_calls == ["called"]
    assert earlier.load_calls == 1
    # the repaired provider loads and the pass continues through the later name
    assert repaired_calls == ["called"]
    assert later_calls == ["called"]
    assert list(main._adapter_registry)[-3:] == ["aaa", "bbb", "ccc"]


# ---------------------------------------------------------------------------- repeated and concurrent calls


def test_repeated_successful_calls_invoke_each_provider_once(install_entry_points):
    first, first_calls = provider("alpha", distribution="one-dist")
    second, second_calls = provider("bravo", distribution="two-dist")
    install_entry_points([first, second])

    assert main._load_all_adapter_providers() is None
    registrations = {name: main._adapter_registry[name] for name in ("alpha", "bravo")}
    assert main._load_all_adapter_providers() is None

    assert first_calls == second_calls == ["called"]
    assert first.load_calls == second.load_calls == 1
    for name, registration in registrations.items():
        assert main._adapter_registry[name] is registration


def test_catalog_is_enumerated_only_once_through_its_existing_cache(monkeypatch):
    entry, _ = provider("acmedb")
    enumerations = []

    def counting_entry_points(*, group):
        enumerations.append(group)
        return [entry] if entry.group == group else []

    monkeypatch.setattr(importlib.metadata, "entry_points", counting_entry_points)
    _adapter_discovery._reset_provider_catalog_for_tests()

    main._load_all_adapter_providers()
    main._load_all_adapter_providers()

    assert enumerations == [GROUP]


def test_load_all_uses_the_definition_time_load_lock():
    original_lock = main._provider_load_lock
    # one lock for the whole subsystem: no second lock is introduced by this slice
    assert main._load_all_adapter_providers.__kwdefaults__["_lock"] is original_lock
    assert main._resolve_adapter_registration.__kwdefaults__["_lock"] is original_lock
    assert main._load_adapter_provider.__kwdefaults__["_lock"] is original_lock
    assert main._register_adapter_under_lock.__kwdefaults__["_lock"] is original_lock


def test_concurrent_load_all_calls_invoke_each_provider_once(install_entry_points):
    # the winning thread blocks inside the first provider's callback until every other worker is
    # provably parked on the shared lock, so an unserialized pass would invoke a callback twice or
    # trip an incidental duplicate-registration error rather than merely running fast.
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

    alpha = FakeEntryPoint("alpha", loaded=register_alpha, distribution="one-dist")
    bravo, bravo_calls = provider("bravo", distribution="two-dist")
    install_entry_points([alpha, bravo])
    shared_lock = CountingRLock()

    results = []
    errors = []

    def worker():
        try:
            start_barrier.wait(timeout=30)
            results.append(main._load_all_adapter_providers(_lock=shared_lock))
        except Exception as exc:  # pragma: no cover - failure reporting only
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
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
    assert results == [None] * thread_count
    assert main._adapter_registry["alpha"].name == "alpha"
    assert main._adapter_registry["bravo"].name == "bravo"


def test_direct_registration_winning_the_lock_suppresses_its_same_name_provider(install_entry_points, monkeypatch):
    # the direct registration lands first and holds the lock, so the pass that follows must observe
    # it and skip the same-name provider entirely
    registered = threading.Event()
    pass_attempt = threading.Event()
    release = threading.Event()

    class GatedRegistry(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.gated = False

        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if key == "acmedb" and not self.gated:
                self.gated = True
                registered.set()
                assert release.wait(timeout=30)

    class CountingRLock:
        def __init__(self):
            self._inner = threading.RLock()
            self._count_guard = threading.Lock()
            self._acquire_attempts = 0

        def __enter__(self):
            with self._count_guard:
                self._acquire_attempts += 1
                if self._acquire_attempts >= 2:
                    pass_attempt.set()
            self._inner.acquire()
            return self

        def __exit__(self, *exc_info):
            self._inner.release()

    monkeypatch.setattr(main, "_adapter_registry", GatedRegistry(main._adapter_registry))
    shared_lock = CountingRLock()
    monkeypatch.setitem(main._register_adapter_under_lock.__kwdefaults__, "_lock", shared_lock)

    entry, calls = provider("acmedb")
    install_entry_points([entry])

    direct_errors = []
    pass_errors = []

    def direct_worker():
        try:
            pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
        except Exception as exc:  # pragma: no cover - failure reporting only
            direct_errors.append(exc)

    def pass_worker():
        try:
            main._load_all_adapter_providers(_lock=shared_lock)
        except Exception as exc:  # pragma: no cover - failure reporting only
            pass_errors.append(exc)

    direct = threading.Thread(target=direct_worker)
    direct.start()
    assert registered.wait(timeout=30)
    loader = threading.Thread(target=pass_worker)
    loader.start()
    # the pass is provably waiting on the shared lock while the direct registration still holds it
    assert pass_attempt.wait(timeout=30)
    release.set()
    direct.join(timeout=30)
    loader.join(timeout=30)
    assert not direct.is_alive()
    assert not loader.is_alive()

    assert not direct_errors
    assert not pass_errors
    assert calls == []
    assert_nothing_loaded([entry])
    assert main._adapter_registry["acmedb"].commands is MockCommands


# ---------------------------------------------------------------------------- scope


def test_automatic_using_paths_do_not_call_the_load_all_helper(install_entry_points, monkeypatch):
    def must_not_run(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("automatic selection must not load all providers in this slice")

    monkeypatch.setattr(main, "_load_all_adapter_providers", must_not_run)
    entry, calls = provider("acmedb", predicate=lambda connection: True)
    install_entry_points([entry])
    connection = object()

    # automatic selection stays registry-only: the installed provider is never loaded, so its
    # would-be matching predicate is never consulted
    with pytest.raises(ValueError) as sync_excinfo:
        pydapper.using(connection)
    with pytest.raises(ValueError) as async_excinfo:
        pydapper.using_async(connection)

    assert "No registered sync adapter" in str(sync_excinfo.value)
    assert "No registered async adapter" in str(async_excinfo.value)
    assert calls == []
    assert_nothing_loaded([entry])
    assert "acmedb" not in main._adapter_registry


def test_automatic_selection_still_uses_a_directly_registered_adapter(install_entry_points, monkeypatch):
    def must_not_run(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("automatic selection must not load all providers in this slice")

    monkeypatch.setattr(main, "_load_all_adapter_providers", must_not_run)
    entry, calls = provider("acmedb")
    install_entry_points([entry])
    connection = object()
    pydapper.register_adapter(
        "matchingdb",
        commands=MockCommands,
        async_commands=MockAsyncCommands,
        using_connection_predicate=lambda candidate: candidate is connection,
    )

    assert isinstance(pydapper.using(connection), MockCommands)
    assert isinstance(pydapper.using_async(connection), MockAsyncCommands)
    assert calls == []
    assert_nothing_loaded([entry])


def test_load_all_adds_no_public_api():
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
    # the pass is private, pinned by the exact non-underscore surface of main rather than by a
    # substring guess
    assert {name for name in vars(main) if not name.startswith("_")} == {
        "AdapterCapability",
        "AsyncConnectionType",
        "BaseCommands",
        "Callable",
        "CommandFactory",
        "Commands",
        "CommandsAsync",
        "ConnectionType",
        "Counter",
        "Iterable",
        "PydapperParseResult",
        "annotations",
        "connect",
        "connect_async",
        "dataclass",
        "inspect",
        "logger",
        "logging",
        "os",
        "parse_dsn",
        "re",
        "register_adapter",
        "threading",
        "using",
        "using_async",
    }
