from .bigquery import GoogleBigqueryClientCommands
from .main import register_adapter
from .mssql import PymssqlCommands
from .mysql import MySqlConnectorPythonCommands
from .oracle import OracledbCommands
from .postgresql import AiopgCommands
from .postgresql import Psycopg2Commands
from .postgresql import Psycopg3Commands
from .postgresql import Psycopg3CommandsAsync
from .sqlite import Sqlite3Commands


def _connection_module_matches(connection: object, *module_prefixes: str) -> bool:
    for connection_class in type(connection).__mro__:
        module = getattr(connection_class, "__module__", "")
        if not isinstance(module, str):
            continue
        if any(module == prefix or module.startswith(f"{prefix}.") for prefix in module_prefixes):
            return True
    return False


def _register_builtin_adapters() -> None:
    register_adapter(
        "sqlite3",
        commands=Sqlite3Commands,
        using_connection_predicate=lambda connection: _connection_module_matches(connection, "sqlite3"),
    )
    register_adapter(
        "psycopg2",
        commands=Psycopg2Commands,
        using_connection_predicate=lambda connection: _connection_module_matches(connection, "psycopg2"),
    )
    register_adapter(
        "psycopg",
        commands=Psycopg3Commands,
        async_commands=Psycopg3CommandsAsync,
        using_connection_predicate=lambda connection: _connection_module_matches(connection, "psycopg"),
    )
    register_adapter(
        "aiopg",
        async_commands=AiopgCommands,
        using_connection_predicate=lambda connection: _connection_module_matches(connection, "aiopg"),
    )
    register_adapter(
        "mysql",
        commands=MySqlConnectorPythonCommands,
        using_connection_predicate=lambda connection: _connection_module_matches(connection, "mysql.connector"),
    )
    register_adapter(
        "pymssql",
        commands=PymssqlCommands,
        using_connection_predicate=lambda connection: _connection_module_matches(connection, "pymssql"),
    )
    register_adapter(
        "oracledb",
        commands=OracledbCommands,
        using_connection_predicate=lambda connection: _connection_module_matches(connection, "oracledb"),
    )
    register_adapter(
        "google",
        commands=GoogleBigqueryClientCommands,
        using_connection_predicate=lambda connection: _connection_module_matches(
            connection, "google.cloud.bigquery.dbapi"
        ),
    )


_register_builtin_adapters()
