import cx_Oracle
import pytest

from pydapper import connect
from pydapper import using
from pydapper.oracle import CxOracleCommands


def test_using(server, database_name):
    with using(
        cx_Oracle.connect(password="pydapper", user="pydapper", dsn=f"{server}:1522/{database_name}")
    ) as commands:
        assert isinstance(commands, CxOracleCommands)


@pytest.mark.parametrize("driver", ["oracle", "oracle+cx_Oracle"])
def test_connect(driver, database_name, server):
    with connect(f"{driver}://pydapper:pydapper@{server}:1522/{database_name}") as commands:
        assert isinstance(commands, CxOracleCommands)
