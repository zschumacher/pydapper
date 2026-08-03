import pytest
from mysql.connector import ProgrammingError

from pydapper import connect
from pydapper import using
from pydapper.exceptions import MultipleStatementsError
from pydapper.mysql import MySqlConnectorPythonCommands
from tests.test_adapter_units import MULTI_STATEMENTS
from tests.test_suites.commands import ExecuteScalarTestSuite
from tests.test_suites.commands import ExecuteTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultTestSuite
from tests.test_suites.commands import QueryFirstTestSuite
from tests.test_suites.commands import QueryMultipleTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultTestSuite
from tests.test_suites.commands import QuerySingleTestSuite
from tests.test_suites.commands import QueryTestSuite

pytestmark = pytest.mark.mysql


@pytest.fixture(scope="function")
def commands(server, database_name, db_port) -> MySqlConnectorPythonCommands:
    import mysql.connector

    with MySqlConnectorPythonCommands(
        mysql.connector.connect(host=server, port=db_port, user="pydapper", password="pydapper", database=database_name)
    ) as commands:
        yield commands


def test_using(server, database_name, db_port):
    import mysql.connector

    with using(
        mysql.connector.connect(host=server, port=db_port, user="pydapper", password="pydapper", database=database_name)
    ) as commands:
        assert isinstance(commands, MySqlConnectorPythonCommands)


@pytest.mark.parametrize("driver", ["mysql", "mysql+mysql"])
def test_connect(driver, database_name, server, db_port):
    with connect(f"{driver}://pydapper:pydapper@{server}:{db_port}/{database_name}") as commands:
        assert isinstance(commands, MySqlConnectorPythonCommands)


@pytest.fixture()
def dsn(database_name, server, db_port):
    return f"mysql://pydapper:pydapper@{server}:{db_port}/{database_name}"


def test_the_mirrored_multi_statements_constant_matches_the_installed_driver():
    """tests/test_adapter_units.py mirrors this value so the core suite needs no mysql extra."""
    import mysql.connector

    assert mysql.connector.constants.ClientFlag.MULTI_STATEMENTS == MULTI_STATEMENTS


def test_connect_clears_multi_statements_on_the_wire(dsn):
    with connect(dsn) as commands:
        assert not commands.connection._client_flags & MULTI_STATEMENTS


def test_connect_clears_multi_statements_even_when_the_caller_passes_client_flags(dsn):
    import mysql.connector

    found_rows = mysql.connector.constants.ClientFlag.FOUND_ROWS
    with connect(dsn, client_flags=[found_rows]) as commands:
        assert commands.connection._client_flags & found_rows
        assert not commands.connection._client_flags & MULTI_STATEMENTS


def test_the_driver_falls_back_to_a_multi_statement_default_on_a_falsy_client_flags():
    """Pins the upstream behavior the resolution is built around.

    ``MySQLConnectionAbstract.config`` resolves the option as ``config["client_flags"] or default``,
    and that default enables ``MULTI_STATEMENTS``. Any falsy value therefore skips the setter and
    silently re-enables the flag, which is why ``_resolve_client_flags`` never emits one. If a future
    driver release changes either fact, this test fails and the resolution should be revisited.
    """
    import inspect

    import mysql.connector
    import mysql.connector.abstracts as abstracts
    from mysql.connector.constants import ClientFlag

    source = inspect.getsource(abstracts.MySQLConnectionAbstract.config)
    assert 'self.client_flags = config["client_flags"] or default' in source
    assert ClientFlag.get_default() & ClientFlag.MULTI_STATEMENTS
    # the driver's own default configuration uses a falsy value, so this is not a hypothetical input
    assert not mysql.connector.constants.DEFAULT_CONFIGURATION["client_flags"]


@pytest.mark.parametrize("caller_value", [None, 0, False, []])
def test_connect_clears_multi_statements_for_a_falsy_client_flags(dsn, caller_value):
    with connect(dsn, client_flags=caller_value) as commands:
        assert not commands.connection._client_flags & MULTI_STATEMENTS


def test_connect_refuses_client_flags_that_asks_only_for_multi_statements(dsn):
    with pytest.raises(ValueError, match="CLIENT_MULTI_STATEMENTS and nothing else"):
        connect(dsn, client_flags=MULTI_STATEMENTS)


def test_a_raw_cursor_on_a_pydapper_connection_cannot_run_a_batch_for_any_client_flags(dsn):
    """The connect-time denial must hold for every input shape, not just the default one."""
    for caller_value in (None, 0, False, [], [MULTI_STATEMENTS], MULTI_STATEMENTS | 1):
        with connect(dsn, client_flags=caller_value) as commands:
            assert not commands.connection._client_flags & MULTI_STATEMENTS, caller_value
            cursor = commands.connection.cursor()
            try:
                with pytest.raises(ProgrammingError) as exc_info:
                    cursor.execute("select 1 as a; select 2 as b")
                    cursor.fetchall()
                assert "1064" in str(exc_info.value), caller_value
            finally:
                cursor.close()


def test_using_keeps_the_callers_own_flags(server, database_name, db_port):
    """Connect-time denial covers only connections pydapper opens; ``using()`` keeps the caller's."""
    import mysql.connector

    conn = mysql.connector.connect(
        host=server, port=db_port, user="pydapper", password="pydapper", database=database_name
    )
    with using(conn) as commands:
        assert commands.connection._client_flags & MULTI_STATEMENTS


def test_appended_statement_never_executes(dsn):
    victim_sql = "select 1 as a; drop table multi_statement_victim;"

    with connect(dsn) as setup:
        setup.execute("drop table if exists multi_statement_victim")
        setup.execute("create table multi_statement_victim (id int)")
        setup.commit()

    try:
        with connect(dsn) as commands:
            with pytest.raises(MultipleStatementsError):
                commands.query(victim_sql)

            # The pydapper guard is only half the contract. Bypassing it with a raw cursor on a
            # connection pydapper opened must still fail, at the server, without dropping anything.
            cursor = commands.connection.cursor()
            try:
                with pytest.raises(ProgrammingError) as exc_info:
                    cursor.execute(victim_sql)
                    cursor.fetchall()
                assert "1064" in str(exc_info.value)
            finally:
                cursor.close()

        with connect(dsn) as verify:
            assert verify.execute_scalar("show tables like 'multi_statement_victim'") == "multi_statement_victim"
    finally:
        with connect(dsn) as cleanup:
            cleanup.execute("drop table if exists multi_statement_victim")
            cleanup.commit()


class TestExecute(ExecuteTestSuite): ...


class TestQuery(QueryTestSuite): ...


class TestQueryMultiple(QueryMultipleTestSuite): ...


class TestQueryFirst(QueryFirstTestSuite): ...


class TestQueryFirstOrDefault(QueryFirstOrDefaultTestSuite): ...


class TestQuerySingle(QuerySingleTestSuite): ...


class TestQuerySingleOrDefault(QuerySingleOrDefaultTestSuite): ...


class TestExecuteScalar(ExecuteScalarTestSuite): ...
