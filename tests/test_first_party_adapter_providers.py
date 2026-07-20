"""Focused coverage for the first-party adapter provider callbacks.

Exercises ``pydapper._adapter_providers`` -- the eight zero-argument callbacks a
later #468 slice will target from ``pydapper.adapters`` entry-point metadata --
and the eager ``_builtin_adapters`` bootstrap that currently delegates to them.

These tests own the *callback contract* and the *registration table*: the exact
name each callback registers, its sync/async shape, its command classes, its
connection-predicate semantics, and the fact that neither invoking a callback
nor evaluating a predicate imports an optional database driver. The generic
provider loader's callback validation, hostile-callback defenses, and
transactional rollback already have dedicated coverage in
tests/test_adapter_loading.py, tests/test_adapter_resolution.py, and
tests/test_adapter_load_all.py and are not duplicated here.

Process-level facts -- driver import laziness and fresh-interpreter bootstrap
order -- are asserted in clean subprocesses rather than by deleting entries from
this process's ``sys.modules``.
"""

import inspect
import json
import subprocess
import sys
import textwrap
import typing

import pytest

import pydapper
import pydapper.main as main
from pydapper import _adapter_providers
from pydapper import _builtin_adapters
from pydapper.bigquery import GoogleBigqueryClientCommands
from pydapper.mssql import PymssqlCommands
from pydapper.mysql import MySqlConnectorPythonCommands
from pydapper.oracle import OracledbCommands
from pydapper.postgresql import AiopgCommands
from pydapper.postgresql import Psycopg2Commands
from pydapper.postgresql import Psycopg3Commands
from pydapper.postgresql import Psycopg3CommandsAsync
from pydapper.sqlite import Sqlite3Commands

pytestmark = pytest.mark.core


# the registration table this slice must preserve exactly, in the original bootstrap order:
# (callback attribute name, adapter name, sync commands, async commands, connection module prefix)
PROVIDER_TABLE = (
    ("_register_sqlite3_provider", "sqlite3", Sqlite3Commands, None, "sqlite3"),
    ("_register_psycopg2_provider", "psycopg2", Psycopg2Commands, None, "psycopg2"),
    ("_register_psycopg_provider", "psycopg", Psycopg3Commands, Psycopg3CommandsAsync, "psycopg"),
    ("_register_aiopg_provider", "aiopg", None, AiopgCommands, "aiopg"),
    ("_register_mysql_provider", "mysql", MySqlConnectorPythonCommands, None, "mysql.connector"),
    ("_register_pymssql_provider", "pymssql", PymssqlCommands, None, "pymssql"),
    ("_register_oracledb_provider", "oracledb", OracledbCommands, None, "oracledb"),
    ("_register_google_provider", "google", GoogleBigqueryClientCommands, None, "google.cloud.bigquery.dbapi"),
)

EXPECTED_NAMES = tuple(row[1] for row in PROVIDER_TABLE)

# every optional driver a provider callback or a connection predicate must never pull in. The
# standard-library ``sqlite3`` module is deliberately absent: importing it through the SQLite
# command implementation is acceptable.
OPTIONAL_DRIVERS = (
    "psycopg2",
    "psycopg",
    "aiopg",
    "mysql.connector",
    "pymssql",
    "oracledb",
    "google.cloud.bigquery.dbapi",
)


def table_row(callback_attr):
    for row in PROVIDER_TABLE:
        if row[0] == callback_attr:
            return row
    raise AssertionError(f"{callback_attr} is not in the expected provider table")  # pragma: no cover


def callback(callback_attr):
    return getattr(_adapter_providers, callback_attr)


def ids(rows):
    return [row[1] for row in rows]


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    """Give each test a private registry, provider catalog, and loader cache.

    Every piece of process state these tests touch is swapped through
    monkeypatch, so this is a real snapshot/restore rather than a reset: state
    the process had already built is put back verbatim at teardown and nothing
    here can decide whether a name resolves in another module. First-party
    adapters are still eagerly registered at import time in this slice, so the
    registry is copied rather than emptied.
    """
    registry = main._adapter_registry.copy()
    monkeypatch.setattr(main, "_adapter_registry", registry)
    monkeypatch.setattr(main, "_loaded_provider_registrations", {})
    yield registry


@pytest.fixture
def register_fresh(isolated_registry):
    """Invoke one provider callback with its own name not yet registered.

    Returns ``(result, registration, before)`` so a test can assert the callback's
    return value, the registration it produced, and that it disturbed nothing else.
    """

    def invoke(callback_attr):
        name = table_row(callback_attr)[1]
        isolated_registry.pop(name, None)
        before = dict(isolated_registry)
        result = callback(callback_attr)()
        return result, isolated_registry[name], before

    return invoke


