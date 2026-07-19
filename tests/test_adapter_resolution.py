import importlib.metadata
import logging
import threading
import types

import pytest

import pydapper
import pydapper.main as main
from pydapper import _adapter_discovery
from pydapper._adapter_discovery import _AdapterProviderDescriptor
from tests.mocks import MockAsyncCommands
from tests.mocks import MockCommands

pytestmark = pytest.mark.core

GROUP = "pydapper.adapters"
FIRST_PARTY = "pydapper"


class FakeDistribution:
    def __init__(self, name):
        self.name = name


class FakeEntryPoint:
    """Resolution-slice fake: passes real discovery *and* really loads a callback.

    Discovery reads ``name``/``value``/``group``/``dist``; the loader calls
    ``load()``. Using one fake for both halves keeps these tests on the real
    catalog + loader path instead of a hand-built stand-in.
    """

    def __init__(
        self,
        name,
        *,
        loaded=None,
        distribution="acme-adapter",
        value=None,
        group=GROUP,
        load_error=None,
    ):
        self.name = name
        self.loaded = loaded
        self.value = value if value is not None else f"pydapper_should_not_import_{distribution}:register"
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


def registering_callback(name, *, commands=MockCommands, async_commands=None, predicate=never_matches):
    calls = []

    def register():
        calls.append("called")
        pydapper.register_adapter(
            name,
            commands=commands,
            async_commands=async_commands,
            using_connection_predicate=predicate,
        )

    return register, calls


def provider(name, *, distribution="acme-adapter", value=None, commands=MockCommands, predicate=never_matches):
    """Build an entry point whose callback registers ``name``, plus its call log."""
    callback, calls = registering_callback(name, commands=commands, predicate=predicate)
    return FakeEntryPoint(name, loaded=callback, distribution=distribution, value=value), calls


def broken_provider(name, *, distribution="broken-adapter", error=None):
    error = error if error is not None else ImportError(f"{name} provider is broken")
    return FakeEntryPoint(name, distribution=distribution, load_error=error)


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    registry = main._adapter_registry.copy()
    monkeypatch.setattr(main, "_adapter_registry", registry)
    original_lock = main._provider_load_lock
    main._reset_provider_load_state_for_tests()
    _adapter_discovery._reset_provider_catalog_for_tests()
    yield registry
    main._provider_load_lock = original_lock
    main._reset_provider_load_state_for_tests()
    _adapter_discovery._reset_provider_catalog_for_tests()


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


