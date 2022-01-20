from contextlib import suppress

import psycopg2
import pytest
from psycopg2.errors import DuplicateDatabase
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from pydapper.postgresql.psycopg2 import Psycopg2Commands


@pytest.fixture(scope="session")
def user():
    return "pydapper"


@pytest.fixture(scope="session")
def password():
    return "pydapper"


@pytest.fixture(scope="session")
def port():
    return "5433"


@pytest.fixture(scope="session")
def base_dsn(user, password, server, port):
    return f"postgresql://{user}:{password}@{server}:{port}"


@pytest.fixture(scope="session")
def default_dsn(base_dsn):
    return f"{base_dsn}/postgres"


@pytest.fixture(scope="session")
def application_dsn(base_dsn, database_name):
    return f"{base_dsn}/{database_name}"


@pytest.fixture(scope="session", autouse=True)
def postgres_setup(default_dsn, application_dsn, setup_sql_dir, database_name):
    # connect to the root and create the db
    conn = psycopg2.connect(default_dsn)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    with suppress(DuplicateDatabase):
        cursor.execute(f"CREATE DATABASE {database_name}")

    # connect to the newly created database and create the tables
    setup_sql = (setup_sql_dir / "postgresql.sql").read_text()
    with psycopg2.connect(application_dsn) as conn:
        with conn.cursor() as cursor:
            cursor.execute(setup_sql)


@pytest.fixture(scope="function")
def psycopg2_connection(application_dsn) -> Psycopg2Commands:
    with Psycopg2Commands(psycopg2.connect(application_dsn)) as commands:
        yield commands
        commands.connection.rollback()
