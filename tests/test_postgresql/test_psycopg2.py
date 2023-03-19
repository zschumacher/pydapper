import datetime

import psycopg2
import pytest

from pydapper import connect
from pydapper import using
from pydapper.postgresql.psycopg2 import Psycopg2Commands
from tests.test_suites.commands import ExecuteScalarTestSuite
from tests.test_suites.commands import ExecuteTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultTestSuite
from tests.test_suites.commands import QueryFirstTestSuite
from tests.test_suites.commands import QueryMultipleTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultTestSuite
from tests.test_suites.commands import QuerySingleTestSuite
from tests.test_suites.commands import QueryTestSuite


@pytest.fixture(scope="function")
def commands(server, database_name) -> Psycopg2Commands:
    with Psycopg2Commands(
        psycopg2.connect(f"postgresql://pydapper:pydapper@{server}:5433/{database_name}")
    ) as commands:
        yield commands
        commands.connection.rollback()


def test_using(server, database_name):
    with using(psycopg2.connect(f"postgresql://pydapper:pydapper@{server}:5433/{database_name}")) as commands:
        assert isinstance(commands, Psycopg2Commands)


@pytest.mark.parametrize("driver", ["postgresql", "postgresql+psycopg2"])
def test_connect(driver, server, database_name):
    with connect(f"{driver}://pydapper:pydapper@{server}:5433/{database_name}") as commands:
        assert isinstance(commands, Psycopg2Commands)


class TestExecute(ExecuteTestSuite):
    def test_multiple(self, commands):
        assert (
            commands.execute(
                "INSERT INTO task (id, description, due_date, owner_id) "
                "VALUES (?id?, ?description?, ?due_date?, ?owner_id?)",
                [
                    {"id": 4, "description": "new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                    {"id": 5, "description": "another new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
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
