from contextlib import suppress

import pytest

from pydapper.commands import Commands
from pydapper.mssql import PymssqlCommands
from pydapper.testing.adapter_conformance import SyncAdapterHarness
from pydapper.testing.adapter_conformance import run_core_sync
from tests.conformance_support import FIRST_PARTY_CONFORMANCE_ENTRIES
from tests.conformance_support import seed_through_adapter

pytestmark = pytest.mark.mssql

_DROP = "DROP TABLE IF EXISTS pydapper_conformance"
_CREATE = "CREATE TABLE pydapper_conformance (id INT PRIMARY KEY, label NVARCHAR(64), score INT, note NVARCHAR(64))"


class _PymssqlConformanceHarness(SyncAdapterHarness):
    adapter_name = "pymssql"
    command_class = PymssqlCommands

    def __init__(self, server, db_port, database_name):
        self._connect_kwargs = {
            "server": server,
            "port": db_port,
            "user": "sa",
            "password": "pydapper!PYDAPPER",
            "database": database_name,
        }
        self.connect_dsn = f"mssql://sa:pydapper!PYDAPPER@{server}:{db_port}/{database_name}"

    def create_commands(self) -> Commands:
        from pymssql import _pymssql

        commands = PymssqlCommands(_pymssql.connect(**self._connect_kwargs))
        commands.execute(_DROP)
        commands.execute(_CREATE)
        seed_through_adapter(commands, self.table_name)
        commands.connection.commit()
        return commands

    def teardown_commands(self, commands: Commands) -> None:
        with suppress(Exception):
            commands.connection.rollback()
            commands.execute(_DROP)
            commands.connection.commit()
        commands.connection.close()


def test_pymssql_core_sync_conformance(server, db_port, database_name):
    entry = FIRST_PARTY_CONFORMANCE_ENTRIES[("pymssql", "sync")]
    harness = _PymssqlConformanceHarness(server, db_port, database_name)
    assert harness.adapter_name == entry.adapter_name
    assert harness.command_class is entry.command_class
    report = run_core_sync(harness)
    report.raise_for_failures()
    # profile planning is declaration-driven: prove the live run actually included it
    assert any(result.profile_id == "transactions" for result in report.results)
