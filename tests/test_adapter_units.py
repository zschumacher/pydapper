import importlib
from decimal import Decimal
from types import SimpleNamespace

import pytest

from pydapper.bigquery import google_bigquery_client as bigquery_module
from pydapper.dsn_parser import PydapperParseResult
from pydapper.exceptions import DuplicateColumnException
from pydapper.exceptions import NoResultException
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

    commands = bigquery_module.GoogleBigqueryClientCommands.connect(PydapperParseResult("bigquery:////"), client=client)

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


@pytest.mark.parametrize(
    ("module", "commands_class", "dbapi_name", "dsn"),
    [
        (mssql_module, mssql_module.PymssqlCommands, "pymssql", "mssql://host/database"),
        (mysql_module, mysql_module.MySqlConnectorPythonCommands, "mysql.connector", "mysql://host/database"),
    ],
)
def test_network_adapters_preserve_driver_default_behavior_for_an_absent_port(
    monkeypatch, module, commands_class, dbapi_name, dsn
):
    dbapi = RecordingDbApi()
    patch_dbapi_import(monkeypatch, module, dbapi_name, dbapi)

    commands_class.connect(PydapperParseResult(dsn))

    assert dbapi.calls[0]["port"] is None


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


class MySqlLifecycleCursor:
    def __init__(
        self,
        rows=(),
        description=(("id",), ("name",)),
        execute_exc=None,
        fetchone_exc=None,
        fetchall_exc=None,
        exit_exc=None,
        exit_result=False,
    ):
        self.rows = list(rows)
        self._description = list(description)
        self.execute_exc = execute_exc
        self.fetchone_exc = fetchone_exc
        self.fetchall_exc = fetchall_exc
        self.exit_exc = exit_exc
        self.exit_result = exit_result
        self.rowcount = -1
        self.calls = []
        self.exit_args = []
        self.exit_tb_matches = []

    @property
    def description(self):
        self.calls.append("description")
        return self._description

    def __enter__(self):
        self.calls.append("enter")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.calls.append("exit")
        self.exit_args.append((exc_type, exc_val, exc_tb))
        self.exit_tb_matches.append(exc_val is not None and exc_tb is exc_val.__traceback__)
        if self.exit_exc is not None:
            raise self.exit_exc
        return self.exit_result

    def execute(self, sql, parameters=None):
        self.calls.append("execute")
        if self.execute_exc is not None:
            raise self.execute_exc

    def fetchone(self):
        self.calls.append("fetchone")
        if self.fetchone_exc is not None:
            raise self.fetchone_exc
        if not self.rows:
            return None
        return self.rows.pop(0)

    def fetchall(self):
        self.calls.append("fetchall")
        if self.fetchall_exc is not None:
            raise self.fetchall_exc
        remaining, self.rows = self.rows, []
        return remaining


def mysql_commands_with_cursor(cursor):
    def acquire_cursor(*args, **kwargs):
        cursor.calls.append("cursor")
        return cursor

    connection = SimpleNamespace(cursor=acquire_cursor)
    return mysql_module.MySqlConnectorPythonCommands(connection)


def test_mysql_query_first_drains_unread_results_before_projection():
    cursor = MySqlLifecycleCursor(rows=[(1, "zach"), (2, "sam")])
    commands = mysql_commands_with_cursor(cursor)

    projection_calls = []

    def mapper(raw_row):
        projection_calls.append(list(cursor.calls))
        return dict(zip(raw_row.columns, raw_row.values))

    result = commands.query_first("select id, name from task", mapper=mapper)

    assert result == {"id": 1, "name": "zach"}
    assert cursor.calls == ["cursor", "enter", "execute", "description", "fetchone", "fetchall", "exit"]
    assert projection_calls == [["cursor", "enter", "execute", "description", "fetchone", "fetchall"]]
    assert cursor.exit_args == [(None, None, None)]


def test_mysql_query_first_mapper_error_wins_over_cleanup_failure():
    mapper_error = RuntimeError("mapper failed")
    cursor = MySqlLifecycleCursor(rows=[(1, "zach")], exit_exc=OSError("cleanup failed"))
    commands = mysql_commands_with_cursor(cursor)

    def mapper(raw_row):
        raise mapper_error

    with pytest.raises(RuntimeError) as exc_info:
        commands.query_first("select id, name from task", mapper=mapper)

    assert exc_info.value is mapper_error
    assert cursor.calls == ["cursor", "enter", "execute", "description", "fetchone", "fetchall", "exit"]
    exc_type, exc_val, exc_tb = cursor.exit_args[0]
    assert exc_type is RuntimeError
    assert exc_val is mapper_error
    assert cursor.exit_tb_matches == [True]


