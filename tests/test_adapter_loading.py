import importlib.metadata
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


class FakeEntryPoint:
    """Loading-slice sibling of the discovery test fakes: load() actually returns a callback."""

    def __init__(self, name, loaded=None, value="fake_provider_module:register", group=GROUP, load_error=None):
        self.name = name
        self.loaded = loaded
        self.value = value
        self.group = group
        self.load_error = load_error
        self.load_calls = 0

    def load(self):
        self.load_calls += 1
        if self.load_error is not None:
            raise self.load_error
        return self.loaded


def make_descriptor(
    name="acmedb",
    *,
    loaded=None,
    distribution="acme-adapter",
    load_error=None,
    value="fake_provider_module:register",
):
    entry_point = FakeEntryPoint(name, loaded=loaded, value=value, load_error=load_error)
    return _AdapterProviderDescriptor(name=name, distribution=distribution, entry_point=entry_point)


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


class MustNotAcquireLock:
    """Stands in for a hostile replacement of the private load lock."""

    def __enter__(self):  # pragma: no cover - must never run
        raise AssertionError("replacement load lock must never be acquired")

    def __exit__(self, *exc_info):  # pragma: no cover - must never run
        raise AssertionError("replacement load lock must never be released")


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    registry = main._adapter_registry.copy()
    monkeypatch.setattr(main, "_adapter_registry", registry)
    original_lock = main._provider_load_lock
    main._reset_provider_load_state_for_tests()
    yield registry
    main._provider_load_lock = original_lock
    main._reset_provider_load_state_for_tests()


def assert_registry_exactly(before):
    assert list(main._adapter_registry) == list(before)
    for name, registration in before.items():
        assert main._adapter_registry[name] is registration


def assert_failed_attempt(excinfo, before, *, name, distribution, cause=None):
    message = str(excinfo.value)
    assert repr(name) in message
    assert repr(distribution) in message
    assert "://" not in message
    if cause is not None:
        assert excinfo.value.__cause__ is cause
    assert_registry_exactly(before)
    assert main._loaded_provider_registrations == {}


# ---------------------------------------------------------------------------- successful behavior


def test_successful_load_calls_load_and_callback_exactly_once():
    callback, calls = registering_callback("acmedb")
    descriptor = make_descriptor("acmedb", loaded=callback)

    registration = main._load_adapter_provider(descriptor)

    assert descriptor.entry_point.load_calls == 1
    assert calls == ["called"]
    assert main._adapter_registry["acmedb"] is registration


def test_sync_only_registration_succeeds():
    callback, _ = registering_callback("acmedb", commands=MockCommands)

    registration = main._load_adapter_provider(make_descriptor("acmedb", loaded=callback))

    assert isinstance(registration, main._AdapterRegistration)
    assert registration.name == "acmedb"
    assert registration.commands is MockCommands
    assert registration.async_commands is None


def test_async_only_registration_succeeds():
    callback, _ = registering_callback("acmedb", commands=None, async_commands=MockAsyncCommands)

    registration = main._load_adapter_provider(make_descriptor("acmedb", loaded=callback))

    assert registration.commands is None
    assert registration.async_commands is MockAsyncCommands


def test_combined_registration_succeeds():
    callback, _ = registering_callback("acmedb", commands=MockCommands, async_commands=MockAsyncCommands)

    registration = main._load_adapter_provider(make_descriptor("acmedb", loaded=callback))

    assert registration.commands is MockCommands
    assert registration.async_commands is MockAsyncCommands


def test_returned_registration_is_the_registered_record():
    callback, _ = registering_callback("acmedb")

    registration = main._load_adapter_provider(make_descriptor("acmedb", loaded=callback))

    assert main._adapter_registry["acmedb"] is registration


def test_repeated_load_returns_cached_registration_without_reinvoking():
    callback, calls = registering_callback("acmedb")
    descriptor = make_descriptor("acmedb", loaded=callback)

    first = main._load_adapter_provider(descriptor)
    second = main._load_adapter_provider(descriptor)

    assert first is second
    assert descriptor.entry_point.load_calls == 1
    assert calls == ["called"]


