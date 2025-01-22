import datetime
from dataclasses import dataclass

import pytest

from pydapper import connect
from pydapper import using
from pydapper.oracle import OracledbCommands
from tests.test_suites.commands import ExecuteScalarTestSuite
from tests.test_suites.commands import ExecuteTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultTestSuite
from tests.test_suites.commands import QueryFirstTestSuite
from tests.test_suites.commands import QueryMultipleTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultTestSuite
from tests.test_suites.commands import QuerySingleTestSuite
from tests.test_suites.commands import QueryTestSuite

pytestmark = pytest.mark.oracle


@pytest.fixture(scope="function")
def commands(server, database_name) -> OracledbCommands:
    import oracledb

    with OracledbCommands(
        oracledb.connect(password="pydapper", user="pydapper", dsn=f"{server}:1522/{database_name}")
    ) as commands:
        yield commands


def test_using(server, database_name):
    import oracledb

    with using(
        oracledb.connect(password="pydapper", user="pydapper", dsn=f"{server}:1522/{database_name}")
    ) as commands:
        assert isinstance(commands, OracledbCommands)
        assert isinstance(commands.connection, oracledb.Connection)


@pytest.mark.parametrize("driver", ["oracle+oracledb"])
def test_connect(driver, database_name, server):
    import oracledb

    with connect(f"{driver}://pydapper:pydapper@{server}:1522/{database_name}") as commands:
        assert isinstance(commands, OracledbCommands)
        assert isinstance(commands.connection, oracledb.Connection)


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


class TestQuery(QueryTestSuite): ...


class TestQueryMultiple(QueryMultipleTestSuite):
    def test_different_models(self, commands, owner_table_name, task_table_name):
        @dataclass
        class Task:
            ID: int
            DESCRIPTION: str
            DUE_DATE: datetime.date
            OWNER_ID: int

        @dataclass
        class Owner:
            ID: int
            NAME: str

        owner, task = commands.query_multiple(
            (
                f"select id, name from {owner_table_name}",
                f"select id, description, due_date, owner_id from {task_table_name}",
            ),
            models=(Owner, Task),
        )

        assert len(owner) == 1
        assert len(task) == 3
        assert isinstance(owner[0], Owner)
        assert all(isinstance(record, Task) for record in task)


class TestQueryFirst(QueryFirstTestSuite):
    def test_param(self, commands, task_table_name):
        task = commands.query_first(f"select id from {task_table_name} where id = ?id?", param={"id": 1})
        assert task["ID"] == 1


class TestQueryFirstOrDefault(QueryFirstOrDefaultTestSuite): ...


class TestQuerySingle(QuerySingleTestSuite):
    def test(self, commands, task_table_name):
        task = commands.query_single(f"select id from {task_table_name} where id = 1")
        assert task["ID"] == 1

    def test_param(self, commands, task_table_name):
        task = commands.query_single(f"select id from {task_table_name} where id = ?id?", param={"id": 1})
        assert task["ID"] == 1


class TestQuerySingleOrDefault(QuerySingleOrDefaultTestSuite): ...


class TestExecuteScalar(ExecuteScalarTestSuite): ...
