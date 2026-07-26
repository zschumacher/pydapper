import importlib.metadata
import sqlite3

import pytest

import pydapper
import pydapper.main as main
from pydapper import _adapter_discovery
from pydapper.bigquery import GoogleBigqueryClientCommands
from pydapper.mssql import PymssqlCommands
from pydapper.mysql import MySqlConnectorPythonCommands
from pydapper.oracle import OracledbCommands
from pydapper.postgresql import AiopgCommands
from pydapper.postgresql import Psycopg2Commands
from pydapper.postgresql import Psycopg3Commands
from pydapper.postgresql import Psycopg3CommandsAsync
from pydapper.sqlite import Sqlite3Commands
from tests.mocks import MockAsyncCommands
from tests.mocks import MockAsyncConnection
from tests.mocks import MockCommands
from tests.mocks import MockConnection

DSN = "somedb+tests://localhost"

pytestmark = pytest.mark.core

# real DB-API connection reprs embed the DSN the connection was opened with, and a third-party
# driver's repr is unbounded, so the sentinel stands in for whatever a driver might render
CREDENTIAL_BEARING_REPR_SENTINEL = "user=admin password=hunter2 host=db.internal dbname=prod"


class CredentialLeakingConnection:
    def __repr__(self):
        return f"<connection object at 0x0; dsn: '{CREDENTIAL_BEARING_REPR_SENTINEL}'>"


# spelled out rather than derived from the class, so the assertions pin the exact rendering
EXPECTED_CONNECTION_TYPE_LABEL = "tests.test_main.CredentialLeakingConnection"


class UnreadableTypeIdentityMeta(type):
    """Makes a connection class's own identity attributes unreadable, as a hostile driver could."""

    def __getattribute__(cls, name):
        if name in ("__module__", "__qualname__"):
            raise AttributeError(name)
        return super().__getattribute__(name)


class NonStringTypeIdentityMeta(type):
    """Same, except the identity attributes are readable and are not strings."""

    def __getattribute__(cls, name):
        if name in ("__module__", "__qualname__"):
            return 42
        return super().__getattribute__(name)


@pytest.fixture
def adapter_registry(monkeypatch):
    registry = main._adapter_registry.copy()
    monkeypatch.setattr(main, "_adapter_registry", registry)
    # name-based public paths resolve through the provider catalog and loader now, so this fixture
    # also isolates that state: a fake catalog or cached load leaked by another module must never
    # decide whether a name resolves here, in either direction. Discovery is restricted to the
    # pydapper distribution's own real entry points, so an unrelated adapter installed on a
    # developer or CI machine can neither add automatic-selection candidates nor break the
    # load-all pass with a broken provider. monkeypatch restores the real enumeration, catalog,
    # and loader cache at teardown rather than leaving them emptied.
    first_party_entry_points = [
        entry_point
        for entry_point in importlib.metadata.entry_points(group="pydapper.adapters")
        if entry_point.dist is not None and main._canonicalize_distribution_name(entry_point.dist.name) == "pydapper"
    ]
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: [entry_point for entry_point in first_party_entry_points if entry_point.group == group],
    )
    monkeypatch.setattr(_adapter_discovery, "_catalog", None)
    monkeypatch.setattr(main, "_loaded_provider_registrations", {})
    return registry


def never_matches(connection):
    return False


def test_register_adapter_sync_only(adapter_registry):
    result = pydapper.register_adapter(
        "sync-only",
        commands=MockCommands,
        using_connection_predicate=never_matches,
    )

    assert result is None
    registration = adapter_registry["sync-only"]
    assert registration.name == "sync-only"
    assert registration.commands is MockCommands
    assert registration.async_commands is None


def test_register_adapter_async_only(adapter_registry):
    pydapper.register_adapter(
        "async-only",
        async_commands=MockAsyncCommands,
        using_connection_predicate=never_matches,
    )

    registration = adapter_registry["async-only"]
    assert registration.commands is None
    assert registration.async_commands is MockAsyncCommands


def test_register_adapter_combined(adapter_registry):
    pydapper.register_adapter(
        "combined",
        commands=MockCommands,
        async_commands=MockAsyncCommands,
        using_connection_predicate=never_matches,
    )

    registration = adapter_registry["combined"]
    assert registration.commands is MockCommands
    assert registration.async_commands is MockAsyncCommands


@pytest.mark.parametrize("name", [None, 1, object()])
def test_register_adapter_rejects_non_string_name(adapter_registry, name):
    with pytest.raises(TypeError):
        pydapper.register_adapter(name, commands=MockCommands, using_connection_predicate=never_matches)


