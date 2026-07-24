"""Shared repository-test support for the adapter conformance suite.

This module is test infrastructure, not part of the shipped helper. It provides:

* a pure-Python in-memory fake DBAPI (no sqlite3, no drivers) plus mock sync/async
  command classes, so framework failures are visible with no database at all;
* a real in-memory SQLite harness factory for live ``core-sync`` coverage; and
* :data:`FIRST_PARTY_CONFORMANCE_ENTRIES` — the single source of truth mapping every
  installed first-party adapter mode to its concrete command class and the backend
  test module holding its live conformance entry. The drift test in
  ``tests/test_adapter_conformance.py`` checks this registry against the installed
  ``pydapper.adapters`` entry points, so no second manually maintained list can
  silently go stale.
"""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Type
from typing import Union

from pydapper.bigquery import GoogleBigqueryClientCommands
from pydapper.commands import BaseSqlParamHandler
from pydapper.commands import Commands
from pydapper.commands import CommandsAsync
from pydapper.mssql import PymssqlCommands
from pydapper.mysql import MySqlConnectorPythonCommands
from pydapper.oracle import OracledbCommands
from pydapper.postgresql import AiopgCommands
from pydapper.postgresql import Psycopg2Commands
from pydapper.postgresql import Psycopg3Commands
from pydapper.postgresql import Psycopg3CommandsAsync
from pydapper.sqlite import Sqlite3Commands
from pydapper.testing.adapter_conformance import CONFORMANCE_COLUMNS
from pydapper.testing.adapter_conformance import AsyncAdapterHarness
from pydapper.testing.adapter_conformance import SyncAdapterHarness
from pydapper.testing.adapter_conformance import seed_rows

MOCK_SYNC_ADAPTER_NAME = "conformance-mock-sync"
MOCK_ASYNC_ADAPTER_NAME = "conformance-mock-async"

_COLUMNS = ("id", "label", "score", "note")

_SELECT_RE = re.compile(r"^SELECT (?P<cols>.+?) FROM (?P<table>\S+)(?: WHERE (?P<where>.+?))?(?P<order> ORDER BY id)?$")
_INSERT_RE = re.compile(r"^INSERT INTO (?P<table>\S+) \((?P<cols>[^)]+)\) VALUES \((?P<vals>.+)\)$")
_UPDATE_RE = re.compile(r"^UPDATE (?P<table>\S+) SET label = %s WHERE id = %s$")


class MiniDbError(Exception):
    """Raised by the fake driver for SQL it does not model."""


class MiniDb:
    """A tiny pure-Python store understanding the conformance statement shapes."""

    def __init__(self, rows: Sequence[Tuple[Any, ...]] = ()) -> None:
        self.rows: List[Dict[str, Any]] = [dict(zip(_COLUMNS, row)) for row in rows]

    def _eval_where(self, where: Optional[str], row: Dict[str, Any], params: Sequence[Any]) -> bool:
        if where is None:
            return True
        if where == "id = %s":
            return row["id"] == params[0]
        if where == "score = %s":
            return row["score"] == params[0]
        if where == "id = %s AND %s = id":
            return row["id"] == params[0] and params[1] == row["id"]
        raise MiniDbError(f"unsupported WHERE clause: {where!r}")

    def select(self, sql: str, params: Sequence[Any]) -> Tuple[Tuple[str, ...], List[Tuple[Any, ...]]]:
        if sql == "SELECT 1":
            return ("1",), [(1,)]
        match = _SELECT_RE.match(sql)
        if match is None:
            raise MiniDbError(f"unsupported SELECT: {sql!r}")
        columns = tuple(part.strip() for part in match.group("cols").split(","))
        matched = [row for row in self.rows if self._eval_where(match.group("where"), row, params)]
        if match.group("order"):
            matched.sort(key=lambda row: row["id"])
        return columns, [tuple(row[column] for column in columns) for row in matched]

    def insert(self, sql: str, params: Sequence[Any]) -> int:
        match = _INSERT_RE.match(sql)
        if match is None:
            raise MiniDbError(f"unsupported INSERT: {sql!r}")
        columns = tuple(part.strip() for part in match.group("cols").split(","))
        self.rows.append(dict(zip(columns, params)))
        return 1

    def update(self, sql: str, params: Sequence[Any]) -> int:
        if _UPDATE_RE.match(sql) is None:
            raise MiniDbError(f"unsupported UPDATE: {sql!r}")
        label, row_id = params
        matched = [row for row in self.rows if row["id"] == row_id]
        for row in matched:
            row["label"] = label
        return len(matched)


