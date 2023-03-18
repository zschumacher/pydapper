import datetime

import cx_Oracle
import pytest

from pydapper import connect
from pydapper import using
from pydapper.oracle import CxOracleCommands
from tests.test_suites.commands import ExecuteScalarTestSuite
from tests.test_suites.commands import ExecuteTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultTestSuite
from tests.test_suites.commands import QueryFirstTestSuite
from tests.test_suites.commands import QueryMultipleTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultTestSuite
from tests.test_suites.commands import QuerySingleTestSuite
from tests.test_suites.commands import QueryTestSuite


@pytest.fixture(scope="function")
def commands(server, database_name) -> CxOracleCommands:
    with CxOracleCommands(
        cx_Oracle.connect(password="pydapper", user="pydapper", dsn=f"{server}:1522/{database_name}")
    ) as commands:
        yield commands


def test_using(server, database_name):
    with using(
        cx_Oracle.connect(password="pydapper", user="pydapper", dsn=f"{server}:1522/{database_name}")
    ) as commands:
        assert isinstance(commands, CxOracleCommands)


@pytest.mark.parametrize("driver", ["oracle", "oracle+cx_Oracle"])
def test_connect(driver, database_name, server):
    with connect(f"{driver}://pydapper:pydapper@{server}:1522/{database_name}") as commands:
        assert isinstance(commands, CxOracleCommands)


class TestExecute(ExecuteTestSuite):
    def test_multiple(self, commands):
        assert (
            commands.execute(
                "INSERT INTO task (id, description, due_date, owner_id) "
                "VALUES (?id?, ?description?, ?due_date?, ?owner_id?)",
                [
                    {"id": 4, "description": "new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                    {
                        "id": 5,
                        "description": "another new task",
                        "due_date": datetime.date(2022, 1, 1),
                        "owner_id": 1,
                    },
                ],
            )
            == 2
        )


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
