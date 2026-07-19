import os
import sqlite3
from dataclasses import dataclass

import pytest

from pydapper import RawRow
from pydapper import connect
from pydapper import using
from pydapper.exceptions import DuplicateColumnException
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
    with connect(f"{driver}:///{setup_sql_dir}{os.path.sep}{database_name}.db") as commands:
        assert isinstance(commands, Sqlite3Commands)


@pytest.mark.parametrize("driver", ["sqlite", "sqlite+sqlite3"])
def test_connect(driver, database_name):
    with connect(f"{driver}://{database_name}.db") as commands:
        assert isinstance(commands, Sqlite3Commands)


def test_join_with_duplicate_id_columns_raises(commands, owner_table_name, task_table_name):
    with pytest.raises(DuplicateColumnException) as exc_info:
        commands.query(
            f"select {task_table_name}.id, {owner_table_name}.id "
            f"from {task_table_name} join {owner_table_name} on {task_table_name}.owner_id = {owner_table_name}.id"
        )

    assert exc_info.value.columns == ("id", "id")
    assert exc_info.value.duplicate_columns == ("id",)
    assert exc_info.value.duplicate_indexes == (0, 1)


def test_join_with_aliased_id_columns_succeeds(commands, owner_table_name, task_table_name):
    rows = commands.query(
        f"select {task_table_name}.id as task_id, {owner_table_name}.id as owner_id "
        f"from {task_table_name} join {owner_table_name} on {task_table_name}.owner_id = {owner_table_name}.id"
    )

    assert rows[0] == {"task_id": 1, "owner_id": 1}
    assert list(rows[0]) == ["task_id", "owner_id"]


def test_mapper_can_project_join_with_duplicate_columns(commands, owner_table_name, task_table_name):
    @dataclass
    class Owner:
        id: int
        name: str

    @dataclass
    class TaskWithOwner:
        id: int
        description: str
        owner: Owner

    def to_task(row: RawRow) -> TaskWithOwner:
        return TaskWithOwner(
            id=row.values[0],
            description=row.values[1],
            owner=Owner(id=row.values[2], name=row.values[3]),
        )

    rows = commands.query(
        f"""
        select
            {task_table_name}.id,
            {task_table_name}.description,
            {owner_table_name}.id,
            {owner_table_name}.name
        from {task_table_name}
        join {owner_table_name} on {task_table_name}.owner_id = {owner_table_name}.id
        order by {task_table_name}.id
        """,
        mapper=to_task,
    )

    assert rows[0] == TaskWithOwner(
        id=1,
        description="Set up a test database",
        owner=Owner(id=1, name="Zach Schumacher"),
    )


def test_mapper_can_use_aliases_by_name(commands, owner_table_name, task_table_name):
    rows = commands.query(
        f"""
        select
            {task_table_name}.id as task_id,
            {owner_table_name}.name as owner_name
        from {task_table_name}
        join {owner_table_name} on {task_table_name}.owner_id = {owner_table_name}.id
        order by {task_table_name}.id
        """,
        mapper=lambda row: {"task_id": row["task_id"], "owner_name": row.as_dict()["owner_name"]},
    )

    assert rows[0] == {"task_id": 1, "owner_name": "Zach Schumacher"}


class TestExecute(ExecuteTestSuite): ...


class TestQuery(QueryTestSuite): ...


class TestQueryMultiple(QueryMultipleTestSuite): ...


class TestQueryFirst(QueryFirstTestSuite): ...


class TestQueryFirstOrDefault(QueryFirstOrDefaultTestSuite): ...


class TestQuerySingle(QuerySingleTestSuite): ...


class TestQuerySingleOrDefault(QuerySingleOrDefaultTestSuite): ...


class TestExecuteScalar(ExecuteScalarTestSuite): ...
