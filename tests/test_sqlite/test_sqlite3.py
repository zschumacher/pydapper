import os
import sqlite3

import pytest

from pydapper import connect
from pydapper import using
from pydapper.sqlite import Sqlite3Commands
from tests.test_suites.commands import ExecuteScalarTestSuite
from tests.test_suites.commands import ExecuteTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultTestSuite
from tests.test_suites.commands import QueryFirstTestSuite
from tests.test_suites.commands import QueryMultipleTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultTestSuite
from tests.test_suites.commands import QuerySingleTestSuite
from tests.test_suites.commands import QueryTestSuite

pytestmark = pytest.mark.sqlite


def test_using_subfolder(database_name, setup_sql_dir):
    with using(sqlite3.connect(f"{setup_sql_dir}{os.path.sep}{database_name}.db")) as commands:
        assert isinstance(commands, Sqlite3Commands)


def test_using(database_name):
    with using(sqlite3.connect(f"{database_name}.db")) as commands:
        assert isinstance(commands, Sqlite3Commands)


@pytest.mark.parametrize("driver", ["sqlite", "sqlite+sqlite3"])
def test_connect_subfolder(driver, database_name, setup_sql_dir):
    with connect(f"{driver}://{setup_sql_dir}{os.path.sep}{database_name}.db") as commands:
        assert isinstance(commands, Sqlite3Commands)


@pytest.mark.parametrize("driver", ["sqlite", "sqlite+sqlite3"])
def test_connect(driver, database_name):
    with connect(f"{driver}://{database_name}.db") as commands:
        assert isinstance(commands, Sqlite3Commands)


class TestExecute(ExecuteTestSuite): ...


class TestQuery(QueryTestSuite): ...


class TestQueryMultiple(QueryMultipleTestSuite): ...


class TestQueryFirst(QueryFirstTestSuite): ...


class TestQueryFirstOrDefault(QueryFirstOrDefaultTestSuite): ...


class TestQuerySingle(QuerySingleTestSuite): ...


class TestQuerySingleOrDefault(QuerySingleOrDefaultTestSuite): ...


class TestExecuteScalar(ExecuteScalarTestSuite): ...
