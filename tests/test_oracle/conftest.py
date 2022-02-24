import cx_Oracle
import pytest

from pydapper.oracle import CxOracleCommands


@pytest.fixture(scope="session", autouse=True)
def oracle_setup(database_name, setup_sql_dir, server):
    conn = cx_Oracle.connect(password="pydapper", user="pydapper", dsn=f"{server}:1522/{database_name}")
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
