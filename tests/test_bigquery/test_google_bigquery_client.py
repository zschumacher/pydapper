import pytest

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

pytestmark = pytest.mark.bigquery


def test_using(creds_as_env_var):
    from google.cloud.bigquery.dbapi import connect

    with pydapper.using(connect()) as commands:
        assert isinstance(commands, GoogleBigqueryClientCommands)


@pytest.mark.parametrize("driver", ["bigquery", "bigquery+google"])
def test_connect_from_env(creds_as_env_var, driver):
    with pydapper.connect(f"{driver}:////") as commands:
        assert isinstance(commands, GoogleBigqueryClientCommands)


@pytest.mark.usefixtures("bigquery_setup")
class TestExecute(ExecuteTestSuite):
    ...


@pytest.mark.usefixtures("bigquery_setup")
class TestQuery(QueryTestSuite):
    ...


@pytest.mark.usefixtures("bigquery_setup")
class TestQueryMultiple(QueryMultipleTestSuite):
    ...


@pytest.mark.usefixtures("bigquery_setup")
class TestQueryFirst(QueryFirstTestSuite):
    ...


@pytest.mark.usefixtures("bigquery_setup")
class TestQueryFirstOrDefault(QueryFirstOrDefaultTestSuite):
    ...


@pytest.mark.usefixtures("bigquery_setup")
class TestQuerySingle(QuerySingleTestSuite):
    ...


@pytest.mark.usefixtures("bigquery_setup")
class TestQuerySingleOrDefault(QuerySingleOrDefaultTestSuite):
    ...


@pytest.mark.usefixtures("bigquery_setup")
class TestExecuteScalar(ExecuteScalarTestSuite):
    ...
