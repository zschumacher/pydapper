from typing import TYPE_CHECKING
from typing import ClassVar

from pydapper.capabilities import AdapterCapability
from pydapper.commands import BaseSqlParamHandler
from pydapper.commands import Commands

from ..utils import import_dbapi_module

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult


class OracledbCommands(Commands):
    capabilities: ClassVar[frozenset[AdapterCapability]] = frozenset({AdapterCapability.TRANSACTIONS})

    class SqlParamHandler(BaseSqlParamHandler):
        def get_param_placeholder(self, param_name) -> str:
            return f":{param_name}"

    @classmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands":
        oracledb = import_dbapi_module("oracledb")
        conn = oracledb.connect(
            user=parsed_dsn.user,
            password=parsed_dsn.password,
            dsn=f"{parsed_dsn.hostloc}/{parsed_dsn.database}",
            **connect_kwargs,
        )
        return cls(conn)
