import os
import sys
import uuid

import pytest

from pydapper.bigquery import GoogleBigqueryClientCommands


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
    return f"pydapper.pydapper.task_{python_version}_{func_uuid.hex}"


@pytest.fixture(scope="function")
def owner_table_name(python_version, func_uuid):
    return f"pydapper.pydapper.owner_{python_version}_{func_uuid.hex}"


@pytest.fixture
def client(monkeypatch):
    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    from google.cloud.bigquery import Client

    options = ClientOptions(api_endpoint="http://localhost:9050")

    client = Client(client_options=options, credentials=AnonymousCredentials(), project="pydapper")
    yield client


@pytest.fixture(scope="function")
def commands(client) -> GoogleBigqueryClientCommands:
    from google.cloud.bigquery.dbapi import connect

    with GoogleBigqueryClientCommands(connect(client=client)) as commands:
        yield commands


@pytest.fixture(scope="function")
def bigquery_setup(client, setup_sql_dir, python_version, owner_table_name, task_table_name):
    from google.cloud.bigquery.dbapi import connect

    conn = connect(client=client)

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