def test_successful_load_preserves_unrelated_registrations():
    before = dict(main._adapter_registry)
    callback, _ = registering_callback("acmedb")

    main._load_adapter_provider(make_descriptor("acmedb", loaded=callback))

    assert set(main._adapter_registry) == set(before) | {"acmedb"}
    for name, registration in before.items():
        assert main._adapter_registry[name] is registration


def test_cached_success_must_stay_coherent_with_registry():
    callback, calls = registering_callback("acmedb")
    descriptor = make_descriptor("acmedb", loaded=callback)
    main._load_adapter_provider(descriptor)

    del main._adapter_registry["acmedb"]

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)
    assert calls == ["called"]
    assert repr("acmedb") in str(excinfo.value)
    assert repr("acme-adapter") in str(excinfo.value)


def test_provider_identity_is_never_normalized():
    hyphen_callback, hyphen_calls = registering_callback("acme-db")
    underscore_callback, underscore_calls = registering_callback("acme_db")

    hyphen = main._load_adapter_provider(make_descriptor("acme-db", loaded=hyphen_callback))
    underscore = main._load_adapter_provider(make_descriptor("acme_db", loaded=underscore_callback))

    assert hyphen_calls == ["called"]
    assert underscore_calls == ["called"]
    assert main._adapter_registry["acme-db"] is hyphen
    assert main._adapter_registry["acme_db"] is underscore


def test_success_cache_is_per_provider_identity_not_per_name():
    callback, _ = registering_callback("acmedb")
    loaded = main._load_adapter_provider(
        make_descriptor("acmedb", loaded=callback, distribution="first-dist", value="first_mod:register")
    )

    other_callback, other_calls = registering_callback("acmedb")
    other = make_descriptor("acmedb", loaded=other_callback, distribution="second-dist", value="second_mod:register")

    with pytest.raises(ValueError):
        main._load_adapter_provider(other)
    assert other_calls == []
    assert main._adapter_registry["acmedb"] is loaded


def test_concurrent_loads_invoke_load_and_callback_exactly_once():
    # the first worker to win the load lock blocks inside the provider callback until the main
    # thread releases it, and the lock is instrumented to count acquire attempts, so the callback
    # is only released once every other worker is provably blocked on the lock mid-load; a
    # non-serialized implementation would invoke the callback more than once or trip an
    # incidental duplicate-registration error
    thread_count = 4
    start_barrier = threading.Barrier(thread_count + 1)
    first_entered = threading.Event()
    all_workers_at_lock = threading.Event()
    release = threading.Event()
    callback_calls = []

    class CountingLock:
        def __init__(self, inner):
            self._inner = inner
            self._count_guard = threading.Lock()
            self._acquire_attempts = 0

        def __enter__(self):
            with self._count_guard:
                self._acquire_attempts += 1
                if self._acquire_attempts >= thread_count:
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

    descriptor = make_descriptor("acmedb", loaded=register)
    shared_lock = CountingLock(threading.Lock())

    results = []
    errors = []

    def worker():
        try:
            start_barrier.wait(timeout=30)
            results.append(main._load_adapter_provider(descriptor, _lock=shared_lock))
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
        thread.join()

    assert not errors
    assert callback_calls == ["called"]
    assert descriptor.entry_point.load_calls == 1
    assert len(results) == thread_count
    assert all(result is results[0] for result in results)
    assert main._adapter_registry["acmedb"] is results[0]


def test_callback_rebinding_the_load_lock_is_inert_for_later_loads():
    original_lock = main._provider_load_lock
    # production callers share the original lock through the definition-time default, so a
    # rebound module global is never read at call time
    assert main._load_adapter_provider.__kwdefaults__["_lock"] is original_lock
    assert main._reset_provider_load_state_for_tests.__kwdefaults__["_lock"] is original_lock

    def register():
        main._provider_load_lock = MustNotAcquireLock()
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)

    descriptor = make_descriptor("acmedb", loaded=register)
    registration = main._load_adapter_provider(descriptor)

    # the cached-hit path, a fresh load, and the test reset would all raise if any of them
    # acquired the hostile replacement instead of the definition-time lock
    assert main._load_adapter_provider(descriptor) is registration
    other_callback, other_calls = registering_callback("otherdb")
    main._load_adapter_provider(make_descriptor("otherdb", loaded=other_callback))
    assert other_calls == ["called"]
    main._reset_provider_load_state_for_tests()
    assert isinstance(main._provider_load_lock, MustNotAcquireLock)