class FakeSyncCursor:
    """A plain (close-only) sync cursor over :class:`MiniDb`."""

    def __init__(self, db: MiniDb) -> None:
        self._db = db
        self._results: List[Tuple[Any, ...]] = []
        self._columns: Tuple[str, ...] = ()
        self.rowcount = -1
        self.closed = False

    @property
    def description(self) -> Tuple[Tuple[Any, ...], ...]:
        return tuple((name, None, None, None, None, None, None) for name in self._columns)

    def _run(self, sql: str, params: Sequence[Any]) -> None:
        statement = sql.strip()
        if statement.upper().startswith("SELECT"):
            self._columns, self._results = self._db.select(statement, params)
            self.rowcount = -1
        elif statement.upper().startswith("INSERT"):
            self.rowcount = self._db.insert(statement, params)
            self._results = []
        elif statement.upper().startswith("UPDATE"):
            self.rowcount = self._db.update(statement, params)
            self._results = []
        else:
            raise MiniDbError(f"unsupported statement: {statement!r}")

    def execute(self, sql: str, parameters: Optional[Sequence[Any]] = None) -> None:
        self._run(sql, tuple(parameters or ()))

    def executemany(self, sql: str, seq_of_parameters: Optional[Sequence[Sequence[Any]]] = None) -> None:
        total = 0
        for parameters in seq_of_parameters or []:
            self._run(sql, tuple(parameters))
            total += max(self.rowcount, 0)
        self.rowcount = total

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        if not self._results:
            return None
        return self._results.pop(0)

    def fetchall(self) -> List[Tuple[Any, ...]]:
        results = self._results
        self._results = []
        return results

    def fetchmany(self, size: int = 1) -> List[Tuple[Any, ...]]:
        results = self._results[:size]
        del self._results[:size]
        return results

    def close(self) -> None:
        self.closed = True


class FakeSyncConnection:
    """A minimal sync DBAPI connection over :class:`MiniDb`."""

    def __init__(self, db: Optional[MiniDb] = None) -> None:
        self.db = db if db is not None else MiniDb()
        self.closed = False

    def cursor(self, *args: Any, **kwargs: Any) -> FakeSyncCursor:
        return FakeSyncCursor(self.db)

    def close(self) -> None:
        self.closed = True


class FakeAsyncCursor:
    """A plain async cursor (awaitable methods, synchronous ``close``) over :class:`MiniDb`."""

    def __init__(self, db: MiniDb) -> None:
        self._inner = FakeSyncCursor(db)

    @property
    def description(self) -> Tuple[Tuple[Any, ...], ...]:
        return self._inner.description

    @property
    def rowcount(self) -> int:
        return self._inner.rowcount

    async def execute(self, sql: str, parameters: Optional[Sequence[Any]] = None) -> None:
        self._inner.execute(sql, parameters)

    async def executemany(self, sql: str, seq_of_parameters: Optional[Sequence[Sequence[Any]]] = None) -> None:
        self._inner.executemany(sql, seq_of_parameters)

    async def fetchone(self) -> Optional[Tuple[Any, ...]]:
        return self._inner.fetchone()

    async def fetchall(self) -> List[Tuple[Any, ...]]:
        return self._inner.fetchall()

    async def fetchmany(self, size: int = 1) -> List[Tuple[Any, ...]]:
        return self._inner.fetchmany(size)

    def close(self) -> None:
        self._inner.close()


class FakeAsyncConnection:
    """A minimal async DBAPI connection whose ``cursor()`` returns an awaitable."""

    def __init__(self, db: Optional[MiniDb] = None) -> None:
        self.db = db if db is not None else MiniDb()
        self.closed = False

    async def cursor(self, *args: Any, **kwargs: Any) -> FakeAsyncCursor:
        return FakeAsyncCursor(self.db)

    def close(self) -> None:
        self.closed = True


class MockSyncConformanceCommands(Commands):
    """A third-party-shaped sync command class over the fake driver."""

    class SqlParamHandler(BaseSqlParamHandler):
        def get_param_placeholder(self, param_name: str) -> str:
            return "%s"

    @classmethod
    def connect(cls, parsed_dsn: Any, **connect_kwargs: Any) -> "MockSyncConformanceCommands":
        return cls(FakeSyncConnection())


class MockAsyncConformanceCommands(CommandsAsync):
    """A third-party-shaped async command class over the fake driver."""

    class SqlParamHandler(BaseSqlParamHandler):
        def get_param_placeholder(self, param_name: str) -> str:
            return "%s"

    @classmethod
    async def connect_async(cls, parsed_dsn: Any, **connect_kwargs: Any) -> "MockAsyncConformanceCommands":
        return cls(FakeAsyncConnection())


def seeded_mini_db(supports_empty_strings: bool = True) -> MiniDb:
    return MiniDb(seed_rows(supports_empty_strings))


class MockSyncConformanceHarness(SyncAdapterHarness):
    """Service-free mock sync harness; requires the mock adapter to be registered."""

    adapter_name = MOCK_SYNC_ADAPTER_NAME
    command_class = MockSyncConformanceCommands
    connect_dsn = f"sqlite+{MOCK_SYNC_ADAPTER_NAME}://mock"

    def create_commands(self) -> Commands:
        return MockSyncConformanceCommands(FakeSyncConnection(seeded_mini_db()))

    def teardown_commands(self, commands: Commands) -> None:
        commands.connection.close()


