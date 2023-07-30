import datetime
from decimal import Decimal

import pytest

from pydapper import connect
from pydapper import using
from pydapper.mssql.pymssql import PymssqlCommands
from tests.test_suites.commands import ExecuteScalarTestSuite
from tests.test_suites.commands import ExecuteTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultTestSuite
from tests.test_suites.commands import QueryFirstTestSuite
from tests.test_suites.commands import QueryMultipleTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultTestSuite
from tests.test_suites.commands import QuerySingleTestSuite
from tests.test_suites.commands import QueryTestSuite

pytestmark = pytest.mark.mssql


@pytest.fixture(scope="function")
def commands(server, database_name) -> PymssqlCommands:
    from pymssql import _pymssql

    with PymssqlCommands(
        _pymssql.connect(server=server, port=1434, password="pydapper!PYDAPPER", user="sa", database=database_name)
    ) as commands:
        yield commands


def test_using(server, database_name):
    from pymssql import _pymssql

    with using(
        _pymssql.connect(server=server, port=1434, password="pydapper!PYDAPPER", user="sa", database=database_name)
    ) as commands:
        assert isinstance(commands, PymssqlCommands)


@pytest.mark.parametrize("driver", ["mssql", "mysql+pymssql"])
def test_connect(driver, database_name, server):
    with connect(f"{driver}://sa:pydapper!PYDAPPER@{server}:1434/{database_name}") as commands:
        assert isinstance(commands, PymssqlCommands)


class TestParamHandler:
    @pytest.mark.parametrize(
        "param, expected",
        [
            ({"test": 1}, "%d"),
            ({"test": Decimal("5.6750000")}, "%d"),
            ({"test": datetime.date.today()}, "%s"),
            ([{"test": datetime.date.today()}, {"test": datetime.datetime.today()}], "%s"),
        ],
    )
    def test_get_param_value(self, param, expected):
        handler = PymssqlCommands.SqlParamHandler("", param)
        assert handler.get_param_placeholder("test") == expected


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
