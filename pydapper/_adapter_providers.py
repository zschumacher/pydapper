"""Private per-adapter registration callbacks for the first-party adapters.

Each stable first-party adapter name owns exactly one zero-argument callback
that registers exactly that name through the public ``register_adapter()`` and
returns ``None``. The ``pydapper`` distribution declares one installed
``pydapper.adapters`` entry point per callback, so these satisfy the same
provider-callback contract as a third-party adapter: synchronous,
zero-argument, ``-> None``, one registration each, and no connection, network,
credential, or discovery work. The private loader in ``main`` resolves and
invokes them lazily; nothing imports this module at package import.

Command-class imports live *inside* the callbacks on purpose. Importing this
module must not drag in every backend command module, because only the
requested adapter's provider should import anything. Registering an adapter
still imports no optional database driver: the command classes defer that to
connection creation via ``import_dbapi_module()``.

Nothing here registers at import time -- the entry-point loader invokes these
callbacks explicitly -- and nothing here is exported from the package root.
"""

from __future__ import annotations

from .main import register_adapter


def _connection_module_matches(connection: object, *module_prefixes: str) -> bool:
    """Report whether a connection's type comes from one of the driver modules.

    Walks ``type(connection).__mro__`` so a subclass of a driver connection is
    claimed by the adapter that owns its base class, and matches a module only
    when it equals a prefix or is a child module of it (``psycopg2`` matches
    ``psycopg2`` and ``psycopg2.extensions`` but never ``psycopg2evil``).

    Deliberately structural and cheap: it imports no driver module to answer,
    and reads no ``repr()``, credential, DSN, attribute, or live network state
    from the connection. A class with a non-string ``__module__`` is skipped
    rather than raising.
    """
    for connection_class in type(connection).__mro__:
        module = getattr(connection_class, "__module__", "")
        if not isinstance(module, str):
            continue
        if any(module == prefix or module.startswith(f"{prefix}.") for prefix in module_prefixes):
            return True
    return False


def _register_sqlite3_provider() -> None:
    from .sqlite import Sqlite3Commands

    register_adapter(
        "sqlite3",
        commands=Sqlite3Commands,
        using_connection_predicate=lambda connection: _connection_module_matches(connection, "sqlite3"),
    )


def _register_psycopg2_provider() -> None:
    from .postgresql import Psycopg2Commands

    register_adapter(
        "psycopg2",
        commands=Psycopg2Commands,
        using_connection_predicate=lambda connection: _connection_module_matches(connection, "psycopg2"),
    )


def _register_psycopg_provider() -> None:
    # one adapter name owns both modes: psycopg3 sync and async register together through this
    # single callback, never as two registrations
    from .postgresql import Psycopg3Commands
    from .postgresql import Psycopg3CommandsAsync

    register_adapter(
        "psycopg",
        commands=Psycopg3Commands,
        async_commands=Psycopg3CommandsAsync,
        using_connection_predicate=lambda connection: _connection_module_matches(connection, "psycopg"),
    )


def _register_aiopg_provider() -> None:
    from .postgresql import AiopgCommands

    register_adapter(
        "aiopg",
        async_commands=AiopgCommands,
        using_connection_predicate=lambda connection: _connection_module_matches(connection, "aiopg"),
    )


def _register_mysql_provider() -> None:
    from .mysql import MySqlConnectorPythonCommands

    register_adapter(
        "mysql",
        commands=MySqlConnectorPythonCommands,
        using_connection_predicate=lambda connection: _connection_module_matches(connection, "mysql.connector"),
    )


def _register_pymssql_provider() -> None:
    from .mssql import PymssqlCommands

    register_adapter(
        "pymssql",
        commands=PymssqlCommands,
        using_connection_predicate=lambda connection: _connection_module_matches(connection, "pymssql"),
    )


def _register_oracledb_provider() -> None:
    from .oracle import OracledbCommands

    register_adapter(
        "oracledb",
        commands=OracledbCommands,
        using_connection_predicate=lambda connection: _connection_module_matches(connection, "oracledb"),
    )


def _register_google_provider() -> None:
    from .bigquery import GoogleBigqueryClientCommands

    register_adapter(
        "google",
        commands=GoogleBigqueryClientCommands,
        using_connection_predicate=lambda connection: _connection_module_matches(
            connection, "google.cloud.bigquery.dbapi"
        ),
    )
