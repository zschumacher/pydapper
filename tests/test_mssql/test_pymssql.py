import datetime
from decimal import Decimal

import pytest
from pymssql import _pymssql

from pydapper import connect
from pydapper import using
from pydapper.mssql.pymssql import PymssqlCommands


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
