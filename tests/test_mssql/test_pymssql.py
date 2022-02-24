import datetime
from decimal import Decimal

import pytest
from pymssql import _pymssql

from pydapper import connect
from pydapper import using
from pydapper.mssql.pymssql import PymssqlCommands
from tests.suites.commands import ExecuteScalarTestSuite
from tests.suites.commands import ExecuteTestSuite
from tests.suites.commands import QueryFirstOrDefaultTestSuite
from tests.suites.commands import QueryFirstTestSuite
from tests.suites.commands import QueryMultipleTestSuite
from tests.suites.commands import QuerySingleOrDefaultTestSuite
from tests.suites.commands import QuerySingleTestSuite
from tests.suites.commands import QueryTestSuite


@pytest.fixture(scope="function")
def commands(server, database_name) -> PymssqlCommands:
    with PymssqlCommands(
        _pymssql.connect(server=server, port=1434, password="pydapper!PYDAPPER", user="sa", database=database_name)
    ) as commands:
        yield commands


def test_using(server, database_name):
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
