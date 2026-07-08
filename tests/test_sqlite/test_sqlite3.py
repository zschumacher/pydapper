import os
import sqlite3

import pytest

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
    with connect(f"{driver}://{setup_sql_dir}{os.path.sep}{database_name}.db") as commands:
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


class TestExecute(ExecuteTestSuite): ...


class TestQuery(QueryTestSuite): ...


class TestQueryMultiple(QueryMultipleTestSuite): ...


class TestQueryFirst(QueryFirstTestSuite): ...


class TestQueryFirstOrDefault(QueryFirstOrDefaultTestSuite): ...


class TestQuerySingle(QuerySingleTestSuite): ...


class TestQuerySingleOrDefault(QuerySingleOrDefaultTestSuite): ...


class TestExecuteScalar(ExecuteScalarTestSuite): ...
