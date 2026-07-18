from typing import TYPE_CHECKING
from typing import ClassVar

from pydapper.capabilities import AdapterCapability
from pydapper.commands import Commands

from ..utils import import_dbapi_module

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult


class GoogleBigqueryClientCommands(Commands):
    capabilities: ClassVar[frozenset[AdapterCapability]] = frozenset()

    @classmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands":
        google_bigquery_client = import_dbapi_module("google.cloud.bigquery.dbapi")
        conn = google_bigquery_client.connect(**connect_kwargs)
        return cls(conn)
