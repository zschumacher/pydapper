import importlib.metadata
import sys
import threading
from dataclasses import dataclass
from dataclasses import field

import pytest

import pydapper
from pydapper import _adapter_discovery
from pydapper.main import _adapter_registry

pytestmark = pytest.mark.core

GROUP = "pydapper.adapters"


@dataclass
class FakeDistribution:
    name: object


@dataclass
class FakeEntryPoint:
    name: object
    value: str = "pydapper_fake_provider_should_not_import.plugin:register"
    group: str = GROUP
    dist: object = field(default_factory=lambda: FakeDistribution("acme-adapter"))
    load_calls: int = 0

    def load(self):
        self.load_calls += 1
        raise AssertionError("EntryPoint.load() must not be called during discovery")


class FakeEntryPoints:
    """Stands in for importlib.metadata.entry_points; records group requests."""

    def __init__(self, entries):
        self.entries = list(entries)
        self.calls = []

    def __call__(self, *, group):
        self.calls.append(group)
        return [ep for ep in self.entries if ep.group == group]


@pytest.fixture(autouse=True)
def reset_catalog():
    _adapter_discovery._reset_provider_catalog_for_tests()
    yield
    _adapter_discovery._reset_provider_catalog_for_tests()


@pytest.fixture
def install_entry_points(monkeypatch):
    def install(entries):
        fake = FakeEntryPoints(entries)
        monkeypatch.setattr(importlib.metadata, "entry_points", fake)
        return fake

    return install


def test_only_exact_group_is_selected(install_entry_points):
    fake = install_entry_points(
        [
            FakeEntryPoint("acmedb"),
            FakeEntryPoint("otherdb", group="pydapper.adapters.extra"),
            FakeEntryPoint("console", group="console_scripts"),
        ]
    )
    catalog = _adapter_discovery._get_provider_catalog()
    assert fake.calls == [GROUP]
    assert set(catalog) == {"acmedb"}


def test_mixed_group_enumeration_result_is_filtered(monkeypatch):
    entries = [FakeEntryPoint("acmedb"), FakeEntryPoint("stray", group="console_scripts")]
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: list(entries))
    catalog = _adapter_discovery._get_provider_catalog()
    assert set(catalog) == {"acmedb"}


def test_discovery_never_loads_imports_or_registers(install_entry_points):
    entries = [FakeEntryPoint("acmedb"), FakeEntryPoint("acmedb", dist=FakeDistribution("other-dist"))]
    install_entry_points(entries)
    registry_before = dict(_adapter_registry)

    _adapter_discovery._get_provider_catalog()

    assert all(ep.load_calls == 0 for ep in entries)
    assert "pydapper_fake_provider_should_not_import" not in sys.modules
    assert "pydapper_fake_provider_should_not_import.plugin" not in sys.modules
    assert dict(_adapter_registry) == registry_before


def test_successful_catalog_is_cached_without_reenumeration(install_entry_points):
    fake = install_entry_points([FakeEntryPoint("acmedb")])
    first = _adapter_discovery._get_provider_catalog()
    second = _adapter_discovery._get_provider_catalog()
    assert first is second
    assert fake.calls == [GROUP]


def test_cached_catalog_is_protected_from_mutation(install_entry_points):
    install_entry_points([FakeEntryPoint("acmedb")])
    catalog = _adapter_discovery._get_provider_catalog()
    with pytest.raises(TypeError):
        catalog["acmedb"] = ()  # type: ignore[index]
    assert isinstance(catalog["acmedb"], tuple)
    with pytest.raises(Exception):
        catalog["acmedb"][0].name = "other"  # type: ignore[misc]


@pytest.mark.parametrize("bad_name", ["", " acmedb", "acmedb ", "\tacmedb\n"])
def test_invalid_names_fail(install_entry_points, bad_name):
    install_entry_points([FakeEntryPoint(bad_name)])
    with pytest.raises(ValueError) as excinfo:
        _adapter_discovery._get_provider_catalog()
    assert repr(bad_name) in str(excinfo.value) or GROUP in str(excinfo.value)


def test_non_string_name_fails_with_type_error(install_entry_points):
    install_entry_points([FakeEntryPoint(123)])
    with pytest.raises(TypeError) as excinfo:
        _adapter_discovery._get_provider_catalog()
    assert GROUP in str(excinfo.value)


def test_case_hyphen_and_underscore_names_stay_distinct(install_entry_points):
    install_entry_points(
        [
            FakeEntryPoint("AcmeDB"),
            FakeEntryPoint("acmedb"),
            FakeEntryPoint("acme-db"),
            FakeEntryPoint("acme_db"),
        ]
    )
    catalog = _adapter_discovery._get_provider_catalog()
    assert set(catalog) == {"AcmeDB", "acmedb", "acme-db", "acme_db"}
    assert all(len(providers) == 1 for providers in catalog.values())


def test_duplicate_exact_names_retain_every_provider(install_entry_points):
    install_entry_points(
        [
            FakeEntryPoint("acmedb", dist=FakeDistribution("zeta-dist")),
            FakeEntryPoint("acmedb", dist=FakeDistribution("alpha-dist")),
        ]
    )
    catalog = _adapter_discovery._get_provider_catalog()
    assert [p.distribution for p in catalog["acmedb"]] == ["alpha-dist", "zeta-dist"]
    assert all(isinstance(p.entry_point, FakeEntryPoint) for p in catalog["acmedb"])