class MockAsyncConformanceHarness(AsyncAdapterHarness):
    """Service-free mock async harness; requires the mock adapter to be registered."""

    adapter_name = MOCK_ASYNC_ADAPTER_NAME
    command_class = MockAsyncConformanceCommands
    connect_dsn = f"sqlite+{MOCK_ASYNC_ADAPTER_NAME}://mock"

    async def create_commands(self) -> CommandsAsync:
        return MockAsyncConformanceCommands(FakeAsyncConnection(seeded_mini_db()))

    async def teardown_commands(self, commands: CommandsAsync) -> None:
        commands.connection.close()


SQLITE_CONFORMANCE_DDL = (
    "CREATE TABLE pydapper_conformance (id INTEGER PRIMARY KEY, label TEXT, score INTEGER, note TEXT)"
)


def seed_sqlite_connection(connection: sqlite3.Connection, supports_empty_strings: bool = True) -> None:
    connection.execute(SQLITE_CONFORMANCE_DDL)
    connection.executemany(
        "INSERT INTO pydapper_conformance (id, label, score, note) VALUES (?, ?, ?, ?)",
        seed_rows(supports_empty_strings),
    )
    connection.commit()


class Sqlite3ConformanceHarness(SyncAdapterHarness):
    """Live ``core-sync`` harness for the first-party sqlite3 adapter.

    Each case gets a fresh in-memory database; the ``connect()`` path uses a
    disposable file database under ``workdir``.
    """

    adapter_name = "sqlite3"
    command_class = Sqlite3Commands

    def __init__(self, workdir: Union[str, Path]) -> None:
        self.workdir = Path(workdir)
        self.connect_dsn = f"sqlite:///{(self.workdir / 'conformance_connect.db').resolve()}"  # type: ignore[misc]

    def create_commands(self) -> Commands:
        connection = sqlite3.connect(":memory:")
        seed_sqlite_connection(connection)
        return Sqlite3Commands(connection)

    def teardown_commands(self, commands: Commands) -> None:
        commands.connection.close()


SEED_INSERT = "INSERT INTO {table} (id, label, score, note) VALUES (?id?, ?label?, ?score?, ?note?)"


def seed_records(supports_empty_strings: bool = True) -> List[Dict[str, Any]]:
    return [dict(zip(CONFORMANCE_COLUMNS, row)) for row in seed_rows(supports_empty_strings)]


def seed_through_adapter(commands: Commands, table_name: str, supports_empty_strings: bool = True) -> None:
    """Seed the canonical dataset through the adapter's own execute path."""
    commands.execute(SEED_INSERT.format(table=table_name), params=seed_records(supports_empty_strings))


async def seed_through_adapter_async(
    commands: CommandsAsync, table_name: str, supports_empty_strings: bool = True
) -> None:
    """Async twin of :func:`seed_through_adapter`."""
    await commands.execute_async(SEED_INSERT.format(table=table_name), params=seed_records(supports_empty_strings))


@dataclass(frozen=True)
class FirstPartyConformanceEntry:
    """One installed first-party adapter mode's conformance entry."""

    adapter_name: str
    mode: str
    command_class: Union[Type[Commands], Type[CommandsAsync]]
    test_module: str


def _build_entries(*entries: FirstPartyConformanceEntry) -> Dict[Tuple[str, str], FirstPartyConformanceEntry]:
    built: Dict[Tuple[str, str], FirstPartyConformanceEntry] = {}
    for entry in entries:
        key = (entry.adapter_name, entry.mode)
        if key in built:
            raise ValueError(f"duplicate first-party conformance entry {key!r}")
        built[key] = entry
    return built


#: Single source of truth for first-party conformance adoption, keyed by
#: (adapter entry-point name, mode). The drift test derives the expected contents
#: from the installed ``pydapper.adapters`` entry points, so additions or removals
#: of first-party adapters fail loudly here instead of going silently untested.
FIRST_PARTY_CONFORMANCE_ENTRIES: Dict[Tuple[str, str], FirstPartyConformanceEntry] = _build_entries(
    *(
        FirstPartyConformanceEntry("sqlite3", "sync", Sqlite3Commands, "tests/test_sqlite/test_conformance.py"),
        FirstPartyConformanceEntry("psycopg2", "sync", Psycopg2Commands, "tests/test_postgresql/test_conformance.py"),
        FirstPartyConformanceEntry("psycopg", "sync", Psycopg3Commands, "tests/test_postgresql/test_conformance.py"),
        FirstPartyConformanceEntry(
            "psycopg", "async", Psycopg3CommandsAsync, "tests/test_postgresql/test_conformance.py"
        ),
        FirstPartyConformanceEntry("aiopg", "async", AiopgCommands, "tests/test_postgresql/test_conformance.py"),
        FirstPartyConformanceEntry(
            "mysql", "sync", MySqlConnectorPythonCommands, "tests/test_mysql/test_conformance.py"
        ),
        FirstPartyConformanceEntry("pymssql", "sync", PymssqlCommands, "tests/test_mssql/test_conformance.py"),
        FirstPartyConformanceEntry("oracledb", "sync", OracledbCommands, "tests/test_oracle/test_conformance.py"),
        FirstPartyConformanceEntry(
            "google", "sync", GoogleBigqueryClientCommands, "tests/test_bigquery/test_conformance.py"
        ),
    )
)
