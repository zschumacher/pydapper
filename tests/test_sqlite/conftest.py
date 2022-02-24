import os
import sqlite3

import pytest

from pydapper.sqlite import Sqlite3Commands


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
def commands(database_name) -> Sqlite3Commands:
    with Sqlite3Commands(sqlite3.connect(f"{database_name}.db")) as commands:
        yield commands
        commands.connection.rollback()
