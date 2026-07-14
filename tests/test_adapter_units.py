import importlib
from decimal import Decimal
from types import SimpleNamespace

import pytest

from pydapper.bigquery import google_bigquery_client as bigquery_module
from pydapper.mssql import pymssql as mssql_module
from pydapper.mysql import mysql_connector_python as mysql_module
from pydapper.oracle import oracledb as oracle_module
from pydapper.postgresql import aiopg as aiopg_module
from pydapper.postgresql import psycopg2 as psycopg2_module
from pydapper.postgresql import psycopg3 as psycopg3_module

sqlite_module = importlib.import_module("pydapper.sqlite.sqlite3")

pytestmark = pytest.mark.core


class RecordingDbApi:
    def __init__(self):
        self.connection = object()
        self.calls = []

    def connect(self, **kwargs):
        self.calls.append(kwargs)
        return self.connection


class RecordingAsyncDbApi:
    def __init__(self):
        self.connection = object()
        self.calls = []

    async def connect(self, **kwargs):
        self.calls.append(kwargs)
        return self.connection


def parsed_dsn(**overrides):
    values = {
        "host": "db-host",
        "hostloc": "db-host:1543",
        "port": 1543,
        "user": "user",
        "username": "user",
        "password": "password",
        "database": "app",
        "dbname": "app",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def patch_dbapi_import(monkeypatch, module, expected_name, dbapi):
    calls = []

    def import_dbapi_module(name):
        calls.append(name)
        assert name == expected_name
        return dbapi

    monkeypatch.setattr(module, "import_dbapi_module", import_dbapi_module)
    return calls


def test_bigquery_connect_imports_dbapi_and_wraps_connection(monkeypatch):
    dbapi = RecordingDbApi()
    import_calls = patch_dbapi_import(monkeypatch, bigquery_module, "google.cloud.bigquery.dbapi", dbapi)
    client = object()

    commands = bigquery_module.GoogleBigqueryClientCommands.connect(parsed_dsn(), client=client)

    assert isinstance(commands, bigquery_module.GoogleBigqueryClientCommands)
    assert commands.connection is dbapi.connection
    assert dbapi.calls == [{"client": client}]
    assert import_calls == ["google.cloud.bigquery.dbapi"]


@pytest.mark.parametrize(
    "param, expected_placeholder",
    [
        (SimpleNamespace(value=Decimal("1.0")), "%d"),
        ([SimpleNamespace(value="text")], "%s"),
        (SimpleNamespace(value=object()), "%s"),
    ],
)
def test_pymssql_param_handler_uses_parameter_type_for_placeholder(param, expected_placeholder):
    handler = mssql_module.PymssqlCommands.SqlParamHandler("select ?value?", param)

    assert handler.get_param_placeholder("value") == expected_placeholder


def test_pymssql_param_handler_uses_default_placeholder_for_empty_executemany_params():
    handler = mssql_module.PymssqlCommands.SqlParamHandler("select ?value?", [])

    assert handler.get_param_placeholder("value") == "%s"
    assert handler.prepared_sql == "select %s"


def test_pymssql_connect_imports_dbapi_and_wraps_connection(monkeypatch):
    dbapi = RecordingDbApi()
    import_calls = patch_dbapi_import(monkeypatch, mssql_module, "pymssql", dbapi)

    commands = mssql_module.PymssqlCommands.connect(parsed_dsn(), login_timeout=3)

    assert isinstance(commands, mssql_module.PymssqlCommands)
    assert commands.connection is dbapi.connection
    assert dbapi.calls == [
        {
            "server": "db-host",
            "port": 1543,
            "user": "user",
            "password": "password",
            "database": "app",
            "login_timeout": 3,
        }
    ]
    assert import_calls == ["pymssql"]


def test_mysql_connect_imports_dbapi_and_wraps_connection(monkeypatch):
    dbapi = RecordingDbApi()
    import_calls = patch_dbapi_import(monkeypatch, mysql_module, "mysql.connector", dbapi)

    commands = mysql_module.MySqlConnectorPythonCommands.connect(parsed_dsn(), charset="utf8mb4")

    assert isinstance(commands, mysql_module.MySqlConnectorPythonCommands)
    assert commands.connection is dbapi.connection
    assert dbapi.calls == [
        {
            "host": "db-host",
            "port": 1543,
            "user": "user",
            "password": "password",
            "database": "app",
            "charset": "utf8mb4",
        }
    ]
    assert import_calls == ["mysql.connector"]


def test_oracledb_param_handler_uses_named_placeholder():
    handler = oracle_module.OracledbCommands.SqlParamHandler("select ?value?", {"value": 1})

    assert handler.get_param_placeholder("value") == ":value"


def test_oracledb_connect_imports_dbapi_and_wraps_connection(monkeypatch):
    dbapi = RecordingDbApi()
    import_calls = patch_dbapi_import(monkeypatch, oracle_module, "oracledb", dbapi)

    commands = oracle_module.OracledbCommands.connect(parsed_dsn(), mode="thin")

    assert isinstance(commands, oracle_module.OracledbCommands)
    assert commands.connection is dbapi.connection
    assert dbapi.calls == [
        {
            "user": "user",
            "password": "password",
            "dsn": "db-host:1543/app",
            "mode": "thin",
        }
    ]
    assert import_calls == ["oracledb"]


@pytest.mark.asyncio
async def test_aiopg_param_handler_emulates_executemany():
    class TrackingCursor:
        def __init__(self):
            self.calls = []
            self.rowcount = 0

        async def execute(self, sql, parameters=None):
            self.calls.append((sql, parameters))
            self.rowcount = 1

    cursor = TrackingCursor()
    handler = aiopg_module.AiopgCommands.SqlParamHandler(
        "insert into task (id) values (?id?)",
        [{"id": 1}, {"id": 2}],
    )

    assert await handler.execute_async(cursor) == 2
    assert cursor.calls == [
        ("insert into task (id) values (%s)", (1,)),
        ("insert into task (id) values (%s)", (2,)),
    ]


@pytest.mark.asyncio
async def test_aiopg_param_handler_executes_with_parameter_values():
    class TrackingCursor:
        rowcount = 5

        def __init__(self):
            self.calls = []

        async def execute(self, sql, parameters=None):
            self.calls.append((sql, parameters))

    cursor = TrackingCursor()
    handler = aiopg_module.AiopgCommands.SqlParamHandler("select ?id?", {"id": 1})

    assert await handler.execute_async(cursor) == 5
    assert cursor.calls == [("select %s", (1,))]


@pytest.mark.asyncio
async def test_aiopg_connect_imports_dbapi_and_wraps_connection(monkeypatch):
    dbapi = RecordingAsyncDbApi()
    import_calls = patch_dbapi_import(monkeypatch, aiopg_module, "aiopg", dbapi)

    commands = await aiopg_module.AiopgCommands.connect_async(parsed_dsn(port=None), application_name="pydapper")

    assert isinstance(commands, aiopg_module.AiopgCommands)
    assert commands.connection is dbapi.connection
    assert dbapi.calls == [
        {
            "dbname": "app",
            "user": "user",
            "password": "password",
            "host": "db-host",
            "port": "5432",
            "application_name": "pydapper",
        }
    ]
    assert import_calls == ["aiopg"]


def test_psycopg2_connect_imports_dbapi_and_wraps_connection(monkeypatch):
    dbapi = RecordingDbApi()
    import_calls = patch_dbapi_import(monkeypatch, psycopg2_module, "psycopg2", dbapi)

    commands = psycopg2_module.Psycopg2Commands.connect(parsed_dsn(port=None), application_name="pydapper")

    assert isinstance(commands, psycopg2_module.Psycopg2Commands)
    assert commands.connection is dbapi.connection
    assert dbapi.calls == [
        {
            "dbname": "app",
            "user": "user",
            "password": "password",
            "host": "db-host",
            "port": "5432",
            "application_name": "pydapper",
        }
    ]
    assert import_calls == ["psycopg2"]


def test_psycopg3_connect_imports_dbapi_and_wraps_connection(monkeypatch):
    dbapi = RecordingDbApi()
    import_calls = patch_dbapi_import(monkeypatch, psycopg3_module, "psycopg", dbapi)

    commands = psycopg3_module.Psycopg3Commands.connect(parsed_dsn(port=None), application_name="pydapper")

    assert isinstance(commands, psycopg3_module.Psycopg3Commands)
    assert commands.connection is dbapi.connection
    assert dbapi.calls == [
        {
            "dbname": "app",
            "user": "user",
            "password": "password",
            "host": "db-host",
            "port": "5432",
            "application_name": "pydapper",
        }
    ]
    assert import_calls == ["psycopg"]


@pytest.mark.asyncio
async def test_psycopg3_connect_async_imports_dbapi_and_wraps_connection(monkeypatch):
    connection = object()
    dbapi_calls = []

    async def connect(**kwargs):
        dbapi_calls.append(kwargs)
        return connection

    dbapi = SimpleNamespace(AsyncConnection=SimpleNamespace(connect=connect))
    import_calls = patch_dbapi_import(monkeypatch, psycopg3_module, "psycopg", dbapi)

    commands = await psycopg3_module.Psycopg3CommandsAsync.connect_async(
        parsed_dsn(port=None),
        application_name="pydapper",
    )

    assert isinstance(commands, psycopg3_module.Psycopg3CommandsAsync)
    assert commands.connection is connection
    assert dbapi_calls == [
        {
            "dbname": "app",
            "user": "user",
            "password": "password",
            "host": "db-host",
            "port": "5432",
            "application_name": "pydapper",
        }
    ]
    assert import_calls == ["psycopg"]


@pytest.mark.asyncio
async def test_psycopg3_async_cursor_wraps_sync_cursor_return_value():
    class Connection:
        def __init__(self):
            self.cursor_result = object()
            self.calls = []

        def cursor(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return self.cursor_result

    connection = Connection()
    commands = psycopg3_module.Psycopg3CommandsAsync(connection)

    wrapper = commands.cursor("cursor-name", row_factory=dict)
    assert type(wrapper).__name__ == "_AwaitableAsyncContextManager"
    assert wrapper._preserve_active_error is True
    async with wrapper as cursor:
        assert cursor is connection.cursor_result

    assert connection.calls == [(("cursor-name",), {"row_factory": dict})]


def test_sqlite_param_handler_uses_question_mark_placeholder():
    handler = sqlite_module.Sqlite3Commands.SqlParamHandler("select ?value?", {"value": 1})

    assert handler.get_param_placeholder("value") == "?"


@pytest.mark.parametrize(
    "dsn, expected_path",
    [
        (parsed_dsn(host="/tmp", database="app.db"), "/tmp/app.db"),
        (parsed_dsn(host="/tmp/app.db", database=""), "/tmp/app.db"),
    ],
)
def test_sqlite_connect_wraps_connection(monkeypatch, dsn, expected_path):
    connection = object()
    calls = []

    def connect(db_path, **kwargs):
        calls.append((db_path, kwargs))
        return connection

    monkeypatch.setattr(sqlite_module.sqlite3, "connect", connect)

    commands = sqlite_module.Sqlite3Commands.connect(dsn, isolation_level=None)

    assert isinstance(commands, sqlite_module.Sqlite3Commands)
    assert commands.connection is connection
    assert calls == [(expected_path, {"isolation_level": None})]
