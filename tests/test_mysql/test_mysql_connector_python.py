import mysql.connector

from pydapper import connect
from pydapper import using
from pydapper.mysql import MySqlConnectorPythonCommands
import pytest

def test_using(server, database_name):
    with using(
        mysql.connector.connect(host=server, port=3307, user="pydapper", password="pydapper", database=database_name)
    ) as commands:
        assert isinstance(commands, MySqlConnectorPythonCommands)


@pytest.mark.parametrize("driver", ["mysql", "mysql+mysql"])
def test_connect(driver, database_name, server):
    with connect(f"{driver}://pydapper:pydapper@{server}:3307/{database_name}") as commands:
        assert isinstance(commands, MySqlConnectorPythonCommands)