@pytest.mark.parametrize("name", ["", " leading", "trailing ", "\tname", "name\n"])
def test_register_adapter_rejects_blank_or_whitespace_padded_name(adapter_registry, name):
    with pytest.raises(ValueError):
        pydapper.register_adapter(name, commands=MockCommands, using_connection_predicate=never_matches)


def test_register_adapter_names_are_case_sensitive(adapter_registry):
    pydapper.register_adapter("Adapter", commands=MockCommands, using_connection_predicate=never_matches)
    pydapper.register_adapter("adapter", commands=MockCommands, using_connection_predicate=never_matches)

    assert {"Adapter", "adapter"}.issubset(adapter_registry)


def test_register_adapter_requires_a_command_class(adapter_registry):
    with pytest.raises(ValueError):
        pydapper.register_adapter("missing-commands", using_connection_predicate=never_matches)


def test_register_adapter_requires_using_connection_predicate(adapter_registry):
    with pytest.raises(TypeError):
        pydapper.register_adapter("missing-predicate", commands=MockCommands)


@pytest.mark.parametrize("commands", [object, MockAsyncCommands])
def test_register_adapter_rejects_invalid_sync_command_class(adapter_registry, commands):
    with pytest.raises(TypeError):
        pydapper.register_adapter("invalid-sync", commands=commands, using_connection_predicate=never_matches)


@pytest.mark.parametrize("async_commands", [object, MockCommands])
def test_register_adapter_rejects_invalid_async_command_class(adapter_registry, async_commands):
    with pytest.raises(TypeError):
        pydapper.register_adapter(
            "invalid-async",
            async_commands=async_commands,
            using_connection_predicate=never_matches,
        )


def test_register_adapter_rejects_non_callable_using_connection_predicate(adapter_registry):
    with pytest.raises(TypeError):
        pydapper.register_adapter("invalid-predicate", commands=MockCommands, using_connection_predicate=None)


def test_registration_validation_failure_is_atomic(adapter_registry):
    before = adapter_registry.copy()

    with pytest.raises(TypeError):
        pydapper.register_adapter("invalid", commands=object, using_connection_predicate=never_matches)

    assert adapter_registry == before


class DeclaredSyncCommands(MockCommands):
    capabilities = frozenset({pydapper.AdapterCapability.TRANSACTIONS})


class DeclaredAsyncCommands(MockAsyncCommands):
    capabilities = frozenset({pydapper.AdapterCapability.RAW_READER, pydapper.AdapterCapability.EXPLAIN})


def test_register_adapter_accepts_empty_capability_declarations(adapter_registry):
    pydapper.register_adapter(
        "empty-capabilities",
        commands=MockCommands,
        async_commands=MockAsyncCommands,
        using_connection_predicate=never_matches,
    )

    registration = adapter_registry["empty-capabilities"]
    assert registration.commands.capabilities == frozenset()
    assert registration.async_commands.capabilities == frozenset()


def test_register_adapter_accepts_distinct_nonempty_per_mode_declarations(adapter_registry):
    pydapper.register_adapter(
        "declared-capabilities",
        commands=DeclaredSyncCommands,
        async_commands=DeclaredAsyncCommands,
        using_connection_predicate=never_matches,
    )

    registration = adapter_registry["declared-capabilities"]
    assert registration.commands.capabilities == frozenset({pydapper.AdapterCapability.TRANSACTIONS})
    assert registration.async_commands.capabilities == frozenset(
        {pydapper.AdapterCapability.RAW_READER, pydapper.AdapterCapability.EXPLAIN}
    )
    assert registration.commands.capabilities != registration.async_commands.capabilities


INVALID_CAPABILITY_DECLARATIONS = [
    pytest.param({pydapper.AdapterCapability.TRANSACTIONS}, id="mutable-set"),
    pytest.param((pydapper.AdapterCapability.TRANSACTIONS,), id="tuple"),
    pytest.param([pydapper.AdapterCapability.TRANSACTIONS], id="list"),
    pytest.param("transactions", id="raw-string"),
    pytest.param(frozenset({"transactions"}), id="raw-string-member"),
    pytest.param(frozenset({pydapper.AdapterCapability.TRANSACTIONS, "explain"}), id="mixed-members"),
    pytest.param(frozenset({pydapper.AdapterCapability.TRANSACTIONS, 1}), id="unrelated-member"),
    pytest.param(object(), id="unrelated-object"),
    pytest.param(None, id="none"),
]


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("declared", INVALID_CAPABILITY_DECLARATIONS)
def test_register_adapter_rejects_invalid_capability_declarations_atomically(adapter_registry, mode, declared):
    before = adapter_registry.copy()
    if mode == "sync":
        kwargs = {"commands": type("InvalidCapabilityCommands", (MockCommands,), {"capabilities": declared})}
    else:
        kwargs = {
            "async_commands": type("InvalidCapabilityCommandsAsync", (MockAsyncCommands,), {"capabilities": declared})
        }

    with pytest.raises(TypeError) as exc_info:
        pydapper.register_adapter("invalid-capabilities", using_connection_predicate=never_matches, **kwargs)

    assert "capabilities" in str(exc_info.value)
    assert adapter_registry == before


