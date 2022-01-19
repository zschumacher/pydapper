import os
import sqlite3

import pytest

from pydapper import connect
from pydapper.sqlite.sqlite3 import Sqlite3Commands


@pytest.fixture(scope="session")
def application_dsn(database_name):
    return f"sqlite+sqlite3://{database_name}.db"


@pytest.fixture(scope="session", autouse=True)
def create_test_database(database_name, setup_sql_dir):
    db_name = f"{database_name}.db"
    # connect to the newly created database and create the tables
    sql = (setup_sql_dir / "sqlite.sql").read_text()
    with sqlite3.connect(db_name) as conn:
        conn.executescript(sql)
    yield
    os.remove(db_name)


@pytest.fixture(scope="function")
def sqlite3_connection(application_dsn) -> Sqlite3Commands:
    with connect(application_dsn) as pydapper_connection:
        yield pydapper_connection
        pydapper_connection.connection.rollback()
