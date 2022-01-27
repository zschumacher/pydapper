import datetime
from decimal import Decimal

import mysql.connector
import pytest

from pydapper import connect
from pydapper import using
from pydapper.mysql import MySqlConnectorPythonCommands


def test_using(server, database_name):
    with using(
        mysql.connector.connect(host=server, port=3307, password="pydapper", user="root", database=database_name)
    ) as commands:
        assert isinstance(commands, MySqlConnectorPythonCommands)


def test_connect(database_name, server):
    with connect(f"mysql+mysql://root:pydapper@{server}:3307/{database_name}") as commands:
        assert isinstance(commands, MySqlConnectorPythonCommands)