@pytest.mark.parametrize("invalid_mode", ["sync", "async"])
def test_register_adapter_capability_failure_in_one_mode_fails_the_whole_registration(adapter_registry, invalid_mode):
    before = adapter_registry.copy()
    invalid_sync = type("InvalidCapabilityCommands", (MockCommands,), {"capabilities": {"transactions"}})
    invalid_async = type("InvalidCapabilityCommandsAsync", (MockAsyncCommands,), {"capabilities": {"transactions"}})
    commands = invalid_sync if invalid_mode == "sync" else DeclaredSyncCommands
    async_commands = invalid_async if invalid_mode == "async" else DeclaredAsyncCommands

    with pytest.raises(TypeError) as exc_info:
        pydapper.register_adapter(
            "half-invalid",
            commands=commands,
            async_commands=async_commands,
            using_connection_predicate=never_matches,
        )

    message = str(exc_info.value)
    if invalid_mode == "sync":
        assert "commands" in message
        assert "async_commands" not in message
    else:
        assert "async_commands" in message
    assert "capabilities" in message
    assert "half-invalid" not in adapter_registry
    assert adapter_registry == before


def test_duplicate_registration_is_rejected_without_mutating_the_original(adapter_registry):
    pydapper.register_adapter("duplicate", commands=MockCommands, using_connection_predicate=never_matches)
    original_registration = adapter_registry["duplicate"]
    before = adapter_registry.copy()

    with pytest.raises(ValueError):
        pydapper.register_adapter("duplicate", commands=MockCommands, using_connection_predicate=never_matches)

    assert adapter_registry == before
    assert adapter_registry["duplicate"] is original_registration


@pytest.mark.parametrize(
    ("registered_kwargs", "second_kwargs", "absent_attribute", "factory", "connection_class", "mode"),
    [
        pytest.param(
            {"commands": MockCommands},
            {"async_commands": MockAsyncCommands},
            "async_commands",
            pydapper.using_async,
            MockAsyncConnection,
            "async",
            id="sync-only-then-async-only",
        ),
        pytest.param(
            {"async_commands": MockAsyncCommands},
            {"commands": MockCommands},
            "commands",
            pydapper.using,
            MockConnection,
            "sync",
            id="async-only-then-sync-only",
        ),
    ],
)
def test_duplicate_registration_never_merges_the_missing_mode(
    adapter_registry, registered_kwargs, second_kwargs, absent_attribute, factory, connection_class, mode
):
    # registration is one-way: a duplicate name may never overwrite *or merge*. Re-registering the
    # same name supplying only the mode the record lacks is still a duplicate, not a helpful
    # completion of a half-registered adapter, so the absent mode must stay absent afterwards.
    pydapper.register_adapter("half-registered", using_connection_predicate=never_matches, **registered_kwargs)
    original_registration = adapter_registry["half-registered"]
    before = adapter_registry.copy()
    assert getattr(original_registration, absent_attribute) is None

    with pytest.raises(ValueError, match="already registered"):
        pydapper.register_adapter("half-registered", using_connection_predicate=never_matches, **second_kwargs)

    assert adapter_registry == before
    assert adapter_registry["half-registered"] is original_registration
    assert getattr(adapter_registry["half-registered"], absent_attribute) is None

    # and the rejected mode is still unreachable through the public API, not silently usable
    with pytest.raises(ValueError, match=f"does not support {mode} mode"):
        factory(connection_class(), adapter="half-registered")


def test_duplicate_name_is_rejected_before_validating_a_second_payload(adapter_registry):
    pydapper.register_adapter("duplicate", commands=MockCommands, using_connection_predicate=never_matches)

    with pytest.raises(ValueError):
        pydapper.register_adapter("duplicate", commands=object, using_connection_predicate=None)


def test_explicit_selection_bypasses_predicates_for_sync_and_async(adapter_registry):
    def predicate(connection):
        raise AssertionError("explicit selection must not call predicates")

    pydapper.register_adapter(
        "explicit",
        commands=MockCommands,
        async_commands=MockAsyncCommands,
        using_connection_predicate=predicate,
    )

    assert isinstance(pydapper.using(MockConnection(), adapter="explicit"), MockCommands)
    assert isinstance(pydapper.using_async(MockAsyncConnection(), adapter="explicit"), MockAsyncCommands)


