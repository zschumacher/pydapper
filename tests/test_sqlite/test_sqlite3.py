import sqlite3

from pydapper import connect
from pydapper import using
from pydapper.sqlite import Sqlite3Commands
import pytest


def test_using(database_name):
    with using(sqlite3.connect(f"{database_name}.db")) as commands:
        assert isinstance(commands, Sqlite3Commands)


@pytest.mark.parametrize("driver", ["sqlite", "sqlite+sqlite3"])
def test_connect(driver, database_name):
    with connect(f"{driver}://{database_name}.db") as commands:
        assert isinstance(commands, Sqlite3Commands)
