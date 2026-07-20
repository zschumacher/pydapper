from uuid import uuid4

import pytest

from pydapper.bigquery import GoogleBigqueryClientCommands
from pydapper.commands import Commands
from pydapper.testing.adapter_conformance import SyncAdapterHarness
from pydapper.testing.adapter_conformance import run_core_sync
from tests.conformance_support import FIRST_PARTY_CONFORMANCE_ENTRIES
from tests.conformance_support import seed_through_adapter

pytestmark = pytest.mark.bigquery


class _BigQueryConformanceHarness(SyncAdapterHarness):
    adapter_name = "google"
    command_class = GoogleBigqueryClientCommands
    # the goccy bigquery-emulator reports unreliable DML rowcounts, so exact-count
    # equality is relaxed; the rowcount cases still run and must return ints
    strict_rowcounts = False
    connect_dsn = "bigquery:////"

    def __init__(self, client):
        self._client = client
        self.connect_kwargs = {"client": client}  # type: ignore[misc]

    def create_commands(self) -> Commands:
        from google.cloud.bigquery.dbapi import connect

        # a unique fully-qualified table per case keeps emulator state isolated
        self.table_name = f"pydapper.pydapper.conformance_{uuid4().hex}"  # type: ignore[misc]
        commands = GoogleBigqueryClientCommands(connect(client=self._client))
        commands.execute(f"CREATE TABLE `{self.table_name}` (id INT64, label STRING, score INT64, note STRING)")
        seed_through_adapter(commands, self.table_name)
        return commands

    def teardown_commands(self, commands: Commands) -> None:
        commands.connection.close()


def test_google_core_sync_conformance(client):
    entry = FIRST_PARTY_CONFORMANCE_ENTRIES[("google", "sync")]
    harness = _BigQueryConformanceHarness(client)
    assert harness.adapter_name == entry.adapter_name
    assert harness.command_class is entry.command_class
    run_core_sync(harness).raise_for_failures()
