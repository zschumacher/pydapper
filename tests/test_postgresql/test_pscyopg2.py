import psycopg2

from pydapper import connect
from pydapper import using
from pydapper.postgresql.psycopg2 import Psycopg2Commands


def test_using(server, database_name):
    with using(psycopg2.connect(f"postgresql://pydapper:pydapper@{server}:5433/{database_name}")) as commands:
        assert isinstance(commands, Psycopg2Commands)


def test_connect(server, database_name):
    with connect(f"postgresql+psycopg2://pydapper:pydapper@{server}:5433/{database_name}") as commands:
        assert isinstance(commands, Psycopg2Commands)