def connection_from_module(module, *, bases=()):
    """Build a connection object whose type reports ``module`` as its ``__module__``."""
    return type("FakeConnection", bases or (object,), {"__module__": module})()


def run_in_subprocess(body):
    """Run a script in a clean interpreter and return its stdout.

    Every script ends by printing a sentinel, and the caller asserts on it, so a
    script that silently fails to reach its assertions cannot pass as a success.
    """
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, f"subprocess failed:\n{completed.stdout}\n{completed.stderr}"
    return completed.stdout


# a meta-path finder makes the driver-import assertions independent of which optional extras happen
# to be installed: a forbidden import fails loudly even when the driver is absent, where a
# sys.modules check would silently pass
DRIVER_IMPORT_GUARD = """
import sys

FORBIDDEN = {forbidden!r}


class ForbiddenDriverImport(AssertionError):
    pass


class DriverImportGuard:
    def find_spec(self, fullname, path=None, target=None):
        for prefix in FORBIDDEN:
            if fullname == prefix or fullname.startswith(prefix + "."):
                raise ForbiddenDriverImport(fullname)
        return None


def install_guard():
    for prefix in FORBIDDEN:
        assert prefix not in sys.modules, prefix
    sys.meta_path.insert(0, DriverImportGuard())


def assert_guard_is_armed():
    # proves the guard would really fire, so a passing driver-laziness test can never be a
    # silently inert import hook
    try:
        __import__(FORBIDDEN[0])
    except ForbiddenDriverImport:
        return
    raise AssertionError("driver import guard did not fire")
"""

# a bootstrap stub lets a subprocess import the provider module *without* the eager
# `_builtin_adapters` bootstrap having populated the registry first, which is how the next slice
# will import it. Seeding sys.modules is the only way to observe that today, since importing any
# pydapper submodule runs the package __init__.
BOOTSTRAP_STUB = """
import sys
import types

sys.modules["pydapper._builtin_adapters"] = types.ModuleType("pydapper._builtin_adapters")
"""


def driver_guard_script(body):
    return DRIVER_IMPORT_GUARD.format(forbidden=list(OPTIONAL_DRIVERS)) + textwrap.dedent(body)


def bootstrap_stub_script(body):
    return BOOTSTRAP_STUB + textwrap.dedent(body)


# ---------------------------------------------------------------------------- callback surface


def test_module_exposes_exactly_the_eight_intended_callbacks():
    discovered = sorted(
        name
        for name, value in vars(_adapter_providers).items()
        if name.startswith("_register_") and name.endswith("_provider") and inspect.isfunction(value)
    )

    assert discovered == sorted(row[0] for row in PROVIDER_TABLE)


def test_provider_tuple_holds_the_eight_callbacks_in_registration_order():
    assert _adapter_providers._FIRST_PARTY_ADAPTER_PROVIDERS == tuple(callback(row[0]) for row in PROVIDER_TABLE)


@pytest.mark.parametrize("row", PROVIDER_TABLE, ids=ids(PROVIDER_TABLE))
def test_callback_is_synchronous_zero_argument_and_annotated_none(row):
    fn = callback(row[0])

    assert inspect.isfunction(fn)
    assert not inspect.iscoroutinefunction(fn)
    assert not inspect.isasyncgenfunction(fn)
    assert not inspect.isgeneratorfunction(fn)
    assert list(inspect.signature(fn).parameters) == []
    assert typing.get_type_hints(fn)["return"] is type(None)


@pytest.mark.parametrize("row", PROVIDER_TABLE, ids=ids(PROVIDER_TABLE))
def test_callback_returns_none(row, register_fresh):
    result, _, _ = register_fresh(row[0])

    assert result is None


# ---------------------------------------------------------------------------- registration effect


@pytest.mark.parametrize("row", PROVIDER_TABLE, ids=ids(PROVIDER_TABLE))
def test_callback_adds_exactly_one_registration_with_its_assigned_name(row, register_fresh, isolated_registry):
    _, registration, before = register_fresh(row[0])

    assert list(isolated_registry) == list(before) + [row[1]]
    assert registration.name == row[1]


@pytest.mark.parametrize("row", PROVIDER_TABLE, ids=ids(PROVIDER_TABLE))
def test_callback_leaves_unrelated_registrations_unchanged(row, register_fresh, isolated_registry):
    _, _, before = register_fresh(row[0])

    assert list(isolated_registry)[: len(before)] == list(before)
    for name, registration in before.items():
        assert isolated_registry[name] is registration


