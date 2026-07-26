import inspect
from contextlib import suppress

import pytest
import pytest_asyncio  # noqa: F401  (documents the async fixture plugin this module relies on)

from pydapper.commands import Commands
from pydapper.commands import CommandsAsync
from pydapper.postgresql import AiopgCommands
from pydapper.postgresql import Psycopg2Commands
from pydapper.postgresql import Psycopg3Commands
from pydapper.postgresql import Psycopg3CommandsAsync
from pydapper.testing.adapter_conformance import AsyncAdapterHarness
from pydapper.testing.adapter_conformance import SyncAdapterHarness
from pydapper.testing.adapter_conformance import run_core_async
from pydapper.testing.adapter_conformance import run_core_sync
from tests.conformance_support import FIRST_PARTY_CONFORMANCE_ENTRIES
from tests.conformance_support import seed_through_adapter
from tests.conformance_support import seed_through_adapter_async

pytestmark = pytest.mark.postgresql

_DROP = "DROP TABLE IF EXISTS pydapper_conformance"
_CREATE = "CREATE TABLE pydapper_conformance (id INTEGER PRIMARY KEY, label TEXT, score INTEGER, note TEXT)"


class _Psycopg2ConformanceHarness(SyncAdapterHarness):
    adapter_name = "psycopg2"
    command_class = Psycopg2Commands

    def __init__(self, server, db_port, database_name):
        self._url = f"postgresql://pydapper:pydapper@{server}:{db_port}/{database_name}"
        self.connect_dsn = self._url

    def create_commands(self) -> Commands:
        import psycopg2

        commands = Psycopg2Commands(psycopg2.connect(self._url))
        commands.execute(_DROP)
        commands.execute(_CREATE)
        seed_through_adapter(commands, self.table_name)
        return commands

    def teardown_commands(self, commands: Commands) -> None:
        try:
            commands.connection.rollback()
            # transaction-profile cases commit durable state; don't leave the table behind
            with suppress(Exception):
                commands.execute(_DROP)
                commands.connection.commit()
        finally:
            commands.connection.close()


class _Psycopg3SyncConformanceHarness(SyncAdapterHarness):
    adapter_name = "psycopg"
    command_class = Psycopg3Commands

    def __init__(self, server, db_port, database_name):
        self._url = f"postgresql://pydapper:pydapper@{server}:{db_port}/{database_name}"
        self.connect_dsn = f"postgresql+psycopg://pydapper:pydapper@{server}:{db_port}/{database_name}"

    def create_commands(self) -> Commands:
        import psycopg

        commands = Psycopg3Commands(psycopg.connect(self._url))
        commands.execute(_DROP)
        commands.execute(_CREATE)
        seed_through_adapter(commands, self.table_name)
        return commands

    def teardown_commands(self, commands: Commands) -> None:
        try:
            commands.connection.rollback()
            # transaction-profile cases commit durable state; don't leave the table behind
            with suppress(Exception):
                commands.execute(_DROP)
                commands.connection.commit()
        finally:
            commands.connection.close()


class _Psycopg3AsyncConformanceHarness(AsyncAdapterHarness):
    adapter_name = "psycopg"
    command_class = Psycopg3CommandsAsync
    # psycopg3's AsyncConnection.cursor() returns the cursor synchronously; the command
    # class normalizes it, so the instrumented connection must use the same shape
    cursor_factory_style = "synchronous"

    def __init__(self, server, db_port, database_name):
        self._url = f"postgresql://pydapper:pydapper@{server}:{db_port}/{database_name}"
        self.connect_dsn = f"postgresql+psycopg://pydapper:pydapper@{server}:{db_port}/{database_name}"

    async def create_commands(self) -> CommandsAsync:
        import psycopg

        connection = await psycopg.AsyncConnection.connect(self._url)
        commands = Psycopg3CommandsAsync(connection)
        await commands.execute_async(_DROP)
        await commands.execute_async(_CREATE)
        await seed_through_adapter_async(commands, self.table_name)
        return commands

    async def teardown_commands(self, commands: CommandsAsync) -> None:
        try:
            await commands.connection.rollback()
            # transaction-profile cases commit durable state; don't leave the table behind
            with suppress(Exception):
                await commands.execute_async(_DROP)
                await commands.connection.commit()
        finally:
            await commands.connection.close()


class _AiopgConformanceHarness(AsyncAdapterHarness):
    adapter_name = "aiopg"
    command_class = AiopgCommands

    def __init__(self, server, db_port, database_name):
        self._url = f"postgresql://pydapper:pydapper@{server}:{db_port}/{database_name}"
        self.connect_dsn = f"postgresql+aiopg://pydapper:pydapper@{server}:{db_port}/{database_name}"

    async def create_commands(self) -> CommandsAsync:
        import aiopg

        commands = AiopgCommands(await aiopg.connect(self._url))
        # aiopg is autocommit-only, so drop/create/seed take effect immediately
        await commands.execute_async(_DROP)
        await commands.execute_async(_CREATE)
        await seed_through_adapter_async(commands, self.table_name)
        return commands

    async def teardown_commands(self, commands: CommandsAsync) -> None:
        with suppress(Exception):
            await commands.execute_async(_DROP)
        result = commands.connection.close()
        if inspect.isawaitable(result):
            await result


def test_psycopg2_core_sync_conformance(server, db_port, database_name):
    entry = FIRST_PARTY_CONFORMANCE_ENTRIES[("psycopg2", "sync")]
    harness = _Psycopg2ConformanceHarness(server, db_port, database_name)
    assert harness.adapter_name == entry.adapter_name
    assert harness.command_class is entry.command_class
    report = run_core_sync(harness)
    report.raise_for_failures()
    # profile planning is declaration-driven: prove the live run actually included it
    assert any(result.profile_id == "transactions" for result in report.results)


def test_psycopg3_core_sync_conformance(server, db_port, database_name):
    entry = FIRST_PARTY_CONFORMANCE_ENTRIES[("psycopg", "sync")]
    harness = _Psycopg3SyncConformanceHarness(server, db_port, database_name)
    assert harness.adapter_name == entry.adapter_name
    assert harness.command_class is entry.command_class
    report = run_core_sync(harness)
    report.raise_for_failures()
    assert any(result.profile_id == "transactions" for result in report.results)


@pytest.mark.asyncio
async def test_psycopg3_core_async_conformance(server, db_port, database_name):
    entry = FIRST_PARTY_CONFORMANCE_ENTRIES[("psycopg", "async")]
    harness = _Psycopg3AsyncConformanceHarness(server, db_port, database_name)
    assert harness.adapter_name == entry.adapter_name
    assert harness.command_class is entry.command_class
    report = await run_core_async(harness)
    report.raise_for_failures()
    assert any(result.profile_id == "transactions" for result in report.results)


@pytest.mark.asyncio
async def test_aiopg_core_async_conformance(server, db_port, database_name):
    entry = FIRST_PARTY_CONFORMANCE_ENTRIES[("aiopg", "async")]
    harness = _AiopgConformanceHarness(server, db_port, database_name)
    assert harness.adapter_name == entry.adapter_name
    assert harness.command_class is entry.command_class
    report = await run_core_async(harness)
    report.raise_for_failures()
