import json
import os
import sys
import uuid
from pathlib import Path

import pytest

from pydapper.bigquery import GoogleBigqueryClientCommands

AUTH_DIR = Path(__file__).parent / "auth"
AUTH_FILE_PATH = AUTH_DIR / "key.json"

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
    AUTH_DIR.mkdir(exist_ok=True)
    with open(AUTH_FILE_PATH, "w") as auth_file:
        json.dump(AUTH, auth_file)


@pytest.fixture(scope="function")
def python_version():
    """Each version needs to have its own bigquery tables since per version tests run at the same time in GHA"""
    version = os.getenv("PYTHON_VERSION") or sys.version[:3]
    return version.replace(".", "")


@pytest.fixture(scope="function")
def func_uuid():
    return uuid.uuid4()


@pytest.fixture(scope="function")
def task_table_name(python_version, func_uuid):
    return f"pydapper.task_{python_version}_{func_uuid.hex}"


@pytest.fixture(scope="function")
def owner_table_name(python_version, func_uuid):
    return f"pydapper.owner_{python_version}_{func_uuid.hex}"


@pytest.fixture(scope="function")
def creds_as_env_var(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(AUTH_FILE_PATH))


@pytest.fixture(scope="function")
def commands() -> GoogleBigqueryClientCommands:
    from google.cloud.bigquery.dbapi import connect

    with GoogleBigqueryClientCommands(connect()) as commands:
        yield commands


@pytest.fixture(scope="function")
def bigquery_setup(setup_sql_dir, creds_as_env_var, python_version, owner_table_name, task_table_name):
    from google.cloud.bigquery.dbapi import connect

    conn = connect()
    cursor = conn.cursor()
    owner = (setup_sql_dir / "bigquery" / "owner.sql").read_text().format(owner_table_name=owner_table_name)
    cursor.execute(owner)
    owner_insert = (
        (setup_sql_dir / "bigquery" / "insert_owner.sql").read_text().format(owner_table_name=owner_table_name)
    )
    cursor.execute(owner_insert)
    task = (setup_sql_dir / "bigquery" / "task.sql").read_text().format(task_table_name=task_table_name)
    cursor.execute(task)
    task_insert = (setup_sql_dir / "bigquery" / "insert_task.sql").read_text().format(task_table_name=task_table_name)
    cursor.execute(task_insert)
