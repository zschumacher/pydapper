"""Integration coverage for name-based public adapter resolution.

Exercises the real public entry points -- ``connect()``, ``connect_async()``,
``using(adapter=)``, and ``using_async(adapter=)`` -- against the real discovery
catalog, the real ``_resolve_adapter_registration()``, and the real
``_load_adapter_provider()`` composition. The resolver is never monkeypatched
here; only installed entry-point metadata is faked, so these tests fail if any
part of that composition stops being wired into a public path.

Private precedence, enumeration order, transactional rollback, hostile
callbacks, and loader-cache corruption already have dedicated coverage in
tests/test_adapter_resolution.py and tests/test_adapter_loading.py and are not
duplicated here.
"""

import importlib.metadata
import inspect
import logging
from types import SimpleNamespace

import pytest

import pydapper
import pydapper.main as main
from pydapper import _adapter_discovery
from pydapper._context import _AwaitableAsyncContextManager
from pydapper.dsn_parser import PydapperParseResult
from tests.mocks import MockAsyncCommands
from tests.mocks import MockAsyncConnection
from tests.mocks import MockCommands
from tests.mocks import MockConnection

pytestmark = pytest.mark.core

GROUP = "pydapper.adapters"
FIRST_PARTY = "pydapper"


def dsn_for(adapter_name):
    return f"somedb+{adapter_name}://localhost/database"


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


def always_matches(connection):
    return True


def provider(
    name,
    *,
    distribution="acme-adapter",
    commands=MockCommands,
    async_commands=None,
    predicate=never_matches,
):
    """Build an entry point whose callback registers ``name``, plus its call log."""
    calls = []

    def register():
        calls.append("called")
        pydapper.register_adapter(
            name,
            commands=commands,
            async_commands=async_commands,
            using_connection_predicate=predicate,
        )

    return FakeEntryPoint(name, loaded=register, distribution=distribution), calls


def broken_provider(name, *, distribution="broken-adapter"):
    return FakeEntryPoint(name, distribution=distribution, load_error=ImportError(f"{name} provider is broken"))


def recording_sync_commands():
    """A fresh sync command class that records what the DSN path handed it."""

    class RecordingCommands(MockCommands):
        connect_calls = []

        @classmethod
        def connect(cls, parsed_dsn, **connect_kwargs):
            cls.connect_calls.append((parsed_dsn, connect_kwargs))
            return cls(MockConnection())

    return RecordingCommands


def recording_async_commands():
    """A fresh async command class that records what the DSN path handed it."""

    class RecordingCommandsAsync(MockAsyncCommands):
        connect_calls = []

        @classmethod
        async def connect_async(cls, parsed_dsn, **connect_kwargs):
            cls.connect_calls.append((parsed_dsn, connect_kwargs))
            return cls(MockAsyncConnection())

    return RecordingCommandsAsync


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


