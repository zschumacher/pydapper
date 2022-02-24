from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def setup_sql_dir():
    return Path(__file__).parent / "databases"


@pytest.fixture(scope="session")
def database_name():
    return f"pydapper"


@pytest.fixture(scope="session")
def server():
    return "localhost"
