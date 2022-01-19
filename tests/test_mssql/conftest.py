from contextlib import suppress

import pytest
from pymssql import _pymssql

import pydapper
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
def base_connect_args_kwargs(user, password, server, port):
    return (server, user, password), {"port": port}


@pytest.fixture(scope="session")
def default_connect_args_kwargs(base_connect_args_kwargs):
    args, kwargs = base_connect_args_kwargs
    return (*args, "master"), kwargs


@pytest.fixture(scope="session")
def application_connect_args_kwargs(base_connect_args_kwargs, database_name):
    args, kwargs = base_connect_args_kwargs
    return (*args, database_name), kwargs


@pytest.fixture(scope="session")
def application_dsn(user, password, server, port, database_name):
    return f"mssql+pymssql://{user}:{password}@{server}/{database_name}"


@pytest.fixture(scope="session", autouse=True)
def mssql_setup(default_connect_args_kwargs, application_connect_args_kwargs, database_name, setup_sql_dir):
    default_args, default_kwargs = application_connect_args_kwargs
    with _pymssql.connect(*default_args, **default_kwargs) as conn:
        conn.autocommit(True)
        with conn.cursor() as cursor:
            with suppress(_pymssql.OperationalError):
                cursor.execute(f"CREATE DATABASE {database_name}")

    app_args, app_kwargs = application_connect_args_kwargs
    with _pymssql.connect(*app_args, **app_kwargs) as conn:
        with conn.cursor() as cursor:
            setup_sql = (setup_sql_dir / "mssql.sql").read_text()
            cursor.execute(setup_sql)
            conn.commit()


@pytest.fixture(scope="function")
def commands(application_dsn) -> Psycopg2Commands:
    with Psycopg2Commands(pydapper.connect(application_dsn)) as commands:
        yield commands