@pytest.mark.parametrize(
    ("factory", "connection"),
    [
        (pydapper.using, MockConnection),
        (pydapper.using_async, MockAsyncConnection),
    ],
)
def test_explicit_selection_rejects_unknown_adapter(adapter_registry, factory, connection):
    # name resolution owns unknown names now, so both modes fail identically: a name that is
    # neither registered nor installed is rejected before any mode is considered
    with pytest.raises(ValueError, match="unknown") as exc_info:
        factory(connection(), adapter="unknown")

    assert "No registered or installed adapter" in str(exc_info.value)


def test_explicit_selection_rejects_adapter_without_requested_mode(adapter_registry):
    pydapper.register_adapter("sync-only", commands=MockCommands, using_connection_predicate=never_matches)
    pydapper.register_adapter(
        "async-only",
        async_commands=MockAsyncCommands,
        using_connection_predicate=never_matches,
    )

    with pytest.raises(ValueError, match="sync-only") as sync_exc_info:
        pydapper.using_async(MockAsyncConnection(), adapter="sync-only")
    with pytest.raises(ValueError, match="async-only") as async_exc_info:
        pydapper.using(MockConnection(), adapter="async-only")

    assert "async" in str(sync_exc_info.value)
    assert "sync" in str(async_exc_info.value)


def test_using_automatically_selects_the_single_matching_sync_adapter(adapter_registry):
    pydapper.register_adapter(
        "sync-match",
        commands=MockCommands,
        using_connection_predicate=lambda connection: isinstance(connection, MockConnection),
    )

    assert isinstance(pydapper.using(MockConnection()), MockCommands)


def test_using_async_automatically_selects_the_single_matching_async_adapter(adapter_registry):
    pydapper.register_adapter(
        "async-match",
        async_commands=MockAsyncCommands,
        using_connection_predicate=lambda connection: isinstance(connection, MockAsyncConnection),
    )

    assert isinstance(pydapper.using_async(MockAsyncConnection()), MockAsyncCommands)


@pytest.mark.parametrize(
    ("factory", "connection", "mode"),
    [
        (pydapper.using, MockConnection, "sync"),
        (pydapper.using_async, MockAsyncConnection, "async"),
    ],
)
def test_automatic_selection_rejects_zero_matches(adapter_registry, factory, connection, mode):
    with pytest.raises(ValueError, match="adapter=") as exc_info:
        factory(connection())

    assert mode in str(exc_info.value)
    assert "register an adapter" in str(exc_info.value)


@pytest.mark.parametrize("names", [("first", "second"), ("second", "first")])
def test_automatic_selection_rejects_ambiguity_regardless_of_registration_order(adapter_registry, names):
    predicate_calls = []

    def matches(connection):
        predicate_calls.append(connection)
        return True

    for name in names:
        pydapper.register_adapter(name, commands=MockCommands, using_connection_predicate=matches)

    connection = MockConnection()
    with pytest.raises(ValueError, match="adapter=") as exc_info:
        pydapper.using(connection)

    message = str(exc_info.value)
    assert "first" in message
    assert "second" in message
    assert message.index("first") < message.index("second")
    assert predicate_calls == [connection, connection]


@pytest.mark.parametrize("factory", [pydapper.using, pydapper.using_async])
def test_automatic_selection_zero_match_error_names_the_connection_type_not_its_repr(adapter_registry, factory):
    connection = CredentialLeakingConnection()

    with pytest.raises(ValueError, match="adapter=") as exc_info:
        factory(connection)

    message = str(exc_info.value)
    # the driver-controlled repr -- credentials and all -- must not reach the message
    assert CREDENTIAL_BEARING_REPR_SENTINEL not in message
    assert repr(connection) not in message
    # the connection is still identified, by module-qualified type: enough to tell a caller which
    # driver pydapper looked at and could not place
    assert repr(EXPECTED_CONNECTION_TYPE_LABEL) in message
    assert "register an adapter" in message


@pytest.mark.parametrize(
    ("factory", "registration_kwargs"),
    [
        (pydapper.using, {"commands": MockCommands}),
        (pydapper.using_async, {"async_commands": MockAsyncCommands}),
    ],
)
def test_automatic_selection_ambiguity_error_names_the_connection_type_not_its_repr(
    adapter_registry, factory, registration_kwargs
):
    for name in ("first", "second"):
        pydapper.register_adapter(name, using_connection_predicate=lambda connection: True, **registration_kwargs)

    connection = CredentialLeakingConnection()
    with pytest.raises(ValueError, match="adapter=") as exc_info:
        factory(connection)

    message = str(exc_info.value)
    assert CREDENTIAL_BEARING_REPR_SENTINEL not in message
    assert repr(connection) not in message
    assert repr(EXPECTED_CONNECTION_TYPE_LABEL) in message
    # the ambiguity is still actionable: both matching adapters are still named
    assert "first" in message
    assert "second" in message