def test_mysql_query_first_execute_error_wins_over_cleanup_failure():
    execute_error = RuntimeError("execute failed")
    cursor = MySqlLifecycleCursor(execute_exc=execute_error, exit_exc=OSError("cleanup failed"))
    commands = mysql_commands_with_cursor(cursor)

    with pytest.raises(RuntimeError) as exc_info:
        commands.query_first("select id, name from task")

    assert exc_info.value is execute_error
    assert cursor.calls == ["cursor", "enter", "execute", "exit"]
    exc_type, exc_val, exc_tb = cursor.exit_args[0]
    assert exc_type is RuntimeError
    assert exc_val is execute_error
    assert cursor.exit_tb_matches == [True]


def test_mysql_query_first_fetch_error_wins_over_cleanup_failure():
    fetch_error = RuntimeError("fetchone failed")
    cursor = MySqlLifecycleCursor(fetchone_exc=fetch_error, exit_exc=OSError("cleanup failed"))
    commands = mysql_commands_with_cursor(cursor)

    with pytest.raises(RuntimeError) as exc_info:
        commands.query_first("select id, name from task")

    assert exc_info.value is fetch_error
    assert cursor.calls == ["cursor", "enter", "execute", "description", "fetchone", "exit"]
    exc_type, exc_val, _ = cursor.exit_args[0]
    assert exc_type is RuntimeError
    assert exc_val is fetch_error


def test_mysql_query_first_drain_error_wins_over_cleanup_failure():
    drain_error = RuntimeError("fetchall failed")
    cursor = MySqlLifecycleCursor(
        rows=[(1, "zach"), (2, "sam")],
        fetchall_exc=drain_error,
        exit_exc=OSError("cleanup failed"),
    )
    commands = mysql_commands_with_cursor(cursor)

    projection_calls = []

    def mapper(raw_row):
        projection_calls.append(raw_row)
        return raw_row

    with pytest.raises(RuntimeError) as exc_info:
        commands.query_first("select id, name from task", mapper=mapper)

    assert exc_info.value is drain_error
    assert projection_calls == []
    assert cursor.calls == ["cursor", "enter", "execute", "description", "fetchone", "fetchall", "exit"]
    exc_type, exc_val, exc_tb = cursor.exit_args[0]
    assert exc_type is RuntimeError
    assert exc_val is drain_error
    assert cursor.exit_tb_matches == [True]


def test_mysql_query_first_truthy_cursor_exit_does_not_suppress_command_error():
    execute_error = RuntimeError("execute failed")
    cursor = MySqlLifecycleCursor(execute_exc=execute_error, exit_result=True)
    commands = mysql_commands_with_cursor(cursor)

    with pytest.raises(RuntimeError) as exc_info:
        commands.query_first("select id, name from task")

    assert exc_info.value is execute_error
    assert cursor.calls == ["cursor", "enter", "execute", "exit"]


def test_mysql_query_first_no_result_wins_over_cleanup_failure():
    cursor = MySqlLifecycleCursor(rows=[], exit_exc=OSError("cleanup failed"))
    commands = mysql_commands_with_cursor(cursor)

    with pytest.raises(NoResultException) as exc_info:
        commands.query_first("select id, name from task")

    assert cursor.calls == ["cursor", "enter", "execute", "description", "fetchone", "exit"]
    exc_type, exc_val, _ = cursor.exit_args[0]
    assert exc_type is NoResultException
    assert exc_val is exc_info.value


def test_mysql_query_first_duplicate_column_error_wins_over_cleanup_failure():
    cursor = MySqlLifecycleCursor(
        rows=[(1, 2)],
        description=[("id",), ("id",)],
        exit_exc=OSError("cleanup failed"),
    )
    commands = mysql_commands_with_cursor(cursor)

    model_calls = []

    def model(**kwargs):
        model_calls.append(kwargs)
        return kwargs

    with pytest.raises(DuplicateColumnException) as exc_info:
        commands.query_first("select id, id from task", model=model)

    assert model_calls == []
    assert cursor.calls == ["cursor", "enter", "execute", "description", "fetchone", "fetchall", "exit"]
    exc_type, exc_val, _ = cursor.exit_args[0]
    assert exc_type is DuplicateColumnException
    assert exc_val is exc_info.value
    assert cursor.exit_tb_matches == [True]


def test_mysql_query_first_mapper_receives_duplicate_columns_after_drain():
    cursor = MySqlLifecycleCursor(rows=[(1, 2), (3, 4)], description=[("id",), ("id",)])
    commands = mysql_commands_with_cursor(cursor)

    result = commands.query_first("select id, id from task", mapper=lambda raw_row: raw_row.values)

    assert result == (1, 2)
    assert cursor.calls == ["cursor", "enter", "execute", "description", "fetchone", "fetchall", "exit"]