@pytest.mark.parametrize("row", PROVIDER_TABLE, ids=ids(PROVIDER_TABLE))
def test_callback_registers_the_expected_command_classes(row, register_fresh):
    _, registration, _ = register_fresh(row[0])

    assert registration.commands is row[2]
    assert registration.async_commands is row[3]


def test_psycopg_registers_both_modes_through_one_callback(register_fresh, isolated_registry):
    _, registration, before = register_fresh("_register_psycopg_provider")

    assert list(isolated_registry) == list(before) + ["psycopg"]
    assert registration.commands is Psycopg3Commands
    assert registration.async_commands is Psycopg3CommandsAsync


def test_aiopg_remains_async_only(register_fresh):
    _, registration, _ = register_fresh("_register_aiopg_provider")

    assert registration.commands is None
    assert registration.async_commands is AiopgCommands


@pytest.mark.parametrize(
    "row", [row for row in PROVIDER_TABLE if row[1] not in {"psycopg", "aiopg"}], ids=lambda row: row[1]
)
def test_non_psycopg_adapters_remain_sync_only(row, register_fresh):
    _, registration, _ = register_fresh(row[0])

    assert registration.commands is row[2]
    assert registration.async_commands is None


@pytest.mark.parametrize("row", PROVIDER_TABLE, ids=ids(PROVIDER_TABLE))
def test_callback_on_an_already_registered_name_raises_and_preserves_the_registration(row, isolated_registry):
    name = row[1]
    existing = isolated_registry[name]
    before = dict(isolated_registry)

    with pytest.raises(ValueError, match=f"Adapter {name!r} is already registered"):
        callback(row[0])()

    assert list(isolated_registry) == list(before)
    assert isolated_registry[name] is existing
    for other, registration in before.items():
        assert isolated_registry[other] is registration


# ---------------------------------------------------------------------------- connection predicates


@pytest.mark.parametrize("row", PROVIDER_TABLE, ids=ids(PROVIDER_TABLE))
def test_predicate_accepts_the_exact_driver_module_prefix(row, register_fresh):
    _, registration, _ = register_fresh(row[0])

    assert registration.using_connection_predicate(connection_from_module(row[4])) is True


@pytest.mark.parametrize("row", PROVIDER_TABLE, ids=ids(PROVIDER_TABLE))
def test_predicate_accepts_a_subclass_of_a_driver_connection(row, register_fresh):
    _, registration, _ = register_fresh(row[0])
    driver_connection_class = type("DriverConnection", (object,), {"__module__": row[4]})
    subclass = type("UserSubclass", (driver_connection_class,), {"__module__": "application.pool"})

    assert registration.using_connection_predicate(subclass()) is True


@pytest.mark.parametrize("row", PROVIDER_TABLE, ids=ids(PROVIDER_TABLE))
def test_predicate_accepts_driver_child_modules(row, register_fresh):
    _, registration, _ = register_fresh(row[0])

    assert registration.using_connection_predicate(connection_from_module(f"{row[4]}.connection")) is True


@pytest.mark.parametrize("row", PROVIDER_TABLE, ids=ids(PROVIDER_TABLE))
def test_predicate_rejects_case_differences_near_prefixes_and_unrelated_modules(row, register_fresh):
    _, registration, _ = register_fresh(row[0])
    predicate = registration.using_connection_predicate

    assert predicate(connection_from_module(row[4].upper())) is False
    assert predicate(connection_from_module(row[4].capitalize())) is False
    assert predicate(connection_from_module(f"{row[4]}evil")) is False
    assert predicate(connection_from_module(f"{row[4]}evil.connection")) is False
    assert predicate(connection_from_module(f"not_{row[4]}")) is False
    assert predicate(connection_from_module("totally.unrelated.driver")) is False


def test_psycopg_predicate_does_not_claim_psycopg2_connections(register_fresh):
    _, psycopg, _ = register_fresh("_register_psycopg_provider")
    _, psycopg2, _ = register_fresh("_register_psycopg2_provider")

    assert psycopg.using_connection_predicate(connection_from_module("psycopg2")) is False
    assert psycopg2.using_connection_predicate(connection_from_module("psycopg")) is False
    assert psycopg.using_connection_predicate(connection_from_module("psycopg.connection")) is True


def test_predicate_ignores_a_non_string_module(register_fresh):
    _, registration, _ = register_fresh("_register_sqlite3_provider")
    hostile = type("Hostile", (object,), {"__module__": 42})()

    assert registration.using_connection_predicate(hostile) is False


