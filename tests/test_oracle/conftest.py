import pytest
from testcontainers.oracle import OracleDbContainer


@pytest.fixture(scope="session")
def oracle_container(database_name):
    with OracleDbContainer(
        username="pydapper",
        password="pydapper",
        dbname=database_name,
    ) as oracle:
        yield oracle


@pytest.fixture(scope="session")
def db_port(oracle_container):
    return oracle_container.get_exposed_port(oracle_container.port)


@pytest.fixture(scope="session", autouse=True)
def oracle_setup(database_name, setup_sql_dir, server, db_port):
    import oracledb

    conn = oracledb.connect(password="pydapper", user="pydapper", dsn=f"{server}:{db_port}/{database_name}")
    cursor = conn.cursor()
    owner_table = (setup_sql_dir / "oracle" / "owner.sql").read_text()
    cursor.execute(owner_table)
    task_table = (setup_sql_dir / "oracle" / "task.sql").read_text()
    cursor.execute(task_table)
    owner_insert = (setup_sql_dir / "oracle" / "insert_owner.sql").read_text()
    cursor.execute(owner_insert)
    task_insert = (setup_sql_dir / "oracle" / "insert_task.sql").read_text()
    cursor.execute(task_insert)
    conn.commit()
    conn.close()
