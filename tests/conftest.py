import os
import sqlite3
from contextlib import suppress
from pathlib import Path

import mysql.connector
import psycopg2
import pytest
from psycopg2.errors import DuplicateDatabase
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from pymssql import _pymssql

from pydapper.mssql import PymssqlCommands
from pydapper.mysql import MySqlConnectorPythonCommands
from pydapper.postgresql import Psycopg2Commands
from pydapper.sqlite import Sqlite3Commands


@pytest.fixture(scope="session")
def setup_sql_dir():
    return Path(__file__).parent / "databases"


@pytest.fixture(scope="session")
def database_name():
    return f"pydapper"


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
def pymssql_commands(server, database_name) -> PymssqlCommands:
    with PymssqlCommands(
        _pymssql.connect(server=server, port=1434, password="pydapper!PYDAPPER", user="sa", database=database_name)
    ) as commands:
        yield commands


@pytest.fixture(scope="session", autouse=True)
def mysql_setup(database_name, setup_sql_dir, server):
    conn = mysql.connector.connect(host=server, port=3307, user="root")
    cursor = conn.cursor(buffered=True)
    setup_sql = (setup_sql_dir / "mysql.sql").read_text()
    cursor.execute(setup_sql, multi=True)
    conn.close()


@pytest.fixture(scope="function")
def mysql_connector_python_commands(server, database_name) -> MySqlConnectorPythonCommands:
    with MySqlConnectorPythonCommands(
        mysql.connector.connect(host=server, port=3307, user="root", database=database_name)
    ) as commands:
        yield commands
