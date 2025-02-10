from typing import TYPE_CHECKING

from ..commands import BaseSqlParamHandler
from ..commands import Commands
from ..main import register
from ..main import register_async
from ..utils import import_dbapi_module

if TYPE_CHECKING:
    from ..dsn_parser import PydapperParseResult


def apply_parameters(operation, parameters):
    from pinotdb.db import escape_operation
    from pinotdb.db import escape_parameter

    if isinstance(parameters, dict):
        escaped_parameters = {key: escape_parameter(value) for key, value in parameters.items()}
    else:
        escaped_parameters = tuple(escape_parameter(value) for value in parameters)

    escaped_operation = escape_operation(operation).replace("%%s", "%s")

    s = escaped_operation % escaped_parameters
    return s


def patch_apply_parameters(f):
    import pinotdb

    pinotdb.db.apply_parameters = f


@register("pinotdb")
class PinotDbCommands(Commands):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        patch_apply_parameters(apply_parameters)

    @classmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands":
        pinotdb = import_dbapi_module("pinotdb")
        scheme = connect_kwargs.get("scheme", "http")
        if scheme not in {"http", "https"}:
            raise ValueError("scheme must be passed as a connect kwarg and be set to one of 'http' or 'https'")

        if scheme == "https" and parsed_dsn.port is None:
            raise ValueError("When connecting via https, must specify a port")

        return cls(
            pinotdb.connect(
                host=parsed_dsn.host,
                port=parsed_dsn.port or 8099,
                user=parsed_dsn.user,
                password=parsed_dsn.password,
                database=parsed_dsn.database,
                scheme=scheme,
                **connect_kwargs,
            )
        )
