import sqlite3

from pydapper import connect
from pydapper import using
from pydapper.sqlite import Sqlite3Commands


def test_using(database_name):
    with using(sqlite3.connect(f"{database_name}.db")) as commands:
        assert isinstance(commands, Sqlite3Commands)


def test_connect(database_name):
    with connect(f"sqlite+sqlite3://{database_name}.db") as commands:
        assert isinstance(commands, Sqlite3Commands)
