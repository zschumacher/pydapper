from uuid import uuid4

import pytest

from pydapper.bigquery import GoogleBigqueryClientCommands
from pydapper.commands import Commands
from pydapper.testing.adapter_conformance import SyncAdapterHarness
from pydapper.testing.adapter_conformance import run_core_sync
from tests.conformance_support import FIRST_PARTY_CONFORMANCE_ENTRIES
from tests.conformance_support import SEED_INSERT
from tests.conformance_support import seed_records

pytestmark = pytest.mark.bigquery

#: Stand-in bound for the canonical dataset's SQL NULL note while seeding; see
#: :meth:`_BigQueryConformanceHarness._seed`.
_NULL_SENTINEL = "__pydapper_null__"


class _BigQueryConformanceHarness(SyncAdapterHarness):
    adapter_name = "google"
    command_class = GoogleBigqueryClientCommands
    # the goccy bigquery-emulator reports unreliable DML rowcounts, so exact-count
    # equality is relaxed; the rowcount cases still run and must return ints
    strict_rowcounts = False
    connect_dsn = "bigquery:////"

    def __init__(self, client):
        self._client = client
        self.connect_kwargs = {"client": client}

    def create_commands(self) -> Commands:
        from google.cloud.bigquery.dbapi import connect

        # a unique fully-qualified table per case keeps emulator state isolated
        self.table_name = f"pydapper.pydapper.conformance_{uuid4().hex}"
        commands = GoogleBigqueryClientCommands(connect(client=self._client))
        commands.execute(f"CREATE TABLE `{self.table_name}` (id INT64, label STRING, score INT64, note STRING)")
        self._seed(commands)
        return commands

    def _seed(self, commands: Commands) -> None:
        """Seed the canonical dataset, working around untyped NULL parameters.

        The BigQuery DBAPI derives each parameter's type from its Python value and
        rejects an untyped ``None``, so the canonical NULL note is bound as a sentinel
        and then replaced with a real SQL NULL. The stored dataset is identical to the
        one every other backend seeds.
        """
        records = seed_records()
        null_ids = [record["id"] for record in records if record["note"] is None]
        for record in records:
            if record["note"] is None:
                record["note"] = _NULL_SENTINEL
        commands.execute(SEED_INSERT.format(table=self.table_name), params=records)
        for row_id in null_ids:
            commands.execute(f"UPDATE {self.table_name} SET note = NULL WHERE id = ?id?", params={"id": row_id})

    def teardown_commands(self, commands: Commands) -> None:
        commands.connection.close()


def test_google_core_sync_conformance(client):
    entry = FIRST_PARTY_CONFORMANCE_ENTRIES[("google", "sync")]
    harness = _BigQueryConformanceHarness(client)
    assert harness.adapter_name == entry.adapter_name
    assert harness.command_class is entry.command_class
    run_core_sync(harness).raise_for_failures()
