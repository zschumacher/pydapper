from contextlib import suppress

import pytest
from testcontainers.mssql import SqlServerContainer

pytestmark = pytest.mark.mssql


@pytest.fixture(scope="session")
def mssql_container(database_name):
    with SqlServerContainer(password="pydapper!PYDAPPER") as mssql:
        yield mssql


@pytest.fixture(scope="session")
def db_port(mssql_container):
    return mssql_container.get_exposed_port(mssql_container.port)


@pytest.fixture(scope="session", autouse=True)
def mssql_setup(database_name, setup_sql_dir, server, db_port):
    from pymssql import _pymssql

    with _pymssql.connect(
        server=server, port=str(db_port), password="pydapper!PYDAPPER", user="sa", database="master"
    ) as conn:
        conn.autocommit(True)
        with conn.cursor() as cursor:
            with suppress(_pymssql.OperationalError):
                cursor.execute(f"CREATE DATABASE {database_name}")

    with _pymssql.connect(
        server=server, port=str(db_port), password="pydapper!PYDAPPER", user="sa", database=database_name
    ) as conn:
        with conn.cursor() as cursor:
            setup_sql = (setup_sql_dir / "mssql.sql").read_text()
            cursor.execute(setup_sql)
            conn.commit()