def assert_no_key_error(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        assert not isinstance(error, KeyError), f"raw KeyError leaked through name resolution: {error!r}"
        error = error.__cause__ or error.__context__


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
    empty.
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


@pytest.fixture
def dsn_parse_log(monkeypatch):
    """Record what the DSN path parsed, and every real parser construction.

    ``parsed`` holds the objects ``parse_dsn()`` handed back to CommandFactory,
    so a test can assert that the *same object* reached the command class.
    ``constructions`` counts ``PydapperParseResult.__init__`` calls, so a
    downstream reparse is still visible even when it bypasses ``parse_dsn()``
    entirely -- checking only the fields of whatever object arrives would let a
    silently reparsed DSN pass.
    """
    parsed = []
    constructions = []
    real_parse_dsn = main.parse_dsn
    real_init = PydapperParseResult.__init__

    def counting_init(self, dsn):
        constructions.append(dsn)
        real_init(self, dsn)

    def recording_parse_dsn(dsn=None):
        result = real_parse_dsn(dsn)
        parsed.append(result)
        return result

    monkeypatch.setattr(PydapperParseResult, "__init__", counting_init)
    monkeypatch.setattr(main, "parse_dsn", recording_parse_dsn)
    return SimpleNamespace(parsed=parsed, constructions=constructions)


@pytest.fixture
def forbid_discovery(monkeypatch):
    def fail_enumeration(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("this path must not enumerate entry points")

    monkeypatch.setattr(importlib.metadata, "entry_points", fail_enumeration)
    _adapter_discovery._reset_provider_catalog_for_tests()


# ---------------------------------------------------------------------------- DSN paths


def test_connect_lazily_loads_a_sync_provider_named_by_the_dsn(install_entry_points, dsn_parse_log):
    commands_class = recording_sync_commands()
    entry_point, calls = provider("acmedb", commands=commands_class)
    install_entry_points([entry_point])
    assert "acmedb" not in main._adapter_registry

    commands = pydapper.connect(dsn_for("acmedb"), timeout=5, application_name="pydapper")

    assert isinstance(commands, commands_class)
    assert calls == ["called"]
    assert entry_point.load_calls == 1
    # the DSN is parsed exactly once, and that very object -- not an equal copy -- is what reaches
    # the selected command class, along with every connect kwarg untouched
    ((parsed_dsn, connect_kwargs),) = commands_class.connect_calls
    assert dsn_parse_log.constructions == [dsn_for("acmedb")]
    assert parsed_dsn is dsn_parse_log.parsed[0]
    assert parsed_dsn.dbapi == "acmedb"
    assert parsed_dsn.hostname == "localhost"
    assert connect_kwargs == {"timeout": 5, "application_name": "pydapper"}


@pytest.mark.asyncio
async def test_connect_async_lazily_loads_an_async_provider_named_by_the_dsn(install_entry_points, dsn_parse_log):
    commands_class = recording_async_commands()
    entry_point, calls = provider("acmedb", commands=None, async_commands=commands_class)
    install_entry_points([entry_point])
    assert "acmedb" not in main._adapter_registry

    awaitable = pydapper.connect_async(dsn_for("acmedb"), timeout=5)
    # the awaitable-context-manager return type is unchanged by lazy resolution
    assert isinstance(awaitable, _AwaitableAsyncContextManager)
    commands = await awaitable

    assert isinstance(commands, commands_class)
    assert calls == ["called"]
    assert entry_point.load_calls == 1
    # same parse-once and object-identity guarantee as the sync path
    ((parsed_dsn, connect_kwargs),) = commands_class.connect_calls
    assert dsn_parse_log.constructions == [dsn_for("acmedb")]
    assert parsed_dsn is dsn_parse_log.parsed[0]
    assert parsed_dsn.dbapi == "acmedb"
    assert connect_kwargs == {"timeout": 5}

    # context-manager semantics still work, and the now-registered name needs no second load
    async with pydapper.connect_async(dsn_for("acmedb")) as context_commands:
        assert isinstance(context_commands, commands_class)
    assert calls == ["called"]
    assert entry_point.load_calls == 1


def test_connect_resolves_only_the_exact_dsn_name_without_reparsing(install_entry_points, dsn_parse_log):
    commands_class = recording_sync_commands()
    entry_point, calls = provider("acmedb", commands=commands_class)
    other_entry, other_calls = provider("otherdb", distribution="other-adapter")
    install_entry_points([entry_point, other_entry])

    pydapper.connect(dsn_for("acmedb"))

    # lazily loading a provider must not cost an extra parse: one parse_dsn() call, one parser
    # construction, and the resolver only ever sees the bare dbapi name from it
    assert len(dsn_parse_log.parsed) == 1
    assert dsn_parse_log.constructions == [dsn_for("acmedb")]
    assert calls == ["called"]
    assert other_calls == []
    assert_nothing_loaded([other_entry])


# ---------------------------------------------------------------------------- explicit adapter= paths


def test_using_with_explicit_adapter_lazily_loads_and_keeps_the_original_connection(install_entry_points):
    entry_point, calls = provider("acmedb", commands=MockCommands)
    install_entry_points([entry_point])
    connection = MockConnection()

    commands = pydapper.using(connection, adapter="acmedb")

    assert isinstance(commands, MockCommands)
    assert commands.connection is connection
    assert calls == ["called"]
    assert entry_point.load_calls == 1


def test_using_async_with_explicit_adapter_lazily_loads_and_keeps_the_original_connection(install_entry_points):
    entry_point, calls = provider("acmedb", commands=None, async_commands=MockAsyncCommands)
    install_entry_points([entry_point])
    connection = MockAsyncConnection()

    commands = pydapper.using_async(connection, adapter="acmedb")

    assert isinstance(commands, MockAsyncCommands)
    assert commands.connection is connection
    assert calls == ["called"]
    assert entry_point.load_calls == 1


def test_explicit_selection_never_evaluates_a_loaded_providers_predicate(install_entry_points):
    def exploding_predicate(connection):  # pragma: no cover - must never run
        raise AssertionError("explicit adapter= selection must not evaluate connection predicates")

    sync_entry, sync_calls = provider("syncdb", commands=MockCommands, predicate=exploding_predicate)
    async_entry, async_calls = provider(
        "asyncdb",
        distribution="async-adapter",
        commands=None,
        async_commands=MockAsyncCommands,
        predicate=exploding_predicate,
    )
    install_entry_points([sync_entry, async_entry])

    # loading a provider registers its predicate but must never call it on a name-based path
    assert isinstance(pydapper.using(MockConnection(), adapter="syncdb"), MockCommands)
    assert isinstance(pydapper.using_async(MockAsyncConnection(), adapter="asyncdb"), MockAsyncCommands)
    assert isinstance(pydapper.connect(dsn_for("syncdb")), MockCommands)

    assert sync_calls == ["called"]
    assert async_calls == ["called"]


def test_name_based_paths_load_only_the_requested_provider(install_entry_points):
    good_entry, good_calls = provider("acmedb", commands=MockCommands, async_commands=MockAsyncCommands)
    broken_entry = broken_provider("brokendb")
    unrelated_entry, unrelated_calls = provider("otherdb", distribution="other-adapter")
    install_entry_points([good_entry, broken_entry, unrelated_entry])

    assert isinstance(pydapper.connect(dsn_for("acmedb")), MockCommands)
    assert isinstance(pydapper.using(MockConnection(), adapter="acmedb"), MockCommands)
    assert isinstance(pydapper.using_async(MockAsyncConnection(), adapter="acmedb"), MockAsyncCommands)

    assert good_calls == ["called"]
    assert good_entry.load_calls == 1
    # a broken and an unrelated healthy provider are both left completely untouched
    assert_nothing_loaded([broken_entry, unrelated_entry])
    assert unrelated_calls == []
    assert "brokendb" not in main._adapter_registry
    assert "otherdb" not in main._adapter_registry


# ---------------------------------------------------------------------------- existing registrations still win


@pytest.mark.asyncio
async def test_direct_registration_serves_every_public_path_without_discovery(forbid_discovery):
    pydapper.register_adapter(
        "acmedb",
        commands=MockCommands,
        async_commands=MockAsyncCommands,
        using_connection_predicate=never_matches,
    )
    connection = MockConnection()
    async_connection = MockAsyncConnection()

    assert isinstance(pydapper.connect(dsn_for("acmedb")), MockCommands)
    assert isinstance(await pydapper.connect_async(dsn_for("acmedb")), MockAsyncCommands)
    assert pydapper.using(connection, adapter="acmedb").connection is connection
    assert pydapper.using_async(async_connection, adapter="acmedb").connection is async_connection

    # the enumeration guard proves no discovery ran; the unbuilt catalog and empty loader cache
    # prove nothing was discovered or loaded behind it
    assert _adapter_discovery._catalog is None
    assert main._loaded_provider_registrations == {}


# ---------------------------------------------------------------------------- unknown names


@pytest.mark.parametrize(
    ("label", "call"),
    [
        ("connect", lambda: pydapper.connect(dsn_for("unknown-adapter"))),
        # connect_async resolves the name before it builds a coroutine, so this raises eagerly
        ("connect_async", lambda: pydapper.connect_async(dsn_for("unknown-adapter"))),
        ("using", lambda: pydapper.using(MockConnection(), adapter="unknown-adapter")),
        ("using_async", lambda: pydapper.using_async(MockAsyncConnection(), adapter="unknown-adapter")),
    ],
)
def test_unknown_exact_names_fail_clearly_without_leaking_key_error(install_entry_points, label, call):
    entry_point, calls = provider("acmedb")
    install_entry_points([entry_point])

    with pytest.raises(ValueError) as excinfo:
        call()

    message = str(excinfo.value)
    assert "No registered or installed adapter" in message
    assert "unknown-adapter" in message
    assert_no_key_error(excinfo.value)
    # an unrelated installed provider is not consulted for a name it does not declare
    assert calls == []
    assert_nothing_loaded([entry_point])


# ---------------------------------------------------------------------------- mode checks happen after resolution


@pytest.mark.asyncio
async def test_async_only_provider_loads_then_raises_the_sync_mode_error(install_entry_points):
    entry_point, calls = provider("asyncdb", commands=None, async_commands=MockAsyncCommands)
    install_entry_points([entry_point])

    with pytest.raises(ValueError, match="does not support sync mode") as excinfo:
        pydapper.connect(dsn_for("asyncdb"))
    assert "asyncdb" in str(excinfo.value)

    # provider selection does not depend on the requested mode: the provider owns the name, loads
    # successfully, and the mode mismatch is reported afterwards without rolling the load back
    registration = main._adapter_registry["asyncdb"]
    assert registration.async_commands is MockAsyncCommands
    assert registration.commands is None
    assert calls == ["called"]
    assert entry_point.load_calls == 1

    # the supported mode reuses the surviving registration and never invokes the provider again
    assert isinstance(await pydapper.connect_async(dsn_for("asyncdb")), MockAsyncCommands)
    assert main._adapter_registry["asyncdb"] is registration
    assert calls == ["called"]
    assert entry_point.load_calls == 1


def test_sync_only_provider_loads_then_raises_the_async_mode_error(install_entry_points):
    entry_point, calls = provider("syncdb", commands=MockCommands)
    install_entry_points([entry_point])

    with pytest.raises(ValueError, match="does not support async mode") as excinfo:
        pydapper.using_async(MockAsyncConnection(), adapter="syncdb")
    assert "syncdb" in str(excinfo.value)

    registration = main._adapter_registry["syncdb"]
    assert registration.commands is MockCommands
    assert registration.async_commands is None
    assert calls == ["called"]
    assert entry_point.load_calls == 1

    connection = MockConnection()
    assert pydapper.using(connection, adapter="syncdb").connection is connection
    assert main._adapter_registry["syncdb"] is registration
    assert calls == ["called"]
    assert entry_point.load_calls == 1


def test_mode_mismatch_does_not_fall_back_to_another_same_name_provider(install_entry_points):
    # both providers declare the same name and are genuinely installed. #559 precedence gives the
    # name to the first-party pydapper distribution, and that owner supplies async only -- so a
    # sync request must raise the mode error rather than fall through to the same-name external
    # provider that *would* have satisfied sync mode. Selection must not be mode-aware.
    owner_entry, owner_calls = provider(
        "acmedb",
        distribution=FIRST_PARTY,
        commands=None,
        async_commands=MockAsyncCommands,
    )
    external_entry, external_calls = provider("acmedb", distribution="other-adapter", commands=MockCommands)
    install_entry_points([owner_entry, external_entry])
    # the losing candidate really is in the catalog and really does support the requested mode
    assert len(_adapter_discovery._get_provider_catalog()["acmedb"]) == 2

    with pytest.raises(ValueError, match="does not support sync mode"):
        pydapper.connect(dsn_for("acmedb"))

    assert owner_calls == ["called"]
    assert owner_entry.load_calls == 1
    assert external_calls == []
    assert_nothing_loaded([external_entry])
    assert main._adapter_registry["acmedb"].commands is None


@pytest.mark.asyncio
async def test_a_dual_mode_provider_is_invoked_once_across_all_public_name_paths(install_entry_points):
    entry_point, calls = provider("acmedb", commands=MockCommands, async_commands=MockAsyncCommands)
    install_entry_points([entry_point])

    assert isinstance(pydapper.connect(dsn_for("acmedb")), MockCommands)
    assert isinstance(await pydapper.connect_async(dsn_for("acmedb")), MockAsyncCommands)
    assert isinstance(pydapper.using(MockConnection(), adapter="acmedb"), MockCommands)
    assert isinstance(pydapper.using_async(MockAsyncConnection(), adapter="acmedb"), MockAsyncCommands)

    assert calls == ["called"]
    assert entry_point.load_calls == 1


# ---------------------------------------------------------------------------- credentials never leak


@pytest.mark.parametrize("adapter_name", ["unknown-adapter", "brokendb"])
@pytest.mark.parametrize("factory", [pydapper.connect, pydapper.connect_async])
def test_dsn_resolution_errors_never_leak_credentials(install_entry_points, caplog, factory, adapter_name):
    install_entry_points([broken_provider("brokendb")])
    dsn = f"somedb+{adapter_name}://dsnuser:dsnsecret@localhost/database"

    with caplog.at_level(logging.DEBUG, logger="pydapper.main"):
        with pytest.raises(ValueError) as excinfo:
            factory(dsn)

    leaked = error_chain_text(excinfo.value) + " " + " ".join(record.getMessage() for record in caplog.records)
    assert "dsnuser" not in leaked
    assert "dsnsecret" not in leaked
    assert dsn not in leaked
    assert "localhost/database" not in leaked


# ---------------------------------------------------------------------------- automatic selection deliberately differs


def test_only_automatic_selection_loads_unrelated_installed_providers(install_entry_points):
    # the intentional #468 contrast, shown on one catalog: a name-based path loads only the
    # provider it was asked for, while automatic selection loads every installed provider so their
    # predicates exist to be evaluated at all
    entry_point, calls = provider(
        "acmedb", commands=MockCommands, async_commands=MockAsyncCommands, predicate=always_matches
    )
    unrelated, unrelated_calls = provider("otherdb", distribution="other-adapter")
    install_entry_points([entry_point, unrelated])

    assert isinstance(pydapper.using(MockConnection(), adapter="acmedb"), MockCommands)
    assert calls == ["called"]
    assert unrelated_calls == []
    assert_nothing_loaded([unrelated])

    # the same unrelated provider is loaded once automatic selection needs the whole picture
    assert isinstance(pydapper.using(MockConnection()), MockCommands)
    assert isinstance(pydapper.using_async(MockAsyncConnection()), MockAsyncCommands)
    assert unrelated_calls == ["called"]
    assert unrelated.load_calls == 1


def test_automatic_selection_still_resolves_a_directly_registered_match(install_entry_points):
    install_entry_points([])

    class AutomaticCommands(MockCommands): ...

    class AutomaticCommandsAsync(MockAsyncCommands): ...

    pydapper.register_adapter(
        "automatic",
        commands=AutomaticCommands,
        async_commands=AutomaticCommandsAsync,
        using_connection_predicate=lambda connection: isinstance(connection, (MockConnection, MockAsyncConnection)),
    )

    assert isinstance(pydapper.using(MockConnection()), AutomaticCommands)
    assert isinstance(pydapper.using_async(MockAsyncConnection()), AutomaticCommandsAsync)
    # automatic selection discovers the catalog now, but an empty one is a successful no-op that
    # loads nothing
    assert main._loaded_provider_registrations == {}


# ---------------------------------------------------------------------------- public surface


def test_public_name_based_signatures_are_unchanged():
    assert list(inspect.signature(pydapper.connect).parameters) == ["dsn", "connect_kwargs"]
    assert list(inspect.signature(pydapper.connect_async).parameters) == ["dsn", "connect_kwargs"]
    assert list(inspect.signature(pydapper.using).parameters) == ["connection", "adapter"]
    assert list(inspect.signature(pydapper.using_async).parameters) == ["connection", "adapter"]
    for function in (pydapper.using, pydapper.using_async):
        assert inspect.signature(function).parameters["adapter"].kind is inspect.Parameter.KEYWORD_ONLY
        assert inspect.signature(function).parameters["adapter"].default is None
