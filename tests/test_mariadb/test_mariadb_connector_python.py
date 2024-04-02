import pytest

from pydapper import connect
from pydapper import using
from pydapper.mariadb import MariaDbConnectorPythonCommands
from tests.test_suites.commands import ExecuteScalarTestSuite
from tests.test_suites.commands import ExecuteTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultTestSuite
from tests.test_suites.commands import QueryFirstTestSuite
from tests.test_suites.commands import QueryMultipleTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultTestSuite
from tests.test_suites.commands import QuerySingleTestSuite
from tests.test_suites.commands import QueryTestSuite

pytestmark = pytest.mark.mysql


@pytest.fixture(scope="function")
def commands(server, database_name) -> MariaDbConnectorPythonCommands:
    import mariadb

    with MariaDbConnectorPythonCommands(
        mariadb.connector.connect(host=server, port=3307, user="pydapper", password="pydapper", database=database_name)
    ) as commands:
        yield commands


def test_using(server, database_name):
    import mariadb

    with using(
        mariadb.connector.connect(host=server, port=3307, user="pydapper", password="pydapper", database=database_name)
    ) as commands:
        assert isinstance(commands, MariaDbConnectorPythonCommands)


@pytest.mark.parametrize("driver", ["mariadb", "mariadb+mariadb"])
def test_connect(driver, database_name, server):
    with connect(f"{driver}://pydapper:pydapper@{server}:3307/{database_name}") as commands:
        assert isinstance(commands, MariaDbConnectorPythonCommands)


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
