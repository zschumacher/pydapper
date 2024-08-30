from contextlib import ExitStack

import pytest

from pydapper.dsn_parser import PydapperParseResult
from pydapper.dsn_parser import parse

SQLITE3_DSN = "sqlite+sqlite3://some.db"
PSYCOPG2_DSN = "postgresql+psycopg2://pydapper:password@localhost:5433/postgres"
PSYCOPG3_DSN = "postgresql+psycopg://pydapper:password@localhost:5433/postgres"
PYMSSQL_DSN = "mssql+pymssql://sa:pydapper!PYDAPPER@localhost:1433/master"
MYSQL_CONNECTOR_PYTHON_DSN = "mysql+mysql://pydapper:pydapper@localhost:3307/pydapper"
CX_ORACLE_DSN = "oracle+cx_Oracle://pydapper:pydapper@localhost:1522/pydapper"
AIOPG_DSN = "postgresql+aiopg://pydapper:pydapper@localhost:5433/postgres"
SQLITE_DEFAULT_DSN = "sqlite://some.db"
POSTGRES_DEFAULT_DSN = "postgresql://pydapper:password@localhost:5433/postgres"
MSSQL_DEFAULT_DSN = "mssql://sa:pydapper!PYDAPPER@localhost:1433/master"
MYSQL_DEFAULT_DSN = "mysql://pydapper:pyapper@localhost:3307/pydapper"
ORACLE_DEFAULT_DSN = "oracle://pydapper:pydapper@localhost:1522/pydapper"


ALL_DSNS = [
    SQLITE3_DSN,
    PSYCOPG2_DSN,
    PSYCOPG3_DSN,
    PYMSSQL_DSN,
    MYSQL_CONNECTOR_PYTHON_DSN,
    CX_ORACLE_DSN,
    AIOPG_DSN,
    SQLITE_DEFAULT_DSN,
    POSTGRES_DEFAULT_DSN,
    MSSQL_DEFAULT_DSN,
    MYSQL_DEFAULT_DSN,
    ORACLE_DEFAULT_DSN,
]

pytestmark = pytest.mark.core


class TestPydapperParseResult:
    @pytest.mark.parametrize("dsn", ALL_DSNS)
    def test__repr__(self, dsn):
        parsed_dsn = PydapperParseResult(dsn)
        assert parsed_dsn.__repr__()

    @pytest.mark.parametrize(
        "dsn, expected",
        [
            (SQLITE3_DSN, "sqlite"),
            (PSYCOPG2_DSN, "postgresql"),
            (PSYCOPG3_DSN, "postgresql"),
            (PYMSSQL_DSN, "mssql"),
            (MYSQL_CONNECTOR_PYTHON_DSN, "mysql"),
            (CX_ORACLE_DSN, "oracle"),
            (AIOPG_DSN, "postgresql"),
            (SQLITE_DEFAULT_DSN, "sqlite"),
            (POSTGRES_DEFAULT_DSN, "postgresql"),
            (MSSQL_DEFAULT_DSN, "mssql"),
            (MYSQL_DEFAULT_DSN, "mysql"),
            (ORACLE_DEFAULT_DSN, "oracle"),
        ],
    )
    def test_dbms(self, dsn, expected):
        parsed_dsn = PydapperParseResult(dsn)
        assert parsed_dsn.dbms == expected

    @pytest.mark.parametrize(
        "dsn, expected",
        [
            (SQLITE3_DSN, "sqlite3"),
            (PSYCOPG2_DSN, "psycopg2"),
            (PSYCOPG3_DSN, "psycopg"),
            (PYMSSQL_DSN, "pymssql"),
            (MYSQL_CONNECTOR_PYTHON_DSN, "mysql"),
            (CX_ORACLE_DSN, "cx_Oracle"),
            (AIOPG_DSN, "aiopg"),
            (SQLITE_DEFAULT_DSN, "sqlite3"),
            (POSTGRES_DEFAULT_DSN, "psycopg2"),
            (MSSQL_DEFAULT_DSN, "pymssql"),
            (MYSQL_DEFAULT_DSN, "mysql"),
            (ORACLE_DEFAULT_DSN, "cx_Oracle"),
            ("postgresql+://locahost:5432/postgres", ValueError),
        ],
    )
    def test_db_api(self, dsn, expected):
        parsed_dsn = PydapperParseResult(dsn)
        with ExitStack() as stack:
            if not isinstance(expected, str) and issubclass(expected, Exception):
                stack.enter_context(pytest.raises(expected))
            assert parsed_dsn.dbapi == expected


@pytest.mark.parametrize("dsn", ALL_DSNS)
def test_parse(dsn):
    parsed = PydapperParseResult(dsn)
    assert parsed == parse(dsn)
