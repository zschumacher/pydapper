"""Packaging and lazy-bootstrap coverage for the first-party adapter entry points.

Exercises the *installed* ``pydapper`` distribution metadata: the eight
``pydapper.adapters`` entry points it declares, and the fresh-process lazy
bootstrap they replace the old eager ``_builtin_adapters`` import with.

These tests own the packaging contract -- the exact installed entry-point
names, callback targets, and distribution identity -- and the process-level
consequences of the cutover: a plain ``import pydapper`` registers nothing,
discovery alone imports nothing, and the public name-based and automatic paths
load real first-party providers lazily from the installed metadata. The
callback registration table itself is covered in
tests/test_first_party_adapter_providers.py, and the discovery/loader/resolver
composition against fake metadata is covered in tests/test_adapter_*.py;
neither is duplicated here.

Process-level facts are asserted in clean subprocesses rather than by deleting
entries from this process's ``sys.modules``. Subprocesses run metadata-isolated
-- they see only the installed ``pydapper`` distribution's metadata -- and
in-process assertions filter real metadata by the ``pydapper`` distribution, so
unrelated entry points installed on a developer machine can never decide an
outcome here.
"""

import configparser
import importlib.metadata
import json
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import types
import zipfile

import pytest

import pydapper
import pydapper.main as main
from pydapper import _adapter_discovery
from tests.mocks import MockCommands

pytestmark = pytest.mark.core

GROUP = "pydapper.adapters"
DISTRIBUTION = "pydapper"
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# the exact installed entry-point table #468 requires: eight names, eight callback targets,
# no aliases, no duplicates
EXPECTED_ENTRY_POINTS = {
    "sqlite3": "pydapper._adapter_providers:_register_sqlite3_provider",
    "psycopg2": "pydapper._adapter_providers:_register_psycopg2_provider",
    "psycopg": "pydapper._adapter_providers:_register_psycopg_provider",
    "aiopg": "pydapper._adapter_providers:_register_aiopg_provider",
    "mysql": "pydapper._adapter_providers:_register_mysql_provider",
    "pymssql": "pydapper._adapter_providers:_register_pymssql_provider",
    "oracledb": "pydapper._adapter_providers:_register_oracledb_provider",
    "google": "pydapper._adapter_providers:_register_google_provider",
}

# every optional driver the lazy bootstrap must never pull in; the standard-library ``sqlite3``
# module is deliberately absent because the SQLite command implementation legitimately imports it
OPTIONAL_DRIVERS = (
    "psycopg2",
    "psycopg",
    "aiopg",
    "mysql.connector",
    "pymssql",
    "oracledb",
    "google.cloud.bigquery.dbapi",
)

COMMAND_MODULES = (
    "pydapper.sqlite",
    "pydapper.postgresql",
    "pydapper.mysql",
    "pydapper.mssql",
    "pydapper.oracle",
    "pydapper.bigquery",
)


def never_matches(connection):
    return False


@pytest.fixture
def isolated_state(monkeypatch):
    """Give an in-process test a private registry, provider catalog, and loader cache.

    Same snapshot/restore discipline as the other adapter test modules: the
    state the process had already built is put back verbatim at teardown, and
    nothing another module leaked can decide whether a name resolves here.
    """
    registry = main._adapter_registry.copy()
    monkeypatch.setattr(main, "_adapter_registry", registry)
    monkeypatch.setattr(_adapter_discovery, "_catalog", None)
    monkeypatch.setattr(main, "_loaded_provider_registrations", {})
    yield registry


def run_in_subprocess(body):
    """Run a script in a clean, metadata-isolated interpreter and return its stdout.

    The interpreter starts with ``-I -S``, so the ambient ``site-packages``
    never joins ``sys.path``. The script sees exactly two extra path entries:
    the repository root, so ``import pydapper`` resolves, and a temporary
    directory holding only the installed ``pydapper`` distribution's
    ``METADATA`` and ``entry_points.txt`` copied verbatim. Unrelated
    distributions installed on a developer or CI machine therefore cannot add
    ``pydapper.adapters`` providers to these subprocesses or break their
    load-all passes.

    Every script ends by printing a sentinel, and the caller asserts on it, so a
    script that silently fails to reach its assertions cannot pass as a success.
    """
    distribution = importlib.metadata.distribution(DISTRIBUTION)
    with tempfile.TemporaryDirectory() as metadata_dir:
        dist_info = pathlib.Path(metadata_dir) / f"{DISTRIBUTION}-{distribution.version}.dist-info"
        dist_info.mkdir()
        for member in ("METADATA", "entry_points.txt"):
            content = distribution.read_text(member)
            assert content is not None, f"installed {DISTRIBUTION} distribution has no {member}"
            dist_info.joinpath(member).write_text(content)
        preamble = f"import sys\nsys.path[:0] = [{str(REPO_ROOT)!r}, {metadata_dir!r}]\n"
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-c", preamble + textwrap.dedent(body)],
            capture_output=True,
            text=True,
        )
    assert completed.returncode == 0, f"subprocess failed:\n{completed.stdout}\n{completed.stderr}"
    return completed.stdout


