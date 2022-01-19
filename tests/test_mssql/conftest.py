from contextlib import suppress

import pytest
from pymssql import _pymssql

import pydapper
from pydapper.postgresql.psycopg2 import Psycopg2Commands


@pytest.fixture(scope="session")
def user():
    return "sa"


@pytest.fixture(scope="session")
def password():
    return "pydapper!PYDAPPER"


@pytest.fixture(scope="session")
def port():
    return "1434"


@pytest.fixture(scope="session")
def base_connect_kwargs(user, password, server, port):
    return {"server": server, "user": user, "password": password, "port": port}


@pytest.fixture(scope="session")
def default_connect_kwargs(base_connect_kwargs):
    return {**base_connect_kwargs, "database": "master"}


@pytest.fixture(scope="session")
def application_connect_kwargs(base_connect_kwargs, database_name):
    return {**base_connect_kwargs, "database": database_name}


@pytest.fixture(scope="session")
def application_dsn(user, password, server, port, database_name):
    return f"mssql+pymssql://{user}:{password}@{server}:{port}/{database_name}"


@pytest.fixture(scope="session", autouse=True)
def mssql_setup(default_connect_kwargs, application_connect_kwargs, database_name, setup_sql_dir):
    with _pymssql.connect(**default_connect_kwargs) as conn:
        conn.autocommit(True)
        with conn.cursor() as cursor:
            with suppress(_pymssql.OperationalError):
                cursor.execute(f"CREATE DATABASE {database_name}")

    with _pymssql.connect(**application_connect_kwargs) as conn:
        with conn.cursor() as cursor:
            setup_sql = (setup_sql_dir / "mssql.sql").read_text()
            cursor.execute(setup_sql)
            conn.commit()


@pytest.fixture(scope="function")
def commands(application_dsn) -> Psycopg2Commands:
    with Psycopg2Commands(pydapper.connect(application_dsn)) as commands:
        yield commands