def test_failing_callback_rebinding_the_load_lock_keeps_future_loads_usable():
    behavior = {"fail": True}

    def register():
        if behavior["fail"]:
            main._provider_load_lock = MustNotAcquireLock()
            raise RuntimeError("fail after swapping the lock")
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)

    descriptor = make_descriptor("acmedb", loaded=register)

    with pytest.raises(ValueError):
        main._load_adapter_provider(descriptor)

    behavior["fail"] = False
    registration = main._load_adapter_provider(descriptor)

    assert main._adapter_registry["acmedb"] is registration


def test_concurrent_caller_is_not_unblocked_by_lock_rebinding_during_callback():
    # deterministic repro of the reported attack: while the first caller holds the original
    # load lock inside a callback that rebinds main._provider_load_lock, a second caller for
    # the same provider must still serialize on the original lock (which production callers
    # share via the definition-time default) and must never acquire the replacement
    in_callback = threading.Event()
    second_attempt = threading.Event()
    release = threading.Event()
    callback_calls = []

    class CountingLock:
        def __init__(self, inner):
            self._inner = inner
            self._count_guard = threading.Lock()
            self._acquire_attempts = 0

        def __enter__(self):
            with self._count_guard:
                self._acquire_attempts += 1
                if self._acquire_attempts >= 2:
                    second_attempt.set()
            self._inner.acquire()
            return self

        def __exit__(self, *exc_info):
            self._inner.release()

    shared_lock = CountingLock(threading.Lock())

    def register():
        callback_calls.append("called")
        main._provider_load_lock = MustNotAcquireLock()
        in_callback.set()
        assert release.wait(timeout=30)
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)

    descriptor = make_descriptor("acmedb", loaded=register)
    results = []
    errors = []

    def worker():
        try:
            results.append(main._load_adapter_provider(descriptor, _lock=shared_lock))
        except Exception as exc:  # pragma: no cover - failure reporting only
            errors.append(exc)

    first = threading.Thread(target=worker)
    first.start()
    assert in_callback.wait(timeout=30)
    second = threading.Thread(target=worker)
    second.start()
    # the second caller is provably attempting the original lock, not the replacement, while
    # the first caller is still paused inside the callback after the rebinding
    assert second_attempt.wait(timeout=30)
    release.set()
    first.join(timeout=30)
    second.join(timeout=30)

    assert not errors
    assert callback_calls == ["called"]
    assert descriptor.entry_point.load_calls == 1
    assert len(results) == 2
    assert results[0] is results[1]
    assert main._adapter_registry["acmedb"] is results[0]


# ---------------------------------------------------------------------------- load/callback failures


def test_load_failure_is_wrapped_with_context_and_cause():
    original = ImportError("no module named fake_provider_module")
    descriptor = make_descriptor("acmedb", load_error=original)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter", cause=original)


def test_non_callable_loaded_object_fails_without_registry_mutation():
    descriptor = make_descriptor("acmedb", loaded=object())
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_callback_requiring_an_argument_fails_with_typeerror_cause():
    def register(required):  # pragma: no cover - never invocable without an argument
        raise AssertionError("should never run")

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert isinstance(excinfo.value.__cause__, TypeError)
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_callback_internal_typeerror_is_reported_as_callback_failure():
    original = TypeError("internal type problem")

    def register():
        raise original

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter", cause=original)


def test_callback_exception_is_preserved_as_cause():
    original = RuntimeError("provider blew up")

    def register():
        raise original

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter", cause=original)


def test_callback_exception_after_registration_rolls_back():
    original = RuntimeError("post-registration failure")

    def register():
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
        raise original

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert "acmedb" not in main._adapter_registry
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter", cause=original)


@pytest.mark.filterwarnings("error::RuntimeWarning")
def test_async_callback_is_rejected_without_invocation():
    ran = []

    async def register():  # pragma: no cover - must never be invoked
        ran.append("ran")

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert ran == []
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