# a meta-path finder makes the driver-import assertions independent of which optional extras happen
# to be installed: a forbidden import fails loudly even when the driver is absent, where a
# sys.modules check would silently pass vacuously
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


def driver_guard_script(body):
    script = DRIVER_IMPORT_GUARD.format(forbidden=list(OPTIONAL_DRIVERS)) + textwrap.dedent(body)
    return script.replace("{command_modules!r}", repr(list(COMMAND_MODULES)))


# ---------------------------------------------------------------------------- installed metadata


def test_installed_distribution_declares_exactly_the_eight_entry_points():
    entry_points = [
        entry_point
        for entry_point in importlib.metadata.distribution(DISTRIBUTION).entry_points
        if entry_point.group == GROUP
    ]

    assert {entry_point.name: entry_point.value for entry_point in entry_points} == EXPECTED_ENTRY_POINTS
    # eight mappings and no duplicate or alias declarations hiding behind the dict comprehension
    assert len(entry_points) == len(EXPECTED_ENTRY_POINTS)


def test_group_enumeration_attributes_each_first_party_entry_point_to_pydapper():
    first_party = [
        entry_point
        for entry_point in importlib.metadata.entry_points(group=GROUP)
        if entry_point.dist is not None and main._canonicalize_distribution_name(entry_point.dist.name) == DISTRIBUTION
    ]

    assert {entry_point.name: entry_point.value for entry_point in first_party} == EXPECTED_ENTRY_POINTS
    assert len(first_party) == len(EXPECTED_ENTRY_POINTS)


def test_discovery_catalog_carries_first_party_descriptors_with_pydapper_identity(isolated_state):
    catalog = _adapter_discovery._get_provider_catalog()

    for name, value in EXPECTED_ENTRY_POINTS.items():
        first_party = [descriptor for descriptor in catalog[name] if main._is_first_party_provider(descriptor)]
        assert len(first_party) == 1, name
        assert first_party[0].name == name
        assert first_party[0].distribution == DISTRIBUTION
        assert first_party[0].entry_point.value == value
    # building the catalog registered nothing and loaded nothing
    assert main._loaded_provider_registrations == {}


# ---------------------------------------------------------------------------- built wheel metadata


