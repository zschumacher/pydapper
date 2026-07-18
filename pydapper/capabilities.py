from enum import Enum
from enum import unique


@unique
class AdapterCapability(str, Enum):
    """Optional behaviors a command class may declare it implements."""

    TRANSACTIONS = "transactions"
    LIST_EXPANSION = "list_expansion"
    RESULT_GRIDS = "result_grids"
    RAW_READER = "raw_reader"
    COMMAND_TIMEOUT = "command_timeout"
    STORED_PROCEDURES = "stored_procedures"
    OUTPUT_PARAMETERS = "output_parameters"
    SCHEMA_INSPECTION = "schema_inspection"
    SQL_VALIDATION = "sql_validation"
    EXPLAIN = "explain"
    READONLY = "readonly"
    MAX_ROWS = "max_rows"
