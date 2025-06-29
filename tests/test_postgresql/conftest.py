import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container(database_name):
    with PostgresContainer(username="pydapper", password="pydapper", dbname=database_name) as postgres:
        yield postgres


@pytest.fixture(scope="session")
def db_port(postgres_container):
    return postgres_container.get_exposed_port(postgres_container.port)


@pytest.fixture(scope="session", autouse=True)
def postgres_setup(setup_sql_dir, database_name, server, db_port):
    import psycopg2

    setup_sql = (setup_sql_dir / "postgresql.sql").read_text()
    with psycopg2.connect(f"postgresql://pydapper:pydapper@{server}:{db_port}/{database_name}") as conn:
        with conn.cursor() as cursor:
            cursor.execute(setup_sql)