def test_built_wheel_declares_exactly_the_eight_entry_points(tmp_path):
    """The built artifact itself carries the entry points, not just this installed environment.

    Builds the real wheel with the project's own build tooling and reads
    ``entry_points.txt`` straight out of the archive, so a packaging regression
    that only shows up in the published artifact -- and not in an editable
    development install -- fails here.
    """
    poetry = shutil.which("poetry")
    assert poetry is not None, "the poetry executable is required to build the wheel under test"

    completed = subprocess.run(
        [poetry, "build", "--format", "wheel", "--output", str(tmp_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, f"poetry build failed:\n{completed.stdout}\n{completed.stderr}"

    [wheel_path] = tmp_path.glob(f"{DISTRIBUTION}-*.whl")
    with zipfile.ZipFile(wheel_path) as wheel:
        [entry_points_member] = [name for name in wheel.namelist() if name.endswith(".dist-info/entry_points.txt")]
        entry_points_text = wheel.read(entry_points_member).decode("utf-8")

    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # entry-point names are exact and case-sensitive
    parser.read_string(entry_points_text)

    assert parser.sections() == [GROUP]
    assert dict(parser[GROUP]) == EXPECTED_ENTRY_POINTS


# ---------------------------------------------------------------------------- fresh-process laziness


def test_plain_import_builds_no_state_and_imports_nothing():
    output = run_in_subprocess(driver_guard_script("""
        install_guard()
        assert_guard_is_armed()

        import pydapper
        import pydapper.main as main
        from pydapper import _adapter_discovery

        assert main._adapter_registry == {}, main._adapter_registry
        assert _adapter_discovery._catalog is None
        assert main._loaded_provider_registrations == {}
        assert "pydapper._adapter_providers" not in sys.modules
        for command_module in {command_modules!r}:
            assert command_module not in sys.modules, command_module
        print("PLAIN_IMPORT_UNTOUCHED")
        """))

    assert "PLAIN_IMPORT_UNTOUCHED" in output


def test_discovery_alone_builds_metadata_but_imports_and_registers_nothing():
    output = run_in_subprocess(driver_guard_script("""
        install_guard()
        assert_guard_is_armed()

        import pydapper
        import pydapper.main as main
        from pydapper import _adapter_discovery

        catalog = _adapter_discovery._get_provider_catalog()

        first_party = {
            name
            for name, descriptors in catalog.items()
            if any(main._is_first_party_provider(descriptor) for descriptor in descriptors)
        }
        assert first_party == {expected_names!r}, first_party
        assert _adapter_discovery._catalog is catalog
        assert main._adapter_registry == {}, main._adapter_registry
        assert main._loaded_provider_registrations == {}
        assert "pydapper._adapter_providers" not in sys.modules
        for command_module in {command_modules!r}:
            assert command_module not in sys.modules, command_module
        print("DISCOVERY_ONLY_METADATA")
        """.replace("{expected_names!r}", repr(set(EXPECTED_ENTRY_POINTS)))))

    assert "DISCOVERY_ONLY_METADATA" in output


def test_exact_name_sqlite_connect_loads_only_the_sqlite3_provider():
    output = run_in_subprocess(driver_guard_script("""
        install_guard()
        assert_guard_is_armed()

        import pydapper
        import pydapper.main as main

        with pydapper.connect("sqlite:///:memory:") as commands:
            commands.execute("create table task (id integer primary key, description text)")
            commands.execute(
                "insert into task (id, description) values (?id?, ?description?)",
                param={"id": 1, "description": "lazy"},
            )
            assert commands.execute_scalar("select description from task where id = 1") == "lazy"

        assert list(main._adapter_registry) == ["sqlite3"], list(main._adapter_registry)
        for command_module in {command_modules!r}:
            if command_module not in ("pydapper.sqlite",):
                assert command_module not in sys.modules, command_module
        print("EXACT_NAME_SQLITE_LAZY")
        """))

    assert "EXACT_NAME_SQLITE_LAZY" in output


def test_explicit_async_adapter_loads_only_the_requested_provider():
    output = run_in_subprocess(driver_guard_script("""
        install_guard()
        assert_guard_is_armed()

        import pydapper
        import pydapper.main as main

        # a service-free fake whose class module proves nothing: explicit adapter= must resolve
        # the real installed aiopg entry point and never consult a predicate
        connection = type("FakeAsyncConnection", (object,), {"__module__": "application.pool"})()
        commands = pydapper.using_async(connection, adapter="aiopg")

        assert type(commands).__name__ == "AiopgCommands"
        assert type(commands).__module__ == "pydapper.postgresql.aiopg"
        assert commands.connection is connection
        assert list(main._adapter_registry) == ["aiopg"], list(main._adapter_registry)
        for command_module in {command_modules!r}:
            if command_module != "pydapper.postgresql":
                assert command_module not in sys.modules, command_module
        print("EXPLICIT_ASYNC_LAZY")
        """))

    assert "EXPLICIT_ASYNC_LAZY" in output


def test_automatic_sync_selection_loads_every_first_party_provider_and_selects_sqlite():
    output = run_in_subprocess(driver_guard_script("""
        install_guard()
        assert_guard_is_armed()

        import sqlite3

        import pydapper
        import pydapper.main as main

        connection = sqlite3.connect(":memory:")
        try:
            commands = pydapper.using(connection)
            assert type(commands).__name__ == "Sqlite3Commands"
            assert commands.execute_scalar("select 41 + 1") == 42
        finally:
            connection.close()

        # the metadata-isolated interpreter sees only the pydapper distribution, so loading every
        # provider registers exactly the eight first-party names and imports their command modules
        # but, per the guard, no optional driver
        assert set(main._adapter_registry) == {expected_names!r}, set(main._adapter_registry)
        print("AUTOMATIC_SYNC_LOADS_ALL")
        """.replace("{expected_names!r}", repr(set(EXPECTED_ENTRY_POINTS)))))

    assert "AUTOMATIC_SYNC_LOADS_ALL" in output


def test_automatic_async_selection_selects_from_real_metadata_without_importing_the_driver():
    output = run_in_subprocess(driver_guard_script("""
        install_guard()
        assert_guard_is_armed()

        import pydapper
        import pydapper.main as main

        # the class module matches the aiopg predicate, but the aiopg driver itself must never
        # be imported to answer automatic selection
        connection = type("FakeAsyncConnection", (object,), {"__module__": "aiopg.connection"})()
        commands = pydapper.using_async(connection)

        assert type(commands).__name__ == "AiopgCommands"
        assert commands.connection is connection
        assert set(main._adapter_registry) == {expected_names!r}, set(main._adapter_registry)
        print("AUTOMATIC_ASYNC_LAZY")
        """.replace("{expected_names!r}", repr(set(EXPECTED_ENTRY_POINTS)))))

    assert "AUTOMATIC_ASYNC_LAZY" in output


# ---------------------------------------------------------------------------- precedence over real metadata


def test_direct_registration_wins_over_the_real_first_party_entry_point(isolated_state):
    isolated_state.pop("sqlite3", None)
    pydapper.register_adapter("sqlite3", commands=MockCommands, using_connection_predicate=never_matches)
    direct_record = main._adapter_registry["sqlite3"]

    connection = sqlite3.connect(":memory:")
    try:
        commands = pydapper.using(connection, adapter="sqlite3")
    finally:
        connection.close()

    assert isinstance(commands, MockCommands)
    assert main._adapter_registry["sqlite3"] is direct_record
    # the real installed provider was never selected or loaded, and resolution never even had to
    # discover the catalog to serve the registered name
    assert main._loaded_provider_registrations == {}
    assert _adapter_discovery._catalog is None


# ---------------------------------------------------------------------------- public surface


def test_packaging_adds_no_public_package_root_api():
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
