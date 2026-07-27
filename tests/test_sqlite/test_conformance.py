import pytest

from pydapper.testing.adapter_conformance import run_core_sync
from tests.conformance_support import FIRST_PARTY_CONFORMANCE_ENTRIES
from tests.conformance_support import Sqlite3ConformanceHarness

pytestmark = pytest.mark.sqlite


def test_core_sync_conformance(tmp_path):
    entry = FIRST_PARTY_CONFORMANCE_ENTRIES[("sqlite3", "sync")]
    harness = Sqlite3ConformanceHarness(tmp_path)
    assert harness.adapter_name == entry.adapter_name
    assert harness.command_class is entry.command_class
    report = run_core_sync(harness)
    report.raise_for_failures()
    assert report.covers_full_inventory
    # profile planning is declaration-driven: prove the live run actually included it
    assert any(result.profile_id == "transactions" for result in report.results)
