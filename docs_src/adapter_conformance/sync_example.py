"""A complete third-party sync-only adapter running the reusable conformance suite.

The "acmedb" driver below is stdlib sqlite3 wearing a third-party hat: the point is
the shape of the harness, not the database. No pytest is required.
"""

import sqlite3
import tempfile

import pydapper
from pydapper.commands import BaseSqlParamHandler
from pydapper.commands import Commands
from pydapper.testing.adapter_conformance import SyncAdapterHarness
from pydapper.testing.adapter_conformance import run_core_sync
from pydapper.testing.adapter_conformance import seed_rows


class AcmeDbCommands(Commands):
    class SqlParamHandler(BaseSqlParamHandler):
        def get_param_placeholder(self, param_name: str) -> str:
            return "?"

    @classmethod
    def connect(cls, parsed_dsn, **connect_kwargs) -> "AcmeDbCommands":
        return cls(sqlite3.connect(parsed_dsn.database, **connect_kwargs))


pydapper.register_adapter(
    "acmedb",
    commands=AcmeDbCommands,
    using_connection_predicate=lambda connection: isinstance(connection, sqlite3.Connection),
)


class AcmeDbConformanceHarness(SyncAdapterHarness):
    adapter_name = "acmedb"
    command_class = AcmeDbCommands

    def __init__(self) -> None:
        # no harness field is a ClassVar, so configuration a real harness only learns at
        # runtime -- a container's host and port, a temp directory -- is assigned on self
        workdir = tempfile.mkdtemp()
        # four slashes make the sqlite path absolute; the +acmedb suffix selects this adapter
        self.connect_dsn = f"sqlite+acmedb:///{workdir}/example.db"

    def create_commands(self) -> Commands:
        # a fresh, isolated database and dataset for every conformance case
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE pydapper_conformance (id INTEGER PRIMARY KEY, label TEXT, score INTEGER, note TEXT)"
        )
        connection.executemany(
            "INSERT INTO pydapper_conformance (id, label, score, note) VALUES (?, ?, ?, ?)",
            seed_rows(self.supports_empty_strings),
        )
        connection.commit()
        return AcmeDbCommands(connection)

    def teardown_commands(self, commands: Commands) -> None:
        commands.connection.close()


report = run_core_sync(AcmeDbConformanceHarness())
for failure in report.failures:
    print(f"{failure.profile_id}/{failure.case_id}: {failure.message}")
print(f"{report.profile_id} for {report.adapter_name!r}: {len(report.results)} cases, passed={report.passed}")
report.raise_for_failures()
# claiming conformance takes both: every case passed *and* every planned case ran
assert report.passed and report.covers_full_inventory
# core-sync for 'acmedb': 58 cases, passed=True
