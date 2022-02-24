import psycopg2
import pytest

from pydapper.postgresql import AiopgCommands
from pydapper.postgresql import Psycopg2Commands


@pytest.fixture(scope="session", autouse=True)
def postgres_setup(setup_sql_dir, database_name, server):
    # connect to the newly created database and create the tables
    setup_sql = (setup_sql_dir / "postgresql.sql").read_text()
    with psycopg2.connect(f"postgresql://pydapper:pydapper@{server}:5433/{database_name}") as conn:
        with conn.cursor() as cursor:
            cursor.execute(setup_sql)
