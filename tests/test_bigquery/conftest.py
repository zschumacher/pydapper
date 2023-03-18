from pathlib import Path

import pytest
from google.cloud.bigquery.dbapi import connect

from pydapper.bigquery import GoogleBigqueryClientCommands

AUTH_FILE_PATH = Path(__file__).parent / Path("auth") / "key.json"

import json
import os
import pathlib

AUTH = {
    "type": "service_account",
    "project_id": "pydapper",
    "private_key_id": "08c8a357ab549f6d34f1705512bdb00c2efaf68f",
    "private_key": os.getenv("GOOGLE_PRIVATE_KEY", "DUMMY").replace("\\n", "\n"),
    "client_email": "pydapper@pydapper.iam.gserviceaccount.com",
    "client_id": "105936813038399443987",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/pydapper%40pydapper.iam.gserviceaccount.com",
}


@pytest.fixture(autouse=True, scope="session")
def write_auth_file():
    with open(AUTH_FILE_PATH, "w") as auth_file:
        json.dump(AUTH, auth_file)


@pytest.fixture(scope="function")
def creds_as_env_var(monkeypatch):
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
