from contextlib import suppress

import pytest

from pydapper.commands import Commands
from pydapper.oracle import OracledbCommands
from pydapper.testing.adapter_conformance import SyncAdapterHarness
from pydapper.testing.adapter_conformance import run_core_sync
from tests.conformance_support import FIRST_PARTY_CONFORMANCE_ENTRIES
from tests.conformance_support import seed_through_adapter

pytestmark = pytest.mark.oracle

_DROP = "BEGIN EXECUTE IMMEDIATE 'DROP TABLE pydapper_conformance'; EXCEPTION WHEN OTHERS THEN NULL; END;"
_CREATE = (
    "CREATE TABLE pydapper_conformance "
    "(id NUMBER(10) PRIMARY KEY, label VARCHAR2(64), score NUMBER(10), note VARCHAR2(64))"
)


def _run_plsql_block(commands: Commands, block: str) -> None:
    """Run an anonymous PL/SQL block on the DBAPI cursor.

    A pydapper command executes exactly one statement, and the guard is lexical: the top-level ';'
    inside a ``BEGIN ... END;`` block trips it. Driving the cursor directly is the documented escape
    hatch for blocks and scripts, and this harness is the first-party demonstration of it.
    """
    with commands.connection.cursor() as cursor:
        cursor.execute(block)


class _OracledbConformanceHarness(SyncAdapterHarness):
    adapter_name = "oracledb"
    command_class = OracledbCommands
    # unquoted Oracle identifiers fold to uppercase, and Oracle stores '' as NULL —
    # both are documented, narrow dialect knobs rather than case opt-outs
    column_case = "upper"
    supports_empty_strings = False
    sql_overrides = {"select_literal": "SELECT 1 FROM dual"}

    def __init__(self, server, db_port, database_name):
        self._oracle_dsn = f"{server}:{db_port}/{database_name}"
        self.connect_dsn = f"oracle://pydapper:pydapper@{server}:{db_port}/{database_name}"

    def create_commands(self) -> Commands:
        import oracledb

        commands = OracledbCommands(oracledb.connect(password="pydapper", user="pydapper", dsn=self._oracle_dsn))
        _run_plsql_block(commands, _DROP)
        commands.execute(_CREATE)
        seed_through_adapter(commands, self.table_name, supports_empty_strings=False)
        commands.connection.commit()
        return commands

    def teardown_commands(self, commands: Commands) -> None:
        with suppress(Exception):
            commands.connection.rollback()
            _run_plsql_block(commands, _DROP)
        commands.connection.close()


def test_oracledb_core_sync_conformance(server, db_port, database_name):
    entry = FIRST_PARTY_CONFORMANCE_ENTRIES[("oracledb", "sync")]
    harness = _OracledbConformanceHarness(server, db_port, database_name)
    assert harness.adapter_name == entry.adapter_name
    assert harness.command_class is entry.command_class
    report = run_core_sync(harness)
    report.raise_for_failures()
    assert report.covers_full_inventory
    # profile planning is declaration-driven: prove the live run actually included it
    assert any(result.profile_id == "transactions" for result in report.results)