@pytest.mark.parametrize("factory", [pydapper.using, pydapper.using_async])
def test_automatic_selection_error_falls_back_to_the_class_name_when_the_module_is_unusable(adapter_registry, factory):
    connection_class = type("ConnectionWithNonStringModule", (), {})
    connection_class.__module__ = None

    with pytest.raises(ValueError, match="adapter=") as exc_info:
        factory(connection_class())

    message = str(exc_info.value)
    # no "None." prefix and no bare leading dot: an unusable module drops out of the label entirely
    assert "a connection of type 'ConnectionWithNonStringModule'" in message


@pytest.mark.parametrize("metaclass", [UnreadableTypeIdentityMeta, NonStringTypeIdentityMeta])
@pytest.mark.parametrize("factory", [pydapper.using, pydapper.using_async])
def test_automatic_selection_still_raises_value_error_for_an_unlabelable_connection_type(
    adapter_registry, factory, metaclass
):
    # reading type identity off a connection must not be able to turn the documented ValueError
    # into an AttributeError (or anything else a driver's metaclass chooses to raise)
    connection_class = metaclass("PathologicalConnection", (), {})

    with pytest.raises(ValueError, match="adapter=") as exc_info:
        factory(connection_class())

    message = str(exc_info.value)
    # still a usable message: what pydapper was asked to do, and what to do about it
    assert "a connection of type '<unknown type>'" in message
    assert "register an adapter" in message


def test_sync_selection_does_not_call_async_only_predicates(adapter_registry):
    def must_not_run(connection):
        raise AssertionError("mode-ineligible predicate was called")

    pydapper.register_adapter(
        "async-only",
        async_commands=MockAsyncCommands,
        using_connection_predicate=must_not_run,
    )
    pydapper.register_adapter(
        "sync-match",
        commands=MockCommands,
        using_connection_predicate=lambda connection: isinstance(connection, MockConnection),
    )

    assert isinstance(pydapper.using(MockConnection()), MockCommands)


def test_async_selection_does_not_call_sync_only_predicates(adapter_registry):
    def must_not_run(connection):
        raise AssertionError("mode-ineligible predicate was called")

    pydapper.register_adapter("sync-only", commands=MockCommands, using_connection_predicate=must_not_run)
    pydapper.register_adapter(
        "async-match",
        async_commands=MockAsyncCommands,
        using_connection_predicate=lambda connection: isinstance(connection, MockAsyncConnection),
    )

    assert isinstance(pydapper.using_async(MockAsyncConnection()), MockAsyncCommands)


def test_automatic_selection_wraps_predicate_errors_with_the_original_cause(adapter_registry):
    cause = RuntimeError("predicate failed")

    def raises(connection):
        raise cause

    pydapper.register_adapter("failing", commands=MockCommands, using_connection_predicate=raises)

    with pytest.raises(ValueError, match="failing") as exc_info:
        pydapper.using(MockConnection())

    assert exc_info.value.__cause__ is cause


def test_connect_routes_to_the_registered_sync_adapter(adapter_registry):
    pydapper.register_adapter("tests", commands=MockCommands, using_connection_predicate=never_matches)

    assert isinstance(pydapper.connect(DSN), MockCommands)


@pytest.mark.asyncio
async def test_connect_async_routes_to_the_registered_async_adapter(adapter_registry):
    pydapper.register_adapter(
        "tests",
        async_commands=MockAsyncCommands,
        using_connection_predicate=never_matches,
    )

    assert isinstance(await pydapper.connect_async(DSN), MockAsyncCommands)


@pytest.mark.asyncio
async def test_connect_async_context_returns_commands_and_propagates_connection_suppression(adapter_registry):
    class SuppressingConnection:
        exited = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            self.exited = True
            return True

    class SuppressingCommands(MockAsyncCommands):
        @classmethod
        async def connect_async(cls, parsed_dsn, **connect_kwargs):
            connection = SuppressingConnection()
            commands = cls(connection)
            commands.test_connection = connection
            return commands

    pydapper.register_adapter(
        "tests",
        async_commands=SuppressingCommands,
        using_connection_predicate=never_matches,
    )

    try:
        async with pydapper.connect_async(DSN) as commands:
            assert isinstance(commands, SuppressingCommands)
            connection = commands.test_connection
            raise ValueError("body")
    except ValueError:
        pytest.fail("connection suppression did not propagate")
    assert connection.exited


@pytest.mark.asyncio
async def test_dsn_selection_bypasses_using_connection_predicate(adapter_registry):
    def predicate(connection):
        raise AssertionError("DSN selection must not call predicates")

    pydapper.register_adapter(
        "tests",
        commands=MockCommands,
        async_commands=MockAsyncCommands,
        using_connection_predicate=predicate,
    )

    assert isinstance(pydapper.connect(DSN), MockCommands)
    assert isinstance(await pydapper.connect_async(DSN), MockAsyncCommands)


