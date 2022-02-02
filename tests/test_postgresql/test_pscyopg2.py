import psycopg2
import pytest

from pydapper import connect
from pydapper import using
from pydapper.postgresql.psycopg2 import Psycopg2Commands


def test_using(server, database_name):
    with using(psycopg2.connect(f"postgresql://pydapper:pydapper@{server}:5433/{database_name}")) as commands:
        assert isinstance(commands, Psycopg2Commands)


@pytest.mark.parametrize("driver", ["postgresql", "postgresql+psycopg2"])
def test_connect(driver, server, database_name):
    with connect(f"{driver}://pydapper:pydapper@{server}:5433/{database_name}") as commands:
        assert isinstance(commands, Psycopg2Commands)
