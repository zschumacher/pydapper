from typing import TYPE_CHECKING

from pydapper.commands import Commands

from ..main import register
from ..utils import import_dbapi_module

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult


@register("google")
class GoogleBigqueryClientCommands(Commands):
    @classmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands":
        google_bigquery_client = import_dbapi_module("google.cloud.bigquery.dbapi")
        conn = google_bigquery_client.connect(**connect_kwargs)
        return cls(conn)
