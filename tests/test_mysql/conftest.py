import pytest


@pytest.fixture(scope="session", autouse=True)
def mysql_setup(database_name, setup_sql_dir, server):
    import mysql.connector

    conn = mysql.connector.connect(host=server, port=3307, user="pydapper", password="pydapper", autocommit=True)
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