def test_predicate_matches_through_a_non_string_module_in_the_mro(register_fresh):
    _, registration, _ = register_fresh("_register_sqlite3_provider")
    driver_base = type("DriverConnection", (object,), {"__module__": "sqlite3"})
    hostile = type("Hostile", (driver_base,), {"__module__": 42})()

    assert registration.using_connection_predicate(hostile) is True


# ---------------------------------------------------------------------------- import laziness


def test_callback_invocation_imports_no_optional_driver():
    output = run_in_subprocess(driver_guard_script("""
            install_guard()
            assert_guard_is_armed()

            import pydapper.main as main
            from pydapper import _adapter_providers

            # the eager bootstrap already invoked all eight callbacks during ``import pydapper``
            # above; invoke them again against an empty registry so the guard covers explicit
            # invocation the way the next slice's entry-point loader will do it
            main._adapter_registry = {}
            for provider in _adapter_providers._FIRST_PARTY_ADAPTER_PROVIDERS:
                assert provider() is None

            assert list(main._adapter_registry) == {names!r}
            print("INVOKED_WITHOUT_DRIVERS")
            """.replace("{names!r}", repr(list(EXPECTED_NAMES)))))

    assert "INVOKED_WITHOUT_DRIVERS" in output


def test_predicate_evaluation_imports_no_optional_driver():
    output = run_in_subprocess(driver_guard_script("""
            install_guard()
            assert_guard_is_armed()

            import pydapper.main as main

            evaluated = 0
            for registration in main._adapter_registry.values():
                for module in ("sqlite3", "psycopg2", "psycopg", "aiopg", "mysql.connector",
                               "pymssql", "oracledb", "google.cloud.bigquery.dbapi", "unrelated"):
                    connection = type("FakeConnection", (object,), {"__module__": module})()
                    assert registration.using_connection_predicate(connection) in (True, False)
                    evaluated += 1

            assert evaluated == 72, evaluated
            print("PREDICATES_WITHOUT_DRIVERS")
            """))

    assert "PREDICATES_WITHOUT_DRIVERS" in output


def test_importing_the_provider_module_alone_imports_no_command_module():
    output = run_in_subprocess(bootstrap_stub_script("""
        import pydapper._adapter_providers  # noqa: F401

        # importing the callbacks must not drag in every backend command module; the next slice
        # loads only the requested adapter's provider
        for command_module in ("pydapper.sqlite", "pydapper.postgresql", "pydapper.mysql",
                               "pydapper.mssql", "pydapper.oracle", "pydapper.bigquery"):
            assert command_module not in sys.modules, command_module
        print("PROVIDER_MODULE_IS_LAZY")
        """))

    assert "PROVIDER_MODULE_IS_LAZY" in output


def test_each_callback_imports_only_its_own_command_module():
    output = run_in_subprocess(bootstrap_stub_script("""
        import json

        from pydapper import _adapter_providers

        imported = {}
        for provider in _adapter_providers._FIRST_PARTY_ADAPTER_PROVIDERS:
            before = set(sys.modules)
            provider()
            imported[provider.__name__] = sorted(
                name for name in set(sys.modules) - before if name.startswith("pydapper.")
            )
        print(json.dumps(imported))
        """))
    imported = json.loads(output.strip().splitlines()[-1])

    # each callback pulls in its own backend package the first time that package is needed;
    # psycopg/aiopg share the already-imported pydapper.postgresql package
    assert imported["_register_sqlite3_provider"] == ["pydapper.sqlite", "pydapper.sqlite.sqlite3"]
    assert "pydapper.postgresql" in imported["_register_psycopg2_provider"]
    assert imported["_register_psycopg_provider"] == []
    assert imported["_register_aiopg_provider"] == []
    assert "pydapper.mysql" in imported["_register_mysql_provider"]
    assert "pydapper.mssql" in imported["_register_pymssql_provider"]
    assert "pydapper.oracle" in imported["_register_oracledb_provider"]
    assert "pydapper.bigquery" in imported["_register_google_provider"]
    # no callback reaches into another adapter's backend package
    assert not any(name.startswith("pydapper.bigquery") for name in imported["_register_sqlite3_provider"])


# ---------------------------------------------------------------------------- eager bootstrap


def test_fresh_import_still_registers_the_eight_names_in_order():
    output = run_in_subprocess("""
        import json

        import pydapper
        import pydapper.main as main

        print(json.dumps(list(main._adapter_registry)))
        """)

    assert json.loads(output.strip().splitlines()[-1]) == list(EXPECTED_NAMES)


