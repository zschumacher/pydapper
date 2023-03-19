import mysql.connector
import pytest

from pydapper import connect
from pydapper import using
from pydapper.mysql import MySqlConnectorPythonCommands
from tests.test_suites.commands import ExecuteScalarTestSuite
from tests.test_suites.commands import ExecuteTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultTestSuite
from tests.test_suites.commands import QueryFirstTestSuite
from tests.test_suites.commands import QueryMultipleTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultTestSuite
from tests.test_suites.commands import QuerySingleTestSuite
from tests.test_suites.commands import QueryTestSuite


@pytest.fixture(scope="function")
def commands(server, database_name) -> MySqlConnectorPythonCommands:
    with MySqlConnectorPythonCommands(
        mysql.connector.connect(host=server, port=3307, user="pydapper", password="pydapper", database=database_name)
    ) as commands:
        yield commands


def test_using(server, database_name):
    with using(
        mysql.connector.connect(host=server, port=3307, user="pydapper", password="pydapper", database=database_name)
    ) as commands:
        assert isinstance(commands, MySqlConnectorPythonCommands)


@pytest.mark.parametrize("driver", ["mysql", "mysql+mysql"])
def test_connect(driver, database_name, server):
    with connect(f"{driver}://pydapper:pydapper@{server}:3307/{database_name}") as commands:
        assert isinstance(commands, MySqlConnectorPythonCommands)


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
