import datetime

import pytest

import pydapper
from pydapper.bigquery import GoogleBigqueryClientCommands
from tests.test_suites.commands import ExecuteScalarTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultTestSuite
from tests.test_suites.commands import QueryFirstTestSuite
from tests.test_suites.commands import QueryMultipleTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultTestSuite
from tests.test_suites.commands import QuerySingleTestSuite
from tests.test_suites.commands import QueryTestSuite

pytestmark = pytest.mark.bigquery


def test_using(client):
    from google.cloud.bigquery.dbapi import connect

    with pydapper.using(connect(client=client)) as commands:
        assert isinstance(commands, GoogleBigqueryClientCommands)


@pytest.mark.parametrize("driver", ["bigquery", "bigquery+google"])
def test_connect(driver, client):
    with pydapper.connect(f"{driver}:////", client=client) as commands:
        assert isinstance(commands, GoogleBigqueryClientCommands)


@pytest.mark.usefixtures("bigquery_setup")
class TestExecute:
    def test_single(self, commands, owner_table_name):
        commands.execute(f"UPDATE {owner_table_name} SET name = ?new_name? WHERE id = 1", {"new_name": "Zachary"})
        assert commands.execute_scalar(f"select name from {owner_table_name} where id = 1") == "Zachary"

    def test_multiple(self, commands, task_table_name):
        commands.execute(
            f"INSERT INTO {task_table_name} (description, due_date, owner_id) "
            "VALUES (?description?, ?due_date?, ?owner_id?)",
            [
                {"description": "new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
                {"description": "another new task", "due_date": datetime.date(2022, 1, 1), "owner_id": 1},
            ],
        )
        # count seems to not work with the bigquery emulator?
        assert len(commands.query(f"select * from {task_table_name}")) == 5


@pytest.mark.usefixtures("bigquery_setup")
class TestQuery(QueryTestSuite): ...


@pytest.mark.usefixtures("bigquery_setup")
class TestQueryMultiple(QueryMultipleTestSuite): ...


@pytest.mark.usefixtures("bigquery_setup")
class TestQueryFirst(QueryFirstTestSuite): ...


@pytest.mark.usefixtures("bigquery_setup")
class TestQueryFirstOrDefault(QueryFirstOrDefaultTestSuite): ...


@pytest.mark.usefixtures("bigquery_setup")
class TestQuerySingle(QuerySingleTestSuite): ...


@pytest.mark.usefixtures("bigquery_setup")
class TestQuerySingleOrDefault(QuerySingleOrDefaultTestSuite): ...


@pytest.mark.usefixtures("bigquery_setup")
class TestExecuteScalar(ExecuteScalarTestSuite): ...
