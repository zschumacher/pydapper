from contextlib import suppress

import pytest

from pydapper.commands import Commands
from pydapper.mysql import MySqlConnectorPythonCommands
from pydapper.testing.adapter_conformance import SyncAdapterHarness
from pydapper.testing.adapter_conformance import run_core_sync
from tests.conformance_support import FIRST_PARTY_CONFORMANCE_ENTRIES
from tests.conformance_support import seed_through_adapter

pytestmark = pytest.mark.mysql

_TABLE = "pydapper.pydapper_conformance"
_DROP = f"DROP TABLE IF EXISTS {_TABLE}"
_CREATE = f"CREATE TABLE {_TABLE} (id INT PRIMARY KEY, label VARCHAR(64), score INT, note VARCHAR(64))"


class _MySqlConformanceHarness(SyncAdapterHarness):
    adapter_name = "mysql"
    command_class = MySqlConnectorPythonCommands
    table_name = _TABLE

    def __init__(self, server, db_port, database_name):
        self._connect_kwargs = {
            "host": server,
            "port": db_port,
            "user": "pydapper",
            "password": "pydapper",
            "database": database_name,
        }
        self.connect_dsn = f"mysql://pydapper:pydapper@{server}:{db_port}/{database_name}"

    def create_commands(self) -> Commands:
        import mysql.connector

        commands = MySqlConnectorPythonCommands(mysql.connector.connect(**self._connect_kwargs))
        commands.execute(_DROP)
        commands.execute(_CREATE)
        seed_through_adapter(commands, self.table_name)
        commands.connection.commit()
        return commands

    def teardown_commands(self, commands: Commands) -> None:
        with suppress(Exception):
            commands.execute(_DROP)
        commands.connection.close()


def test_mysql_core_sync_conformance(server, db_port, database_name):
    entry = FIRST_PARTY_CONFORMANCE_ENTRIES[("mysql", "sync")]
    harness = _MySqlConformanceHarness(server, db_port, database_name)
    assert harness.adapter_name == entry.adapter_name
    assert harness.command_class is entry.command_class
    run_core_sync(harness).raise_for_failures()