def test_enumeration_order_does_not_change_catalog(install_entry_points):
    entries = [
        FakeEntryPoint("acmedb", value="zeta_mod:register", dist=FakeDistribution("zeta-dist")),
        FakeEntryPoint("acmedb", value="beta_mod:register", dist=FakeDistribution("alpha-dist")),
        FakeEntryPoint("acmedb", value="alpha_mod:register", dist=FakeDistribution("alpha-dist")),
        FakeEntryPoint("otherdb", value="other_mod:register", dist=FakeDistribution("other-dist")),
    ]
    install_entry_points(entries)
    forward = _adapter_discovery._get_provider_catalog()

    _adapter_discovery._reset_provider_catalog_for_tests()
    install_entry_points(list(reversed(entries)))
    reversed_order = _adapter_discovery._get_provider_catalog()

    def full_metadata(catalog):
        return {
            name: [(p.name, p.distribution, p.entry_point.value, p.entry_point.group) for p in providers]
            for name, providers in catalog.items()
        }

    assert list(forward) == list(reversed_order) == ["acmedb", "otherdb"]
    assert full_metadata(forward) == full_metadata(reversed_order)
    # secondary entry-point-value key breaks the tie between same-distribution providers
    assert [(p.distribution, p.entry_point.value) for p in forward["acmedb"]] == [
        ("alpha-dist", "alpha_mod:register"),
        ("alpha-dist", "beta_mod:register"),
        ("zeta-dist", "zeta_mod:register"),
    ]


def test_distribution_provenance_is_retained(install_entry_points):
    install_entry_points([FakeEntryPoint("acmedb", dist=FakeDistribution("acme-adapter"))])
    provider = _adapter_discovery._get_provider_catalog()["acmedb"][0]
    assert provider.distribution == "acme-adapter"
    assert provider.name == "acmedb"


@pytest.mark.parametrize("dist", [None, FakeDistribution(None), FakeDistribution(""), FakeDistribution(" pkg ")])
def test_missing_or_malformed_distribution_fails(install_entry_points, dist):
    install_entry_points([FakeEntryPoint("acmedb", dist=dist)])
    with pytest.raises(ValueError) as excinfo:
        _adapter_discovery._get_provider_catalog()
    assert "acmedb" in str(excinfo.value)


def test_raising_distribution_metadata_access_is_wrapped_with_context(install_entry_points):
    original = RuntimeError("metadata read failed")

    class RaisingDistEntryPoint(FakeEntryPoint):
        @property
        def dist(self):
            raise original

        @dist.setter
        def dist(self, value):  # allow dataclass __init__ assignment
            pass

    install_entry_points([RaisingDistEntryPoint("acmedb")])
    with pytest.raises(ValueError) as excinfo:
        _adapter_discovery._get_provider_catalog()
    assert excinfo.value.__cause__ is original
    assert "acmedb" in str(excinfo.value)
    assert GROUP in str(excinfo.value)


def test_iteration_time_enumeration_failure_is_wrapped(monkeypatch):
    original = RuntimeError("iteration exploded")

    def failing_iterable():
        yield FakeEntryPoint("acmedb")
        raise original

    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: failing_iterable())
    with pytest.raises(ValueError) as excinfo:
        _adapter_discovery._get_provider_catalog()
    assert excinfo.value.__cause__ is original
    assert GROUP in str(excinfo.value)


def test_enumeration_failure_preserves_cause_and_is_not_cached(monkeypatch):
    original = RuntimeError("metadata backend exploded")

    def broken(*, group):
        raise original

    monkeypatch.setattr(importlib.metadata, "entry_points", broken)
    with pytest.raises(ValueError) as excinfo:
        _adapter_discovery._get_provider_catalog()
    assert excinfo.value.__cause__ is original
    assert GROUP in str(excinfo.value)

    fake = FakeEntryPoints([FakeEntryPoint("acmedb")])
    monkeypatch.setattr(importlib.metadata, "entry_points", fake)
    catalog = _adapter_discovery._get_provider_catalog()
    assert set(catalog) == {"acmedb"}


def test_validation_failure_is_not_cached_and_retry_succeeds(monkeypatch):
    fake = FakeEntryPoints([FakeEntryPoint("")])
    monkeypatch.setattr(importlib.metadata, "entry_points", fake)
    with pytest.raises(ValueError):
        _adapter_discovery._get_provider_catalog()

    fake.entries = [FakeEntryPoint("acmedb")]
    catalog = _adapter_discovery._get_provider_catalog()
    assert set(catalog) == {"acmedb"}
    assert fake.calls == [GROUP, GROUP]


def test_concurrent_first_discovery_enumerates_exactly_once(monkeypatch):
    # the first worker to win the discovery lock blocks inside enumeration until the main thread
    # releases it, and the lock is instrumented to count acquire attempts, so enumeration is only
    # released once every other worker is provably blocked on the lock with the catalog still
    # unbuilt; a non-serialized implementation would then enumerate more than once
    thread_count = 4
    start_barrier = threading.Barrier(thread_count + 1)
    first_entered = threading.Event()
    all_workers_at_lock = threading.Event()
    release = threading.Event()
    calls = []

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

    def blocking_entry_points(*, group):
        calls.append(group)
        first_entered.set()
        assert release.wait(timeout=30)
        return [FakeEntryPoint("acmedb")]

    monkeypatch.setattr(importlib.metadata, "entry_points", blocking_entry_points)
    monkeypatch.setattr(_adapter_discovery, "_catalog_lock", CountingLock(threading.Lock()))

    results = []
    errors = []

    def worker():
        try:
            start_barrier.wait(timeout=30)
            results.append(_adapter_discovery._get_provider_catalog())
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
    assert calls == [GROUP]
    assert len(results) == thread_count
    assert all(catalog is results[0] for catalog in results)


def test_no_public_package_root_symbol_added():
    public_names = [name for name in vars(pydapper) if not name.startswith("_")]
    assert not any("discover" in name.lower() or "catalog" in name.lower() for name in public_names)
    assert "_adapter_discovery" not in getattr(pydapper, "__all__", [])
