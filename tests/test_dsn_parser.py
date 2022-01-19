from contextlib import ExitStack

import pytest

from pydapper.dsn_parser import PydapperParseResult
from pydapper.dsn_parser import parse
from tests.dsn import *


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
            (PYMSSQL_DSN, "mssql"),
            (SQLITE_DEFAULT_DSN, "sqlite"),
            (POSTGRES_DEFAULT_DSN, "postgresql"),
            (MSSQL_DEFAULT_DSN, "mssql"),
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
            (PYMSSQL_DSN, "pymssql"),
            (SQLITE_DEFAULT_DSN, "sqlite3"),
            (POSTGRES_DEFAULT_DSN, "psycopg2"),
            (MSSQL_DEFAULT_DSN, "pymssql"),
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