def test_connect_uses_the_environment_dsn_fallback(adapter_registry, monkeypatch):
    pydapper.register_adapter("tests", commands=MockCommands, using_connection_predicate=never_matches)
    monkeypatch.setenv("PYDAPPER_DSN", DSN)

    assert isinstance(pydapper.connect(), MockCommands)


@pytest.mark.asyncio
async def test_connect_async_uses_the_environment_dsn_fallback(adapter_registry, monkeypatch):
    pydapper.register_adapter(
        "tests",
        async_commands=MockAsyncCommands,
        using_connection_predicate=never_matches,
    )
    monkeypatch.setenv("PYDAPPER_DSN", DSN)

    assert isinstance(await pydapper.connect_async(), MockAsyncCommands)


def test_explicit_dsn_takes_precedence_over_environment_for_connect(adapter_registry, monkeypatch):
    class EnvironmentCommands(MockCommands): ...

    class ExplicitCommands(MockCommands): ...

    pydapper.register_adapter(
        "environment",
        commands=EnvironmentCommands,
        using_connection_predicate=never_matches,
    )
    pydapper.register_adapter(
        "explicit",
        commands=ExplicitCommands,
        using_connection_predicate=never_matches,
    )
    monkeypatch.setenv("PYDAPPER_DSN", "somedb+environment://localhost")

    assert isinstance(pydapper.connect("somedb+explicit://localhost"), ExplicitCommands)


@pytest.mark.asyncio
async def test_explicit_dsn_takes_precedence_over_environment_for_connect_async(adapter_registry, monkeypatch):
    class EnvironmentCommands(MockAsyncCommands): ...

    class ExplicitCommands(MockAsyncCommands): ...

    pydapper.register_adapter(
        "environment",
        async_commands=EnvironmentCommands,
        using_connection_predicate=never_matches,
    )
    pydapper.register_adapter(
        "explicit",
        async_commands=ExplicitCommands,
        using_connection_predicate=never_matches,
    )
    monkeypatch.setenv("PYDAPPER_DSN", "somedb+environment://localhost")

    assert isinstance(await pydapper.connect_async("somedb+explicit://localhost"), ExplicitCommands)


@pytest.mark.parametrize("factory", [pydapper.connect, pydapper.connect_async])
@pytest.mark.parametrize("invalid_dsn", ["", "missing-scheme"])
def test_invalid_explicit_dsn_is_not_replaced_by_environment(
    adapter_registry,
    monkeypatch,
    factory,
    invalid_dsn,
):
    pydapper.register_adapter(
        "environment",
        commands=MockCommands,
        async_commands=MockAsyncCommands,
        using_connection_predicate=never_matches,
    )
    monkeypatch.setenv("PYDAPPER_DSN", "somedb+environment://localhost")

    with pytest.raises(ValueError):
        factory(invalid_dsn)


@pytest.mark.parametrize("factory", [pydapper.connect, pydapper.connect_async])
@pytest.mark.parametrize("environment_dsn", ["", "missing-scheme"])
def test_invalid_environment_dsn_is_rejected(adapter_registry, monkeypatch, factory, environment_dsn):
    monkeypatch.setenv("PYDAPPER_DSN", environment_dsn)

    with pytest.raises(ValueError):
        factory()


@pytest.mark.parametrize(
    ("dsn", "adapter_name"),
    [
        ("sqlite://routing.db", "sqlite3"),
        ("postgresql://user:password@localhost/database", "psycopg2"),
        ("mssql://user:password@localhost/database", "pymssql"),
        ("mysql://user:password@localhost/database", "mysql"),
        ("oracle://user:password@localhost/database", "oracledb"),
        ("bigquery:////", "google"),
        ("sqlite+sqlite3://routing.db", "sqlite3"),
        ("postgresql+psycopg://user:password@localhost/database", "psycopg"),
    ],
)
def test_connect_routes_default_and_explicit_dsn_adapter_names(adapter_registry, dsn, adapter_name):
    # a direct registration of the stable name wins over the installed first-party entry point,
    # so registering a mock under it both proves the DSN routes to that exact name and proves the
    # provider is never loaded over it
    adapter_registry.pop(adapter_name, None)
    pydapper.register_adapter(adapter_name, commands=MockCommands, using_connection_predicate=never_matches)

    assert isinstance(pydapper.connect(dsn), MockCommands)
    assert main._loaded_provider_registrations == {}


