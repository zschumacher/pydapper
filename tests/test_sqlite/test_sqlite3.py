import sqlite3

import pytest

from pydapper import connect
from pydapper import using
from pydapper.sqlite import Sqlite3Commands
from tests.suites.commands import ExecuteScalarTestSuite
from tests.suites.commands import ExecuteTestSuite
from tests.suites.commands import QueryFirstOrDefaultTestSuite
from tests.suites.commands import QueryFirstTestSuite
from tests.suites.commands import QueryMultipleTestSuite
from tests.suites.commands import QuerySingleOrDefaultTestSuite
from tests.suites.commands import QuerySingleTestSuite
from tests.suites.commands import QueryTestSuite


def test_using(database_name):
    with using(sqlite3.connect(f"{database_name}.db")) as commands:
        assert isinstance(commands, Sqlite3Commands)


@pytest.mark.parametrize("driver", ["sqlite", "sqlite+sqlite3"])
def test_connect(driver, database_name):
    with connect(f"{driver}://{database_name}.db") as commands:
        assert isinstance(commands, Sqlite3Commands)


class TestExecute(ExecuteTestSuite):
    ...


class TestQuery(QueryTestSuite):
    ...


class TestQueryMultiple(QueryMultipleTestSuite):
    ...


class TestQueryFirst(QueryFirstTestSuite):
    ...


class TestQueryFirstOrDefault(QueryFirstOrDefaultTestSuite):
    ...


class TestQuerySingle(QuerySingleTestSuite):
    ...


class TestQuerySingleOrDefault(QuerySingleOrDefaultTestSuite):
    ...


class TestExecuteScalar(ExecuteScalarTestSuite):
    ...
