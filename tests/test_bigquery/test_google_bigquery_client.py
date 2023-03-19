import pytest
from google.cloud.bigquery.dbapi import connect

import pydapper
from pydapper.bigquery import GoogleBigqueryClientCommands
from tests.test_suites.commands import ExecuteScalarTestSuite
from tests.test_suites.commands import ExecuteTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultTestSuite
from tests.test_suites.commands import QueryFirstTestSuite
from tests.test_suites.commands import QueryMultipleTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultTestSuite
from tests.test_suites.commands import QuerySingleTestSuite
from tests.test_suites.commands import QueryTestSuite


def test_using(creds_as_env_var):
    with pydapper.using(connect()) as commands:
        assert isinstance(commands, GoogleBigqueryClientCommands)


@pytest.mark.parametrize("driver", ["bigquery", "bigquery+google"])
def test_connect_from_env(creds_as_env_var, driver):
    with pydapper.connect(f"{driver}:////") as commands:
        assert isinstance(commands, GoogleBigqueryClientCommands)


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