@pytest.mark.parametrize(
    ("dsn", "adapter_name"),
    [
        ("postgresql+psycopg://user:password@localhost/database", "psycopg"),
        ("postgresql+aiopg://user:password@localhost/database", "aiopg"),
    ],
)
@pytest.mark.asyncio
async def test_connect_async_routes_explicit_dsn_adapter_names(adapter_registry, dsn, adapter_name):
    adapter_registry.pop(adapter_name, None)
    pydapper.register_adapter(adapter_name, async_commands=MockAsyncCommands, using_connection_predicate=never_matches)

    assert isinstance(await pydapper.connect_async(dsn), MockAsyncCommands)
    assert main._loaded_provider_registrations == {}


@pytest.mark.asyncio
async def test_third_party_explicit_adapter_name_routes_exactly_for_sync_and_async(adapter_registry):
    class AcmeCommands(MockCommands): ...

    class AcmeCommandsAsync(MockAsyncCommands): ...

    pydapper.register_adapter(
        "AcmeDB",
        commands=AcmeCommands,
        async_commands=AcmeCommandsAsync,
        using_connection_predicate=never_matches,
    )

    assert isinstance(pydapper.connect("acme+AcmeDB://localhost/database"), AcmeCommands)
    assert isinstance(await pydapper.connect_async("acme+AcmeDB://localhost/database"), AcmeCommandsAsync)


def test_default_dsn_adapter_still_checks_requested_mode(adapter_registry):
    with pytest.raises(ValueError, match="psycopg2") as exc_info:
        pydapper.connect_async("postgresql://user:password@localhost/database")

    assert "async" in str(exc_info.value)


def test_connect_rejects_an_unknown_dsn_adapter(adapter_registry):
    with pytest.raises(ValueError, match="unknown") as exc_info:
        pydapper.connect("somedb+unknown://localhost")

    assert "No registered or installed adapter" in str(exc_info.value)


def test_connect_async_rejects_an_unknown_dsn_adapter(adapter_registry):
    with pytest.raises(ValueError, match="unknown") as exc_info:
        pydapper.connect_async("somedb+unknown://localhost")

    assert "No registered or installed adapter" in str(exc_info.value)


def test_connect_async_rejects_an_adapter_without_async_support(adapter_registry):
    pydapper.register_adapter("sync-only", commands=MockCommands, using_connection_predicate=never_matches)

    with pytest.raises(ValueError, match="sync-only") as exc_info:
        pydapper.connect_async("somedb+sync-only://localhost")

    assert "async" in str(exc_info.value)


def test_connect_rejects_an_adapter_without_sync_support(adapter_registry):
    pydapper.register_adapter(
        "async-only",
        async_commands=MockAsyncCommands,
        using_connection_predicate=never_matches,
    )

    with pytest.raises(ValueError, match="async-only") as exc_info:
        pydapper.connect("somedb+async-only://localhost")

    assert "sync" in str(exc_info.value)


#: The exact capability set every first-party command class must declare. Sync classes
#: implement the transaction APIs; the async transaction feature has not landed, and
#: BigQuery's DBAPI cannot support transactions (commit() is a no-op, rollback() is absent).
FIRST_PARTY_CAPABILITY_DECLARATIONS = {
    Sqlite3Commands: frozenset({pydapper.AdapterCapability.TRANSACTIONS}),
    Psycopg2Commands: frozenset({pydapper.AdapterCapability.TRANSACTIONS}),
    Psycopg3Commands: frozenset({pydapper.AdapterCapability.TRANSACTIONS}),
    Psycopg3CommandsAsync: frozenset(),
    AiopgCommands: frozenset(),
    MySqlConnectorPythonCommands: frozenset({pydapper.AdapterCapability.TRANSACTIONS}),
    PymssqlCommands: frozenset({pydapper.AdapterCapability.TRANSACTIONS}),
    OracledbCommands: frozenset({pydapper.AdapterCapability.TRANSACTIONS}),
    GoogleBigqueryClientCommands: frozenset(),
}

FIRST_PARTY_COMMAND_CLASSES = list(FIRST_PARTY_CAPABILITY_DECLARATIONS)


@pytest.mark.parametrize("command_class", FIRST_PARTY_COMMAND_CLASSES, ids=lambda command_class: command_class.__name__)
def test_first_party_command_classes_declare_exact_capability_sets(command_class):
    declared = vars(command_class).get("capabilities")

    assert declared is not None, f"{command_class.__name__} must declare capabilities directly, not inherit the default"
    assert type(declared) is frozenset
    assert all(isinstance(member, pydapper.AdapterCapability) for member in declared)
    # any drift from this table is either an overclaim or an undeclared implemented feature
    assert declared == FIRST_PARTY_CAPABILITY_DECLARATIONS[command_class]


