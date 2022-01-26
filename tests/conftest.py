import os
import sqlite3
from contextlib import suppress
from pathlib import Path

import psycopg2
import pytest
from psycopg2.errors import DuplicateDatabase
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from pymssql import _pymssql

from pydapper import connect
from pydapper.mssql import PymssqlCommands
from pydapper.postgresql import Psycopg2Commands
from pydapper.sqlite import Sqlite3Commands


@pytest.fixture(scope="session")
def setup_sql_dir():
    return Path(__file__).parent / "databases"


@pytest.fixture(scope="session")
def database_name(worker_id):
    return f"pydapper_{worker_id}"


@pytest.fixture(scope="session")
def server():
    return "localhost"


@pytest.fixture(scope="session", autouse=True)
def sqlite_setup(database_name, setup_sql_dir):
    db_name = f"{database_name}.db"
    # connect to the newly created database and create the tables
    sql = (setup_sql_dir / "sqlite.sql").read_text()
    with sqlite3.connect(db_name) as conn:
        conn.executescript(sql)
    yield
    os.remove(db_name)


@pytest.fixture(scope="function")
def sqlite3_commands(database_name) -> Sqlite3Commands:
    with Sqlite3Commands(sqlite3.connect(f"{database_name}.db")) as commands:
        yield commands
        commands.connection.rollback()


@pytest.fixture(scope="session", autouse=True)
def postgres_setup(setup_sql_dir, database_name, server):
    # connect to the root and create the db
    conn = psycopg2.connect(f"postgresql://pydapper:pydapper@{server}:5433/postgres")
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    with suppress(DuplicateDatabase):
        cursor.execute(f"CREATE DATABASE {database_name}")

    # connect to the newly created database and create the tables
    setup_sql = (setup_sql_dir / "postgresql.sql").read_text()
    with psycopg2.connect(f"postgresql://pydapper:pydapper@{server}:5433/{database_name}") as conn:
        with conn.cursor() as cursor:
            cursor.execute(setup_sql)


@pytest.fixture(scope="function")
def psycopg2_commands(server, database_name) -> Psycopg2Commands:
    with Psycopg2Commands(
        psycopg2.connect(f"postgresql://pydapper:pydapper@{server}:5433/{database_name}")
    ) as commands:
        yield commands
        commands.connection.rollback()


@pytest.fixture(scope="session", autouse=True)
def mssql_setup(database_name, setup_sql_dir, server):
    with _pymssql.connect(server=server, port=1434, password="pydapper!PYDAPPER", user="sa", database="master") as conn:
        conn.autocommit(True)
        with conn.cursor() as cursor:
            with suppress(_pymssql.OperationalError):
                cursor.execute(f"CREATE DATABASE {database_name}")

    with _pymssql.connect(
        server=server, port=1434, password="pydapper!PYDAPPER", user="sa", database=database_name
    ) as conn:
        with conn.cursor() as cursor:
            setup_sql = (setup_sql_dir / "mssql.sql").read_text()
            cursor.execute(setup_sql)
            conn.commit()


@pytest.fixture(scope="function")
def pymssql_commands(server, database_name) -> Psycopg2Commands:
    with PymssqlCommands(
        _pymssql.connect(server=server, port=1434, password="pydapper!PYDAPPER", user="sa", database=database_name)
    ) as commands:
        yield commands
