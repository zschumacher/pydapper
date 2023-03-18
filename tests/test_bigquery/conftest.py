from pathlib import Path

import pytest
from google.cloud.bigquery.dbapi import connect

from pydapper.bigquery import GoogleBigqueryClientCommands
from tests.test_bigquery.utils import write_auth_file

AUTH_FILE_PATH = Path(__file__).parent / Path("auth") / "key.json"


@pytest.fixture(scope="function")
def creds_as_env_var(monkeypatch):
    write_auth_file()
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(AUTH_FILE_PATH))


@pytest.fixture(scope="function")
def commands() -> GoogleBigqueryClientCommands:
    with GoogleBigqueryClientCommands(connect()) as commands:
        yield commands


@pytest.fixture(scope="function", autouse=True)
def bigquery_setup(database_name, setup_sql_dir, creds_as_env_var):
    """We have to tear down after each test, which will unfortunately be slow but it is what it is"""
    conn = connect()
    cursor = conn.cursor()
    owner = (setup_sql_dir / "bigquery" / "owner.sql").read_text()
    cursor.execute(owner)
    owner_insert = (setup_sql_dir / "bigquery" / "insert_owner.sql").read_text()
    cursor.execute(owner_insert)
    task = (setup_sql_dir / "bigquery" / "task.sql").read_text()
    cursor.execute(task)
    task_insert = (setup_sql_dir / "bigquery" / "insert_task.sql").read_text()
    cursor.execute(task_insert)
    yield
    cursor.execute(f"delete from {database_name}.task where true")
    cursor.execute(f"delete from {database_name}.owner where true")


@pytest.fixture(scope="function")
def task_table_name():
    return "pydapper.task"


@pytest.fixture(scope="function")
def owner_table_name():
    return "pydapper.owner"