@pytest.mark.filterwarnings("error::RuntimeWarning")
def test_async_generator_callback_is_rejected_without_invocation():
    async def register():  # pragma: no cover - must never be invoked
        yield

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_base_exception_from_callback_rolls_back_and_propagates():
    def register():
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
        raise KeyboardInterrupt

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(KeyboardInterrupt):
        main._load_adapter_provider(descriptor)

    assert "acmedb" not in main._adapter_registry
    assert_registry_exactly(before)
    assert main._loaded_provider_registrations == {}


@pytest.mark.filterwarnings("error::RuntimeWarning")
def test_awaitable_callback_return_is_rejected_safely_and_rolled_back():
    async def async_register():  # pragma: no cover - never awaited
        return None

    def register():
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
        return async_register()

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert "acmedb" not in main._adapter_registry
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_non_none_return_is_rejected_and_rolled_back():
    def register():
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
        return "unexpected"

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert "acmedb" not in main._adapter_registry
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


# ---------------------------------------------------------------------------- registry postconditions


def test_callback_registering_nothing_fails():
    descriptor = make_descriptor("acmedb", loaded=lambda: None)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_callback_registering_a_different_name_fails_and_is_removed():
    wrong_callback, _ = registering_callback("not-acmedb")
    descriptor = make_descriptor("acmedb", loaded=wrong_callback)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert "not-acmedb" not in main._adapter_registry
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_callback_registering_multiple_names_fails_and_removes_all():
    def register():
        pydapper.register_adapter("acmedb-one", commands=MockCommands, using_connection_predicate=never_matches)
        pydapper.register_adapter("acmedb-two", commands=MockCommands, using_connection_predicate=never_matches)

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert "acmedb-one" not in main._adapter_registry
    assert "acmedb-two" not in main._adapter_registry
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_callback_registering_expected_name_plus_extra_fails_and_removes_both():
    def register():
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
        pydapper.register_adapter("acmedb-extra", commands=MockCommands, using_connection_predicate=never_matches)

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert "acmedb" not in main._adapter_registry
    assert "acmedb-extra" not in main._adapter_registry
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_callback_removing_an_existing_registration_fails_and_restores_it():
    removed_name = "sqlite3"
    original_record = main._adapter_registry[removed_name]

    def register():
        del main._adapter_registry[removed_name]
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert main._adapter_registry[removed_name] is original_record
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_callback_replacing_an_existing_registration_fails_and_restores_it():
    target = "sqlite3"
    original_record = main._adapter_registry[target]

    def register():
        main._adapter_registry[target] = main._AdapterRegistration(
            name=target,
            commands=MockCommands,
            async_commands=None,
            using_connection_predicate=never_matches,
        )
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert main._adapter_registry[target] is original_record
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_callback_reordering_existing_registrations_fails_and_restores_order():
    assert len(main._adapter_registry) >= 2
    first_name = next(iter(main._adapter_registry))
    original_record = main._adapter_registry[first_name]

    def register():
        record = main._adapter_registry.pop(first_name)
        main._adapter_registry[first_name] = record
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert next(iter(main._adapter_registry)) == first_name
    assert main._adapter_registry[first_name] is original_record
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_callback_rebinding_the_registry_fails_and_restores_the_binding(isolated_registry):
    def register():
        main._adapter_registry = {
            "acmedb": main._AdapterRegistration(
                name="acmedb",
                commands=MockCommands,
                async_commands=None,
                using_connection_predicate=never_matches,
            )
        }

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(isolated_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert main._adapter_registry is isolated_registry
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_callback_rebinding_the_registry_and_raising_still_rolls_back(isolated_registry):
    original = RuntimeError("provider exploded after rebinding")

    def register():
        main._adapter_registry = None
        raise original

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(isolated_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert main._adapter_registry is isolated_registry
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter", cause=original)


def test_direct_insertion_of_an_invalid_registry_object_fails_and_rolls_back():
    def register():
        main._adapter_registry["acmedb"] = object()

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert "acmedb" not in main._adapter_registry
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_direct_insertion_with_invalid_contents_fails_and_preserves_cause():
    def register():
        main._adapter_registry["acmedb"] = main._AdapterRegistration(
            name="acmedb",
            commands=MockCommands,
            async_commands=None,
            using_connection_predicate=None,
        )

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert isinstance(excinfo.value.__cause__, TypeError)
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_direct_insertion_with_mismatched_internal_name_fails():
    def register():
        main._adapter_registry["acmedb"] = main._AdapterRegistration(
            name="other-name",
            commands=MockCommands,
            async_commands=None,
            using_connection_predicate=never_matches,
        )

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


class RaisingCapabilitiesDescriptor:
    def __get__(self, obj, objtype=None):
        raise RuntimeError("capabilities read exploded")


class ExplodingCapabilityCommands(MockCommands):
    capabilities = RaisingCapabilitiesDescriptor()


def test_unexpected_validation_exception_is_wrapped_with_context_and_rolled_back():
    def register():
        main._adapter_registry["acmedb"] = main._AdapterRegistration(
            name="acmedb",
            commands=ExplodingCapabilityCommands,
            async_commands=None,
            using_connection_predicate=never_matches,
        )

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert isinstance(excinfo.value.__cause__, RuntimeError)
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


class BadCapabilityCommands(MockCommands):
    capabilities = ["not-a-frozenset"]


def test_invalid_capabilities_via_register_adapter_fail_and_preserve_cause():
    def register():
        pydapper.register_adapter("acmedb", commands=BadCapabilityCommands, using_connection_predicate=never_matches)

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert isinstance(excinfo.value.__cause__, TypeError)
    assert "capabilities" in str(excinfo.value.__cause__)
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_duplicate_registration_failure_leaves_registry_unchanged():
    def register():
        pydapper.register_adapter("sqlite3", commands=MockCommands, using_connection_predicate=never_matches)

    descriptor = make_descriptor("acmedb", loaded=register)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert isinstance(excinfo.value.__cause__, ValueError)
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_directly_registered_name_is_not_overwritten_or_claimed_as_provider_success():
    pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)
    direct_record = main._adapter_registry["acmedb"]
    callback, calls = registering_callback("acmedb")
    descriptor = make_descriptor("acmedb", loaded=callback)
    before = dict(main._adapter_registry)

    with pytest.raises(ValueError) as excinfo:
        main._load_adapter_provider(descriptor)

    assert descriptor.entry_point.load_calls == 0
    assert calls == []
    assert main._adapter_registry["acmedb"] is direct_record
    assert_failed_attempt(excinfo, before, name="acmedb", distribution="acme-adapter")


def test_failing_callback_cannot_poison_the_success_cache():
    behavior = {"fail": True}
    calls = []

    def register():
        calls.append("called")
        if behavior["fail"]:
            main._loaded_provider_registrations[main._provider_load_state_key(descriptor)] = object()
            raise RuntimeError("fail after poisoning the cache")
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)

    descriptor = make_descriptor("acmedb", loaded=register)

    with pytest.raises(ValueError):
        main._load_adapter_provider(descriptor)
    assert main._loaded_provider_registrations == {}

    behavior["fail"] = False
    registration = main._load_adapter_provider(descriptor)

    assert calls == ["called", "called"]
    assert main._adapter_registry["acmedb"] is registration


