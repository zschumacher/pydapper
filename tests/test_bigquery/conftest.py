import uuid

import pytest

from pydapper.bigquery import GoogleBigqueryClientCommands
from tests.test_bigquery.testcontainer import BigQueryEmulatorContainer


@pytest.fixture(scope="session")
def bigquery_container():
    with BigQueryEmulatorContainer(
        project="pydapper",
        dataset="pydapper",
    ) as bigquery:
        yield bigquery


@pytest.fixture(scope="session")
def http_port(bigquery_container):
    return bigquery_container.get_exposed_port(bigquery_container.port)


@pytest.fixture(scope="function")
def func_uuid():
    return uuid.uuid4()


@pytest.fixture(scope="function")
def task_table_name(func_uuid):
    return f"pydapper.pydapper.task_{func_uuid.hex}"


@pytest.fixture(scope="function")
def owner_table_name(func_uuid):
    return f"pydapper.pydapper.owner_{func_uuid.hex}"


@pytest.fixture
def client(monkeypatch, http_port, server):
    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    from google.cloud.bigquery import Client

    options = ClientOptions(api_endpoint=f"http://{server}:{http_port}")

    client = Client(client_options=options, credentials=AnonymousCredentials(), project="pydapper")
    yield client


@pytest.fixture(scope="function")
def commands(client) -> GoogleBigqueryClientCommands:
    from google.cloud.bigquery.dbapi import connect

    with GoogleBigqueryClientCommands(connect(client=client)) as commands:
        yield commands


@pytest.fixture(scope="function")
def bigquery_setup(client, setup_sql_dir, owner_table_name, task_table_name):
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