FIRST_PARTY_ADAPTER_TABLE = {
    "sqlite3": (Sqlite3Commands, None),
    "psycopg2": (Psycopg2Commands, None),
    "psycopg": (Psycopg3Commands, Psycopg3CommandsAsync),
    "aiopg": (None, AiopgCommands),
    "mysql": (MySqlConnectorPythonCommands, None),
    "pymssql": (PymssqlCommands, None),
    "oracledb": (OracledbCommands, None),
    "google": (GoogleBigqueryClientCommands, None),
}


def test_first_party_capability_audit_covers_every_registered_command_class(adapter_registry):
    # first-party adapters register lazily now, so load them through the real installed metadata
    # and audit the command classes those registrations actually carry
    registered = {
        command_class
        for name in FIRST_PARTY_ADAPTER_TABLE
        for registration in [main._resolve_adapter_registration(name)]
        for command_class in (registration.commands, registration.async_commands)
        if command_class is not None
    }

    assert registered == set(FIRST_PARTY_COMMAND_CLASSES)


def test_first_party_adapter_name_and_command_class_mappings(adapter_registry):
    # resolves each stable name through the real installed entry points rather than reading an
    # eagerly populated registry, which no longer exists
    for name, (commands, async_commands) in FIRST_PARTY_ADAPTER_TABLE.items():
        adapter_registry.pop(name, None)
        registration = main._resolve_adapter_registration(name)
        assert registration.commands is commands
        assert registration.async_commands is async_commands
        assert adapter_registry[name] is registration


@pytest.mark.parametrize(
    ("module", "commands_class"),
    [
        ("psycopg2.extensions", Psycopg2Commands),
        ("psycopg.connection", Psycopg3Commands),
        ("mysql.connector.connection_cext", MySqlConnectorPythonCommands),
        ("pymssql._pymssql", PymssqlCommands),
        ("oracledb", OracledbCommands),
        ("google.cloud.bigquery.dbapi.connection", GoogleBigqueryClientCommands),
    ],
)
def test_first_party_sync_detection_uses_documented_connection_modules(adapter_registry, module, commands_class):
    connection_class = type("NativeConnection", (), {"__module__": module})

    assert isinstance(pydapper.using(connection_class()), commands_class)


@pytest.mark.parametrize(
    ("module", "commands_class"),
    [
        ("psycopg.connection_async", Psycopg3CommandsAsync),
        ("aiopg.connection", AiopgCommands),
    ],
)
def test_first_party_async_detection_uses_documented_connection_modules(adapter_registry, module, commands_class):
    connection_class = type("NativeConnection", (), {"__module__": module})

    assert isinstance(pydapper.using_async(connection_class()), commands_class)


def test_first_party_detection_supports_sqlite_native_connections_and_subclasses(adapter_registry):
    class SubclassedConnection(sqlite3.Connection):
        pass

    native_connection = sqlite3.connect(":memory:")
    subclassed_connection = sqlite3.connect(":memory:", factory=SubclassedConnection)
    try:
        assert isinstance(pydapper.using(native_connection), Sqlite3Commands)
        assert isinstance(pydapper.using(subclassed_connection), Sqlite3Commands)
    finally:
        native_connection.close()
        subclassed_connection.close()


def test_first_party_detection_inspects_the_full_mro(adapter_registry):
    native_connection_class = type("NativeConnection", (), {"__module__": "mysql.connector.connection"})
    wrapper_subclass = type("ConnectionSubclass", (native_connection_class,), {"__module__": "application.db"})

    assert isinstance(pydapper.using(wrapper_subclass()), MySqlConnectorPythonCommands)


def test_first_party_detection_uses_anchored_module_prefixes(adapter_registry):
    unrelated_connection_class = type("UnrelatedConnection", (), {"__module__": "application.sqlite3_proxy"})

    with pytest.raises(ValueError, match="adapter="):
        pydapper.using(unrelated_connection_class())


def test_first_party_detection_ignores_non_string_class_modules(adapter_registry):
    connection_class = type("ConnectionWithNonStringModule", (), {})
    connection_class.__module__ = None

    with pytest.raises(ValueError, match="adapter="):
        pydapper.using(connection_class())


def test_adapter_argument_is_keyword_only():
    with pytest.raises(TypeError):
        pydapper.using(MockConnection(), "sqlite3")
    with pytest.raises(TypeError):
        pydapper.using_async(MockAsyncConnection(), "psycopg")


def test_legacy_registration_exports_are_absent():
    assert not hasattr(pydapper, "register")
    assert not hasattr(pydapper, "register_async")
    assert not hasattr(main, "register")
    assert not hasattr(main, "register_async")
    assert not hasattr(main.CommandFactory, "sync_registry")
    assert not hasattr(main.CommandFactory, "async_registry")
