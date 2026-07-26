"""Pins the BigQuery transaction limits documented in docs/database_support/bigquery.md."""

import pytest

import pydapper
from pydapper.exceptions import UnsupportedFeatureError

pytestmark = pytest.mark.bigquery


def test_transaction_apis_raise_unsupported_feature_error(commands):
    assert commands.supports(pydapper.AdapterCapability.TRANSACTIONS) is False
    with pytest.raises(UnsupportedFeatureError):
        commands.commit()
    with pytest.raises(UnsupportedFeatureError):
        commands.rollback()
    with pytest.raises(UnsupportedFeatureError):
        commands.transaction()


def test_driver_commit_is_a_noop_and_rollback_is_absent(commands):
    assert commands.connection.commit() is None  # documented no-op
    assert not hasattr(commands.connection, "rollback")


def test_dbapi_connection_has_no_context_manager(commands):
    """with pydapper.connect(...) works only because pydapper's proxying is conditional —
    exiting the block performs no driver call at all."""
    connection_type = type(commands.connection)
    assert not hasattr(connection_type, "__enter__")
    assert not hasattr(connection_type, "__exit__")
