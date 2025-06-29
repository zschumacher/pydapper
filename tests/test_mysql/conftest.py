import pytest
from testcontainers.mysql import MySqlContainer


@pytest.fixture(scope="session")
def mysql_container(database_name):
    with MySqlContainer(
        username="pydapper",
        dialect="mysqlconnector",
        password="pydapper",
        dbname=database_name,
    ) as mysql:
        yield mysql


@pytest.fixture(scope="session")
def db_port(mysql_container):
    return mysql_container.get_exposed_port(mysql_container.port)


@pytest.fixture(scope="session", autouse=True)
def mysql_setup(database_name, setup_sql_dir, server, db_port):
    import mysql.connector

    conn = mysql.connector.connect(host=server, port=db_port, user="pydapper", password="pydapper", autocommit=True)
    cursor = conn.cursor()
    owner_table = (setup_sql_dir / "mysql" / "owner.sql").read_text()
    cursor.execute(owner_table)
    task_table = (setup_sql_dir / "mysql" / "task.sql").read_text()
    cursor.execute(task_table)
    owner_insert = (setup_sql_dir / "mysql" / "insert_owner.sql").read_text()
    cursor.execute(owner_insert)
    task_insert = (setup_sql_dir / "mysql" / "insert_task.sql").read_text()
    cursor.execute(task_insert)
    conn.close()