def test_callback_tampering_with_the_success_cache_is_discarded_on_success():
    original_cache = main._loaded_provider_registrations

    def register():
        main._loaded_provider_registrations = {("poison", "poison", "poison"): object()}
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)

    descriptor = make_descriptor("acmedb", loaded=register)

    registration = main._load_adapter_provider(descriptor)

    assert main._loaded_provider_registrations is original_cache
    assert main._loaded_provider_registrations == {main._provider_load_state_key(descriptor): registration}


# ---------------------------------------------------------------------------- retryability


def test_load_failure_is_retryable():
    callback, calls = registering_callback("acmedb")
    descriptor = make_descriptor("acmedb", loaded=callback, load_error=RuntimeError("import exploded"))

    with pytest.raises(ValueError):
        main._load_adapter_provider(descriptor)
    assert main._loaded_provider_registrations == {}

    descriptor.entry_point.load_error = None
    registration = main._load_adapter_provider(descriptor)

    assert descriptor.entry_point.load_calls == 2
    assert calls == ["called"]
    assert main._adapter_registry["acmedb"] is registration


def test_callback_failure_is_retryable_and_retry_invokes_the_callback():
    behavior = {"fail": True}
    calls = []

    def register():
        calls.append("called")
        if behavior["fail"]:
            raise RuntimeError("first attempt fails")
        pydapper.register_adapter("acmedb", commands=MockCommands, using_connection_predicate=never_matches)

    descriptor = make_descriptor("acmedb", loaded=register)

    with pytest.raises(ValueError):
        main._load_adapter_provider(descriptor)
    assert main._loaded_provider_registrations == {}

    behavior["fail"] = False
    registration = main._load_adapter_provider(descriptor)

    assert calls == ["called", "called"]
    assert main._adapter_registry["acmedb"] is registration