def test_fresh_import_registers_the_expected_shapes():
    output = run_in_subprocess("""
        import json

        import pydapper
        import pydapper.main as main

        shapes = {
            name: [
                registration.commands.__name__ if registration.commands is not None else None,
                registration.async_commands.__name__ if registration.async_commands is not None else None,
            ]
            for name, registration in main._adapter_registry.items()
        }
        print(json.dumps(shapes))
        """)
    shapes = json.loads(output.strip().splitlines()[-1])

    assert shapes == {
        row[1]: [row[2].__name__ if row[2] is not None else None, row[3].__name__ if row[3] is not None else None]
        for row in PROVIDER_TABLE
    }


def test_eager_bootstrap_delegates_to_the_provider_callbacks(monkeypatch, isolated_registry):
    """The bootstrap is only ordering + invocation; the callbacks are the registration source."""
    calls = []

    def recorder(name):
        def record() -> None:
            calls.append(name)

        return record

    monkeypatch.setattr(
        _builtin_adapters,
        "_FIRST_PARTY_ADAPTER_PROVIDERS",
        tuple(recorder(row[1]) for row in PROVIDER_TABLE),
    )
    before = dict(isolated_registry)

    assert _builtin_adapters._register_builtin_adapters() is None

    assert calls == list(EXPECTED_NAMES)
    # with every callback stubbed out, the bootstrap registered nothing on its own
    assert list(isolated_registry) == list(before)


def test_bootstrap_uses_the_provider_tuple_as_its_single_registration_source():
    assert _builtin_adapters._FIRST_PARTY_ADAPTER_PROVIDERS is _adapter_providers._FIRST_PARTY_ADAPTER_PROVIDERS
    # no direct registration path or command-class import survives in the bootstrap module
    assert not hasattr(_builtin_adapters, "register_adapter")
    assert not hasattr(_builtin_adapters, "_connection_module_matches")
    for _, _, commands, async_commands, _ in PROVIDER_TABLE:
        for command_class in (commands, async_commands):
            if command_class is not None:
                assert not hasattr(_builtin_adapters, command_class.__name__)


# ---------------------------------------------------------------------------- public surface


def test_no_provider_callback_or_record_becomes_a_public_package_symbol():
    for callback_attr, *_ in PROVIDER_TABLE:
        assert not hasattr(pydapper, callback_attr)
    assert not hasattr(pydapper, "_FIRST_PARTY_ADAPTER_PROVIDERS")
    assert not hasattr(pydapper, "_connection_module_matches")

    # nothing this slice added is reachable by identity through a public package-root symbol
    private_objects = [callback(row[0]) for row in PROVIDER_TABLE]
    private_objects.append(_adapter_providers._FIRST_PARTY_ADAPTER_PROVIDERS)
    private_objects.append(_adapter_providers._connection_module_matches)
    for name in dir(pydapper):
        if not name.startswith("_"):
            attribute = getattr(pydapper, name)
            assert not any(attribute is private for private in private_objects), name

    # the provider module itself stays a private submodule and is not re-exported
    assert _adapter_providers.__name__ == "pydapper._adapter_providers"
    assert "adapter_providers" not in dir(pydapper)


def test_provider_module_registers_nothing_at_import_time():
    output = run_in_subprocess(bootstrap_stub_script("""
        # the provider module is imported here without the eager bootstrap having run, so any
        # import-time registration side effect in it would show up in the registry
        import pydapper.main as main

        assert list(main._adapter_registry) == [], list(main._adapter_registry)
        import pydapper._adapter_providers  # noqa: F401
        assert list(main._adapter_registry) == [], list(main._adapter_registry)
        print("NO_IMPORT_TIME_REGISTRATION")
        """))

    assert "NO_IMPORT_TIME_REGISTRATION" in output


# ---------------------------------------------------------------------------- unchanged behavior


def test_connect_still_resolves_a_first_party_adapter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pydapper.connect("sqlite+sqlite3://pydapper.db") as commands:
        assert isinstance(commands, Sqlite3Commands)
        assert commands.execute("create table t (id integer)") == -1


def test_explicit_selection_still_resolves_a_first_party_adapter():
    import sqlite3

    connection = sqlite3.connect(":memory:")
    try:
        commands = pydapper.using(connection, adapter="sqlite3")
        assert isinstance(commands, Sqlite3Commands)
    finally:
        connection.close()


def test_automatic_selection_still_resolves_a_first_party_adapter():
    import sqlite3

    connection = sqlite3.connect(":memory:")
    try:
        commands = pydapper.using(connection)
        assert isinstance(commands, Sqlite3Commands)
    finally:
        connection.close()