def test_mysql_query_first_cleanup_failure_propagates_after_successful_body():
    cleanup_error = OSError("cleanup failed")
    cursor = MySqlLifecycleCursor(rows=[(1, "zach")], exit_exc=cleanup_error)
    commands = mysql_commands_with_cursor(cursor)

    projection_calls = []

    def mapper(raw_row):
        projection_calls.append(raw_row.values)
        return raw_row.values

    with pytest.raises(OSError) as exc_info:
        commands.query_first("select id, name from task", mapper=mapper)

    assert exc_info.value is cleanup_error
    assert projection_calls == [(1, "zach")]
    assert cursor.calls == ["cursor", "enter", "execute", "description", "fetchone", "fetchall", "exit"]
    assert cursor.exit_args == [(None, None, None)]


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


def test_oracledb_connect_forwards_ipv6_hostloc_and_decoded_parser_fields(monkeypatch):
    dbapi = RecordingDbApi()
    patch_dbapi_import(monkeypatch, oracle_module, "oracledb", dbapi)
    dsn = PydapperParseResult("oracle+oracledb://ora%40user:p%3Ass%2Fword@[2001:db8::1]:1521/service%20name")

    oracle_module.OracledbCommands.connect(dsn)

    assert dbapi.calls == [
        {
            "user": "ora@user",
            "password": "p:ss/word",
            "dsn": "[2001:db8::1]:1521/service name",
        }
    ]


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


@pytest.mark.asyncio
async def test_aiopg_connect_forwards_decoded_parser_fields_and_integer_port(monkeypatch):
    dbapi = RecordingAsyncDbApi()
    patch_dbapi_import(monkeypatch, aiopg_module, "aiopg", dbapi)
    dsn = PydapperParseResult("postgresql+aiopg://async%40user:p%3Ass%2Fword@async-db.example:6544/async%20database")

    await aiopg_module.AiopgCommands.connect_async(dsn)

    assert dbapi.calls == [
        {
            "dbname": "async database",
            "user": "async@user",
            "password": "p:ss/word",
            "host": "async-db.example",
            "port": 6544,
        }
    ]


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


def test_psycopg2_connect_forwards_decoded_parser_fields_and_integer_port(monkeypatch):
    dbapi = RecordingDbApi()
    patch_dbapi_import(monkeypatch, psycopg2_module, "psycopg2", dbapi)
    dsn = PydapperParseResult("postgresql+psycopg2://sync%40user:p%3Ass%2Fword@sync-db.example:6543/sync%20database")

    psycopg2_module.Psycopg2Commands.connect(dsn)

    assert dbapi.calls == [
        {
            "dbname": "sync database",
            "user": "sync@user",
            "password": "p:ss/word",
            "host": "sync-db.example",
            "port": 6543,
        }
    ]


def test_psycopg2_connect_preserves_a_supplied_zero_port(monkeypatch):
    dbapi = RecordingDbApi()
    patch_dbapi_import(monkeypatch, psycopg2_module, "psycopg2", dbapi)

    psycopg2_module.Psycopg2Commands.connect(PydapperParseResult("postgresql://host:0/database"))

    assert dbapi.calls[0]["port"] == 0


def test_psycopg2_connect_preserves_its_default_for_a_real_parser_without_a_port(monkeypatch):
    dbapi = RecordingDbApi()
    patch_dbapi_import(monkeypatch, psycopg2_module, "psycopg2", dbapi)

    psycopg2_module.Psycopg2Commands.connect(PydapperParseResult("postgresql://host/database"))

    assert dbapi.calls[0]["port"] == "5432"


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
        ("sqlite://relative.db", "relative.db"),
        ("sqlite+sqlite3://relative.db", "relative.db"),
        ("sqlite:///relative/path.db", "relative/path.db"),
        ("sqlite:////absolute/path.db", "/absolute/path.db"),
        ("sqlite:///:memory:", ":memory:"),
        ("sqlite://", ""),
        ("sqlite:///relative/my%20database.db", "relative/my database.db"),
    ],
)
def test_sqlite_connect_wraps_connection(monkeypatch, dsn, expected_path):
    connection = object()
    calls = []

    def connect(db_path, **kwargs):
        calls.append((db_path, kwargs))
        return connection

    monkeypatch.setattr(sqlite_module.sqlite3, "connect", connect)

    commands = sqlite_module.Sqlite3Commands.connect(PydapperParseResult(dsn), isolation_level=None)

    assert isinstance(commands, sqlite_module.Sqlite3Commands)
    assert commands.connection is connection
    assert calls == [(expected_path, {"isolation_level": None})]