def test_postcondition_failure_is_retryable():
    behavior = {"name": "wrong-name"}

    def register():
        pydapper.register_adapter(behavior["name"], commands=MockCommands, using_connection_predicate=never_matches)

    descriptor = make_descriptor("acmedb", loaded=register)

    with pytest.raises(ValueError):
        main._load_adapter_provider(descriptor)
    assert "wrong-name" not in main._adapter_registry
    assert main._loaded_provider_registrations == {}

    behavior["name"] = "acmedb"
    registration = main._load_adapter_provider(descriptor)

    assert main._adapter_registry["acmedb"] is registration
    assert "wrong-name" not in main._adapter_registry


# ---------------------------------------------------------------------------- privacy and separation


def test_loading_does_not_enumerate_the_catalog(monkeypatch):
    _adapter_discovery._reset_provider_catalog_for_tests()

    def fail_enumeration(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("provider loading must not enumerate entry points")

    monkeypatch.setattr(importlib.metadata, "entry_points", fail_enumeration)
    callback, calls = registering_callback("acmedb")

    main._load_adapter_provider(make_descriptor("acmedb", loaded=callback))

    assert calls == ["called"]
    assert _adapter_discovery._catalog is None


def test_loading_one_descriptor_ignores_same_name_duplicates():
    other_callback, other_calls = registering_callback("acmedb")
    other = make_descriptor("acmedb", loaded=other_callback, distribution="other-dist", value="other_mod:register")
    chosen_callback, chosen_calls = registering_callback("acmedb")
    chosen = make_descriptor("acmedb", loaded=chosen_callback)

    main._load_adapter_provider(chosen)

    assert chosen_calls == ["called"]
    assert other_calls == []
    assert other.entry_point.load_calls == 0


def test_loading_never_calls_connection_paths_or_predicates(monkeypatch):
    def must_not_run(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("connection selection must not run during provider loading")

    for method in ("from_dsn", "from_dsn_async", "from_connection", "from_connection_async"):
        monkeypatch.setattr(main.CommandFactory, method, must_not_run)

    def predicate_must_not_run(connection):  # pragma: no cover - must never run
        raise AssertionError("predicate must not run during provider loading")

    callback, _ = registering_callback("acmedb", predicate=predicate_must_not_run)

    registration = main._load_adapter_provider(make_descriptor("acmedb", loaded=callback))

    assert registration.using_connection_predicate is predicate_must_not_run


def test_no_new_public_package_root_api():
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


def test_shared_validation_order_is_preserved_with_multiple_invalid_fields():
    # pins the check order of the validation shared by register_adapter() and provider
    # postconditions so the extraction cannot silently reorder public behavior
    with pytest.raises(ValueError) as excinfo:
        pydapper.register_adapter("sqlite3", commands=object, using_connection_predicate=None)
    assert "already registered" in str(excinfo.value)

    with pytest.raises(ValueError) as excinfo:
        pydapper.register_adapter("new-name", using_connection_predicate=None)
    assert "At least one sync or async command class" in str(excinfo.value)

    with pytest.raises(TypeError) as excinfo:
        pydapper.register_adapter("new-name", commands=object, async_commands=object, using_connection_predicate=None)
    assert "commands must be a Commands subclass" in str(excinfo.value)

    with pytest.raises(TypeError) as excinfo:
        pydapper.register_adapter(
            "new-name", commands=MockCommands, async_commands=object, using_connection_predicate=None
        )
    assert "async_commands must be a CommandsAsync subclass" in str(excinfo.value)

    with pytest.raises(TypeError) as excinfo:
        pydapper.register_adapter("new-name", commands=BadCapabilityCommands, using_connection_predicate=None)
    assert "using_connection_predicate must be callable" in str(excinfo.value)

    assert "new-name" not in main._adapter_registry