@pytest.fixture
def forbid_discovery(monkeypatch):
    def fail_enumeration(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("resolution must not enumerate entry points on this path")

    monkeypatch.setattr(importlib.metadata, "entry_points", fail_enumeration)
    _adapter_discovery._reset_provider_catalog_for_tests()


def assert_nothing_loaded(entry_points):
    for entry_point in entry_points:
        assert entry_point.load_calls == 0


# ---------------------------------------------------------------------------- existing registration wins


def test_directly_registered_adapter_is_returned_by_identity_without_discovery(forbid_discovery):
    pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
    direct_record = main._adapter_registry["acmedb"]

    assert main._resolve_adapter_registration("acmedb") is direct_record
    # the enumeration guard proves no discovery ran; the unbuilt catalog proves none was cached
    assert _adapter_discovery._catalog is None


def test_eagerly_bootstrapped_adapter_resolves_without_discovery(forbid_discovery):
    # the built-in bootstrap still populates the registry in this slice, so a stable name must
    # resolve straight from it
    assert main._resolve_adapter_registration("sqlite3") is main._adapter_registry["sqlite3"]
    assert _adapter_discovery._catalog is None


def test_direct_registration_prevents_a_same_name_provider_from_loading(install_entry_points):
    entry_point, calls = provider("acmedb")
    install_entry_points([entry_point])
    pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
    direct_record = main._adapter_registry["acmedb"]

    assert main._resolve_adapter_registration("acmedb") is direct_record
    assert calls == []
    assert_nothing_loaded([entry_point])
    assert main._loaded_provider_registrations == {}


def test_direct_registration_wins_over_a_first_party_provider(install_entry_points):
    entry_point, calls = provider("acmedb", distribution=FIRST_PARTY)
    install_entry_points([entry_point])
    pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
    direct_record = main._adapter_registry["acmedb"]

    assert main._resolve_adapter_registration("acmedb") is direct_record
    assert calls == []
    assert_nothing_loaded([entry_point])


def test_direct_registration_wins_over_an_otherwise_conflicting_name(install_entry_points):
    # duplicate external providers would be a hard error, but a runtime registration short-circuits
    # selection entirely, so the conflict is never even evaluated
    first, first_calls = provider("acmedb", distribution="one-dist")
    second, second_calls = provider("acmedb", distribution="two-dist")
    install_entry_points([first, second])
    pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
    direct_record = main._adapter_registry["acmedb"]

    assert main._resolve_adapter_registration("acmedb") is direct_record
    assert first_calls == second_calls == []
    assert_nothing_loaded([first, second])


# ---------------------------------------------------------------------------- external provider loading


def test_single_external_provider_is_selected_loaded_and_returned(install_entry_points):
    entry_point, calls = provider("acmedb")
    install_entry_points([entry_point])

    registration = main._resolve_adapter_registration("acmedb")

    assert calls == ["called"]
    assert entry_point.load_calls == 1
    assert isinstance(registration, main._AdapterRegistration)
    assert registration.name == "acmedb"
    assert main._adapter_registry["acmedb"] is registration


def test_repeated_resolution_returns_the_registered_record_without_reinvoking(install_entry_points):
    entry_point, calls = provider("acmedb")
    install_entry_points([entry_point])

    first = main._resolve_adapter_registration("acmedb")
    second = main._resolve_adapter_registration("acmedb")
    third = main._resolve_adapter_registration("acmedb")

    assert first is second is third
    assert calls == ["called"]
    assert entry_point.load_calls == 1


def test_resolution_returns_the_loader_registration_object(install_entry_points):
    entry_point, _ = provider("acmedb")
    install_entry_points([entry_point])

    registration = main._resolve_adapter_registration("acmedb")

    assert main._loaded_provider_registrations == {
        (
            "acmedb",
            "acme-adapter",
            entry_point.value,
        ): registration
    }


def test_resolution_only_loads_the_requested_provider(install_entry_points):
    wanted, wanted_calls = provider("acmedb")
    other, other_calls = provider("otherdb", distribution="other-adapter")
    install_entry_points([wanted, other])

    main._resolve_adapter_registration("acmedb")

    assert wanted_calls == ["called"]
    assert other_calls == []
    assert_nothing_loaded([other])
    assert "otherdb" not in main._adapter_registry


def test_resolution_never_loads_an_unrelated_broken_provider(install_entry_points):
    wanted, wanted_calls = provider("acmedb")
    broken = broken_provider("brokendb")
    install_entry_points([broken, wanted])

    registration = main._resolve_adapter_registration("acmedb")

    assert wanted_calls == ["called"]
    assert registration.name == "acmedb"
    assert_nothing_loaded([broken])


def test_loader_failures_are_not_masked_by_resolution(install_entry_points):
    original = ImportError("provider module missing")
    install_entry_points([broken_provider("acmedb", distribution="acme-adapter", error=original)])
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._resolve_adapter_registration("acmedb")

    # the loader owns wrapping, cause preservation, and rollback; resolution must not weaken them
    assert excinfo.value.__cause__ is original
    assert repr("acmedb") in str(excinfo.value)
    assert repr("acme-adapter") in str(excinfo.value)
    assert dict(main._adapter_registry) == before
    assert main._loaded_provider_registrations == {}


# ---------------------------------------------------------------------------- unknown and exact names


def test_unknown_name_raises_a_clear_value_error_without_a_key_error(install_entry_points):
    install_entry_points([provider("acmedb")[0]])

    with pytest.raises(ValueError) as excinfo:
        main._resolve_adapter_registration("nosuchdb")

    message = str(excinfo.value)
    assert repr("nosuchdb") in message
    assert "No registered or installed adapter" in message
    assert "://" not in message
    assert excinfo.value.__cause__ is None
    assert not isinstance(excinfo.value.__context__, KeyError)


def test_empty_provider_tuple_is_treated_as_an_unknown_name(monkeypatch):
    # a name present in the catalog with no providers must not fall through to an index error
    monkeypatch.setattr(main, "_get_provider_catalog", lambda: {"acmedb": ()})

    with pytest.raises(ValueError) as excinfo:
        main._resolve_adapter_registration("acmedb")

    assert repr("acmedb") in str(excinfo.value)
    assert excinfo.value.__cause__ is None


def test_no_installed_providers_still_raises_a_clear_error(install_entry_points):
    install_entry_points([])

    with pytest.raises(ValueError) as excinfo:
        main._resolve_adapter_registration("acmedb")

    assert repr("acmedb") in str(excinfo.value)


@pytest.mark.parametrize("requested", ["AcmeDB", "acmedb", "acme-db", "acme_db"])
def test_case_hyphen_and_underscore_variants_stay_distinct(install_entry_points, requested):
    variants = ["AcmeDB", "acmedb", "acme-db", "acme_db"]
    entries = {}
    logs = {}
    for index, name in enumerate(variants):
        entries[name], logs[name] = provider(name, distribution=f"dist-{index}")
    install_entry_points(entries.values())

    registration = main._resolve_adapter_registration(requested)

    assert registration.name == requested
    assert logs[requested] == ["called"]
    for name in variants:
        if name != requested:
            assert logs[name] == []
            assert_nothing_loaded([entries[name]])
            assert name not in main._adapter_registry


def test_a_near_miss_name_does_not_resolve_to_a_similar_provider(install_entry_points):
    entry_point, calls = provider("acme-db")
    install_entry_points([entry_point])

    with pytest.raises(ValueError) as excinfo:
        main._resolve_adapter_registration("acme_db")

    assert repr("acme_db") in str(excinfo.value)
    assert calls == []
    assert_nothing_loaded([entry_point])


@pytest.mark.parametrize("requested", [" acmedb", "acmedb ", "ACMEDB"])
def test_whitespace_and_case_are_never_trimmed_or_folded(install_entry_points, requested):
    entry_point, calls = provider("acmedb")
    install_entry_points([entry_point])

    with pytest.raises(ValueError):
        main._resolve_adapter_registration(requested)

    assert calls == []
    assert_nothing_loaded([entry_point])


# ---------------------------------------------------------------------------- first-party precedence


def test_first_party_provider_beats_a_single_external_collision(install_entry_points):
    external, external_calls = provider("acmedb", distribution="acme-adapter")
    first_party, first_party_calls = provider("acmedb", distribution=FIRST_PARTY)
    install_entry_points([external, first_party])

    registration = main._resolve_adapter_registration("acmedb")

    assert first_party_calls == ["called"]
    assert first_party.load_calls == 1
    assert external_calls == []
    assert_nothing_loaded([external])
    assert main._adapter_registry["acmedb"] is registration


def test_first_party_provider_beats_multiple_external_collisions(install_entry_points):
    externals = [provider("acmedb", distribution=name) for name in ("zeta-dist", "alpha-dist", "middle-dist")]
    first_party, first_party_calls = provider("acmedb", distribution=FIRST_PARTY)
    install_entry_points([entry_point for entry_point, _ in externals] + [first_party])

    main._resolve_adapter_registration("acmedb")

    assert first_party_calls == ["called"]
    for entry_point, calls in externals:
        assert calls == []
        assert entry_point.load_calls == 0


def test_ignored_external_distributions_are_reported_in_a_debug_log(install_entry_points, caplog):
    externals = [provider("acmedb", distribution=name) for name in ("zeta-dist", "alpha-dist")]
    first_party, _ = provider("acmedb", distribution=FIRST_PARTY)
    install_entry_points([entry_point for entry_point, _ in externals] + [first_party])

    with caplog.at_level(logging.DEBUG, logger="pydapper.main"):
        main._resolve_adapter_registration("acmedb")

    records = [record for record in caplog.records if record.levelno == logging.DEBUG]
    assert len(records) == 1
    message = records[0].getMessage()
    assert repr("acmedb") in message
    # deterministic order regardless of enumeration order, and no ignored provider was imported
    assert message.endswith(f"{'alpha-dist'!r}, {'zeta-dist'!r}")
    assert "://" not in message
    for entry_point, _ in externals:
        assert entry_point.load_calls == 0


def test_no_debug_log_when_there_is_nothing_to_ignore(install_entry_points, caplog):
    first_party, _ = provider("acmedb", distribution=FIRST_PARTY)
    install_entry_points([first_party])

    with caplog.at_level(logging.DEBUG, logger="pydapper.main"):
        main._resolve_adapter_registration("acmedb")

    assert [record for record in caplog.records if record.levelno == logging.DEBUG] == []


@pytest.mark.parametrize("distribution", ["pydapper", "PyDapper", "PYDAPPER", "Pydapper"])
def test_distribution_case_variants_are_still_first_party(install_entry_points, distribution):
    external, external_calls = provider("acmedb", distribution="acme-adapter")
    first_party, first_party_calls = provider("acmedb", distribution=distribution)
    install_entry_points([external, first_party])

    main._resolve_adapter_registration("acmedb")

    assert first_party_calls == ["called"]
    assert external_calls == []


@pytest.mark.parametrize("distribution", ["py-dapper", "py_dapper", "py.dapper", "pydapper-acmedb", "pydapper2"])
def test_lookalike_distributions_are_not_treated_as_first_party(install_entry_points, distribution):
    lookalike, _ = provider("acmedb", distribution=distribution)
    external, _ = provider("acmedb", distribution="acme-adapter")
    install_entry_points([lookalike, external])

    with pytest.raises(ValueError) as excinfo:
        main._resolve_adapter_registration("acmedb")

    # neither is first party, so this is an ordinary external conflict
    assert repr(distribution) in str(excinfo.value)
    assert repr("acme-adapter") in str(excinfo.value)
    assert_nothing_loaded([lookalike, external])


def test_distribution_canonicalization_follows_package_name_semantics():
    canonicalize = main._canonicalize_distribution_name
    assert canonicalize("Acme.Adapter") == canonicalize("acme_adapter") == canonicalize("ACME-adapter")
    assert canonicalize("acme--__..adapter") == "acme-adapter"
    # normalization applies to distributions only; it must never collapse distinct adapter names
    assert canonicalize("pydapper") != canonicalize("py-dapper")


# ---------------------------------------------------------------------------- duplicate providers


HOSTILE_VALUE = "postgres://user:hunter2@db.example.com/register"


def test_multiple_first_party_providers_fail_before_any_load(install_entry_points):
    first, first_calls = provider("acmedb", distribution=FIRST_PARTY, value="pydapper.one:register")
    second, second_calls = provider("acmedb", distribution="PyDapper", value="pydapper.two:register")
    external, external_calls = provider("acmedb", distribution="acme-adapter")
    install_entry_points([first, second, external])
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._resolve_adapter_registration("acmedb")

    message = str(excinfo.value)
    assert repr("acmedb") in message
    assert "packaging" in message
    # both first-party distributions are named, so a duplicate install is diagnosable
    assert repr("PyDapper") in message and repr(FIRST_PARTY) in message
    assert first_calls == second_calls == external_calls == []
    assert_nothing_loaded([first, second, external])
    assert dict(main._adapter_registry) == before
    assert main._loaded_provider_registrations == {}


@pytest.mark.parametrize("distributions", [(FIRST_PARTY, "PyDapper"), ("one-dist", "two-dist")])
def test_conflict_errors_never_disclose_entry_point_values(install_entry_points, distributions):
    # entry-point values are arbitrary installed metadata pydapper does not control; a value
    # carrying credentials must never reach an error message. Both conflict branches are covered.
    entries = [
        provider("acmedb", distribution=distributions[0], value=HOSTILE_VALUE)[0],
        provider("acmedb", distribution=distributions[1], value="safe_module:register")[0],
    ]
    install_entry_points(entries)

    with pytest.raises(ValueError) as excinfo:
        main._resolve_adapter_registration("acmedb")

    message = str(excinfo.value)
    assert HOSTILE_VALUE not in message
    assert "hunter2" not in message
    assert "://" not in message
    assert "safe_module" not in message
    assert_nothing_loaded(entries)


def test_duplicate_declarations_from_one_distribution_are_reported_honestly(install_entry_points):
    # a duplicate install declares the same name twice from one distribution name; de-duplicating
    # the distribution must not make the message claim a single declaration
    entries = [
        provider("acmedb", distribution="one-dist", value="one_mod:register")[0],
        provider("acmedb", distribution="one-dist", value="two_mod:register")[0],
    ]
    install_entry_points(entries)

    with pytest.raises(ValueError) as excinfo:
        main._resolve_adapter_registration("acmedb")

    message = str(excinfo.value)
    assert repr("acmedb") in message
    assert "2 installed providers" in message
    assert f"{'one-dist'!r} (2 declarations)" in message
    assert_nothing_loaded(entries)


def test_duplicate_declarations_from_one_first_party_distribution_are_counted(install_entry_points):
    entries = [
        provider("acmedb", distribution=FIRST_PARTY, value="one_mod:register")[0],
        provider("acmedb", distribution=FIRST_PARTY, value="two_mod:register")[0],
    ]
    install_entry_points(entries)

    with pytest.raises(ValueError) as excinfo:
        main._resolve_adapter_registration("acmedb")

    message = str(excinfo.value)
    assert "packaging" in message
    assert f"{FIRST_PARTY!r} (2 declarations)" in message
    assert_nothing_loaded(entries)


def test_multiple_external_providers_fail_before_any_load_and_report_all(install_entry_points):
    entries = [provider("acmedb", distribution=name) for name in ("zeta-dist", "alpha-dist", "middle-dist")]
    install_entry_points([entry_point for entry_point, _ in entries])
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._resolve_adapter_registration("acmedb")

    message = str(excinfo.value)
    assert repr("acmedb") in message
    for distribution in ("zeta-dist", "alpha-dist", "middle-dist"):
        assert repr(distribution) in message
    assert "uninstall or rename" in message
    assert "://" not in message
    for entry_point, calls in entries:
        assert calls == []
        assert entry_point.load_calls == 0
    assert dict(main._adapter_registry) == before
    assert main._loaded_provider_registrations == {}


def test_duplicate_conflict_does_not_block_a_different_name(install_entry_points):
    conflicting = [provider("acmedb", distribution=name)[0] for name in ("one-dist", "two-dist")]
    healthy, healthy_calls = provider("otherdb", distribution="other-dist")
    install_entry_points(conflicting + [healthy])

    with pytest.raises(ValueError):
        main._resolve_adapter_registration("acmedb")

    assert main._resolve_adapter_registration("otherdb").name == "otherdb"
    assert healthy_calls == ["called"]
    assert_nothing_loaded(conflicting)


# ---------------------------------------------------------------------------- order independence


def test_reversed_enumeration_order_does_not_change_first_party_selection(install_entry_points):
    def resolve_with(order):
        entries = []
        chosen = {}
        for distribution in order:
            entry_point, calls = provider("acmedb", distribution=distribution)
            entries.append(entry_point)
            chosen[distribution] = calls
        install_entry_points(entries)
        registration = main._resolve_adapter_registration("acmedb")
        loaded = [distribution for distribution, calls in chosen.items() if calls == ["called"]]
        del main._adapter_registry["acmedb"]
        main._reset_provider_load_state_for_tests()
        return registration.name, loaded

    order = ["zeta-dist", FIRST_PARTY, "alpha-dist"]
    forward = resolve_with(order)
    backward = resolve_with(list(reversed(order)))

    assert forward == backward == ("acmedb", [FIRST_PARTY])


def test_reversed_enumeration_order_does_not_change_duplicate_errors(install_entry_points):
    def error_for(order):
        entries = [provider("acmedb", distribution=distribution)[0] for distribution in order]
        install_entry_points(entries)
        with pytest.raises(ValueError) as excinfo:
            main._resolve_adapter_registration("acmedb")
        assert_nothing_loaded(entries)
        return str(excinfo.value)

    order = ["zeta-dist", "alpha-dist", "middle-dist"]

    assert error_for(order) == error_for(list(reversed(order)))


def test_reversed_descriptor_order_does_not_change_selection():
    # the pure selector is exercised directly so ordering cannot be hidden by the catalog's sort
    descriptors = tuple(
        _AdapterProviderDescriptor(
            name="acmedb",
            distribution=distribution,
            entry_point=FakeEntryPoint("acmedb", distribution=distribution),
        )
        for distribution in ("zeta-dist", FIRST_PARTY, "alpha-dist")
    )

    forward = main._select_provider_descriptor("acmedb", descriptors)
    backward = main._select_provider_descriptor("acmedb", tuple(reversed(descriptors)))

    assert forward.distribution == backward.distribution == FIRST_PARTY
    assert_nothing_loaded([descriptor.entry_point for descriptor in descriptors])


# ---------------------------------------------------------------------------- no connection side effects


class ExplodingConnectCommands(MockCommands):
    @classmethod
    def connect(cls, parsed_dsn, **connect_kwargs):  # pragma: no cover - must never run
        raise AssertionError("connection factory must not run during resolution")


def test_resolution_never_calls_predicates_or_connection_factories(install_entry_points, monkeypatch):
    def must_not_run(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("connection selection must not run during resolution")

    for method in ("from_dsn", "from_dsn_async", "from_connection", "from_connection_async"):
        monkeypatch.setattr(main.CommandFactory, method, must_not_run)

    def predicate_must_not_run(connection):  # pragma: no cover - must never run
        raise AssertionError("predicate must not run during resolution")

    entry_point, _ = provider(
        "acmedb",
        commands=ExplodingConnectCommands,
        predicate=predicate_must_not_run,
    )
    install_entry_points([entry_point])

    registration = main._resolve_adapter_registration("acmedb")

    assert registration.using_connection_predicate is predicate_must_not_run
    assert registration.commands is ExplodingConnectCommands
    # a second resolution takes the already-registered path and must stay just as inert
    assert main._resolve_adapter_registration("acmedb") is registration


def test_resolution_does_not_consult_requested_mode(install_entry_points):
    # mode checks belong to a later slice: an async-only provider still resolves by name
    callback, calls = registering_callback("acmedb", commands=None, async_commands=MockAsyncCommands)
    entry_point = FakeEntryPoint("acmedb", loaded=callback)
    install_entry_points([entry_point])

    registration = main._resolve_adapter_registration("acmedb")

    assert calls == ["called"]
    assert registration.commands is None
    assert registration.async_commands is MockAsyncCommands


# ---------------------------------------------------------------------------- locking


def test_resolution_uses_the_definition_time_load_lock():
    original_lock = main._provider_load_lock
    assert main._resolve_adapter_registration.__kwdefaults__["_lock"] is original_lock
    assert main._load_adapter_provider.__kwdefaults__["_lock"] is original_lock
    assert main._register_adapter_under_lock.__kwdefaults__["_lock"] is original_lock


def test_concurrent_resolution_invokes_the_provider_once(install_entry_points):
    # the first worker to win the lock blocks inside the provider callback until the main thread
    # releases it, and the instrumented lock counts acquire attempts, so the callback is only
    # released once every other worker is provably blocked mid-resolution. An unlocked registry
    # check followed by a later load would invoke the callback more than once or trip an
    # incidental duplicate-registration error.
    thread_count = 4
    # the winner acquires twice (resolution, then the nested load) before it blocks, so every
    # other worker is at the lock exactly when attempts reach thread_count + 1
    expected_attempts = thread_count + 1
    start_barrier = threading.Barrier(thread_count + 1)
    first_entered = threading.Event()
    all_workers_at_lock = threading.Event()
    release = threading.Event()
    callback_calls = []

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

    def register():
        callback_calls.append("called")
        first_entered.set()
        assert release.wait(timeout=30)
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)

    entry_point = FakeEntryPoint("acmedb", loaded=register)
    install_entry_points([entry_point])
    shared_lock = CountingRLock()

    results = []
    errors = []

    def worker():
        try:
            start_barrier.wait(timeout=30)
            results.append(main._resolve_adapter_registration("acmedb", _lock=shared_lock))
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
    assert callback_calls == ["called"]
    assert entry_point.load_calls == 1
    assert len(results) == thread_count
    assert all(result is results[0] for result in results)
    assert main._adapter_registry["acmedb"] is results[0]


def test_registry_check_and_load_are_one_serialized_operation(install_entry_points, monkeypatch):
    # deterministic proof that resolution holds the lock across the whole decision: the registry
    # itself is gated so the first membership test for the name pauses mid-resolution, and a direct
    # register_adapter() on another thread is then provably blocked on the shared lock. A separate
    # unlocked check followed by a later load would let the direct registration land in between,
    # and the loader would fail the resolution with "refusing to load over the existing registration".
    checked = threading.Event()
    direct_attempt = threading.Event()
    release = threading.Event()

    class GatedRegistry(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.gated = False

        def __contains__(self, key):
            if key == "acmedb" and not self.gated:
                self.gated = True
                checked.set()
                assert release.wait(timeout=30)
            return super().__contains__(key)

    class CountingRLock:
        def __init__(self):
            self._inner = threading.RLock()
            self._count_guard = threading.Lock()
            self._acquire_attempts = 0

        def __enter__(self):
            with self._count_guard:
                self._acquire_attempts += 1
                if self._acquire_attempts >= 2:
                    direct_attempt.set()
            self._inner.acquire()
            return self

        def __exit__(self, *exc_info):
            self._inner.release()

    monkeypatch.setattr(main, "_adapter_registry", GatedRegistry(main._adapter_registry))
    shared_lock = CountingRLock()
    monkeypatch.setitem(main._register_adapter_under_lock.__kwdefaults__, "_lock", shared_lock)

    entry_point, calls = provider("acmedb")
    install_entry_points([entry_point])

    resolved = []
    resolve_errors = []
    direct_errors = []

    def resolving_worker():
        try:
            resolved.append(main._resolve_adapter_registration("acmedb", _lock=shared_lock))
        except Exception as exc:  # pragma: no cover - failure reporting only
            resolve_errors.append(exc)

    def direct_worker():
        try:
            pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
        except Exception as exc:
            direct_errors.append(exc)

    resolver = threading.Thread(target=resolving_worker)
    resolver.start()
    assert checked.wait(timeout=30)
    direct = threading.Thread(target=direct_worker)
    direct.start()
    # the direct registration is provably waiting on the shared lock while resolution is still
    # paused between its registry check and its load
    assert direct_attempt.wait(timeout=30)
    release.set()
    resolver.join(timeout=30)
    direct.join(timeout=30)
    assert not resolver.is_alive()
    assert not direct.is_alive()

    assert not resolve_errors
    assert calls == ["called"]
    assert len(resolved) == 1
    assert main._adapter_registry["acmedb"] is resolved[0]
    # the provider won the race outright; register_adapter() then hits the normal one-way error
    assert len(direct_errors) == 1
    assert "already registered" in str(direct_errors[0])


def test_concurrent_resolution_of_distinct_names_loads_each_provider_once(install_entry_points):
    names = ["acmedb", "otherdb", "thirddb"]
    entries = {}
    logs = {}
    for index, name in enumerate(names):
        entries[name], logs[name] = provider(name, distribution=f"dist-{index}")
    install_entry_points(entries.values())

    start_barrier = threading.Barrier(len(names))
    results = {}
    errors = []

    def worker(name):
        try:
            start_barrier.wait(timeout=30)
            results[name] = main._resolve_adapter_registration(name)
        except Exception as exc:  # pragma: no cover - failure reporting only
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(name,)) for name in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    for name in names:
        assert logs[name] == ["called"]
        assert entries[name].load_calls == 1
        assert main._adapter_registry[name] is results[name]


# ---------------------------------------------------------------------------- privacy


def test_resolution_adds_no_public_api():
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
    # every resolution symbol is private, pinned by the exact non-underscore surface of main rather
    # than by a substring guess. Plain stdlib/typing imports are the file's existing convention
    # (os, threading, inspect, logging, Callable, dataclass predate this slice).
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


def test_public_connection_paths_are_untouched_by_this_slice(install_entry_points):
    # integration is a later slice: an installed-but-unloaded provider must still be invisible to
    # the public name-based lookups
    entry_point, calls = provider("acmedb")
    install_entry_points([entry_point])

    with pytest.raises(ValueError) as excinfo:
        main._get_sync_commands_class("acmedb")
    assert "is registered" in str(excinfo.value)

    with pytest.raises(ValueError):
        main._get_async_commands_class("acmedb")

    assert calls == []
    assert_nothing_loaded([entry_point])
