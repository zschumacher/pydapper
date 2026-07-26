"""A complete third-party async-only adapter running the reusable conformance suite.

The "acmeaio" driver below is a tiny async facade over stdlib sqlite3, standing in
for a real async driver. The conformance API itself never calls ``asyncio.run()`` —
``run_core_async`` is awaited inside whatever event loop the caller owns, which here
is the one this script starts at the bottom.
"""

import asyncio
import sqlite3
import tempfile

import pydapper
from pydapper.commands import BaseSqlParamHandler
from pydapper.commands import CommandsAsync
from pydapper.testing.adapter_conformance import AsyncAdapterHarness
from pydapper.testing.adapter_conformance import run_core_async
from pydapper.testing.adapter_conformance import seed_rows

WORKDIR = tempfile.mkdtemp()


class AcmeAioCursor:
    """An async cursor facade over a sqlite3 cursor."""

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    async def execute(self, sql, parameters=None) -> None:
        if parameters is None:
            self._cursor.execute(sql)
        else:
            self._cursor.execute(sql, parameters)

    async def executemany(self, sql, seq_of_parameters=None) -> None:
        self._cursor.executemany(sql, seq_of_parameters or [])

    async def fetchone(self):
        return self._cursor.fetchone()

    async def fetchall(self):
        return self._cursor.fetchall()

    async def fetchmany(self, size=1):
        return self._cursor.fetchmany(size)

    async def close(self) -> None:
        self._cursor.close()


class AcmeAioConnection:
    """An async connection facade whose cursor() returns an awaitable."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    async def cursor(self, *args, **kwargs) -> AcmeAioCursor:
        return AcmeAioCursor(self._connection.cursor())

    def close(self) -> None:
        self._connection.close()


class AcmeAioCommands(CommandsAsync):
    class SqlParamHandler(BaseSqlParamHandler):
        def get_param_placeholder(self, param_name: str) -> str:
            return "?"

    @classmethod
    async def connect_async(cls, parsed_dsn, **connect_kwargs) -> "AcmeAioCommands":
        return cls(AcmeAioConnection(sqlite3.connect(parsed_dsn.database, **connect_kwargs)))


pydapper.register_adapter(
    "acmeaio",
    async_commands=AcmeAioCommands,
    using_connection_predicate=lambda connection: isinstance(connection, AcmeAioConnection),
)


class AcmeAioConformanceHarness(AsyncAdapterHarness):
    adapter_name = "acmeaio"
    command_class = AcmeAioCommands
    # four slashes make the sqlite path absolute; the +acmeaio suffix selects this adapter
    connect_dsn = f"sqlite+acmeaio:///{WORKDIR}/example.db"
    # our cursor() returns an awaitable, the CommandsAsync base contract; a driver whose
    # cursor() returns the cursor synchronously (like psycopg3 async) declares "synchronous"
    cursor_factory_style = "awaitable"

    async def create_commands(self) -> CommandsAsync:
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE pydapper_conformance (id INTEGER PRIMARY KEY, label TEXT, score INTEGER, note TEXT)"
        )
        connection.executemany(
            "INSERT INTO pydapper_conformance (id, label, score, note) VALUES (?, ?, ?, ?)",
            seed_rows(self.supports_empty_strings),
        )
        connection.commit()
        return AcmeAioCommands(AcmeAioConnection(connection))

    async def teardown_commands(self, commands: CommandsAsync) -> None:
        commands.connection.close()


async def main() -> None:
    report = await run_core_async(AcmeAioConformanceHarness())
    for failure in report.failures:
        print(f"{failure.profile_id}/{failure.case_id}: {failure.message}")
    print(f"{report.profile_id} for {report.adapter_name!r}: {len(report.results)} cases, passed={report.passed}")
    report.raise_for_failures()


asyncio.run(main())
# core-async for 'acmeaio': 58 cases, passed=True
