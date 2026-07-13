from dataclasses import dataclass
from enum import Enum
from math import inf
from numbers import Real
from typing import Optional


class CommandKind(str, Enum):
    TEXT = "text"
    STORED_PROCEDURE = "stored_procedure"


@dataclass(frozen=True, slots=True)
class CommandOptions:
    timeout: Optional[float] = None
    command_kind: CommandKind = CommandKind.TEXT
    readonly: Optional[bool] = None
    max_rows: Optional[int] = None

    def __post_init__(self) -> None:
        if self.timeout is not None:
            if isinstance(self.timeout, bool) or not isinstance(self.timeout, Real):
                raise TypeError("timeout must be a positive finite number or None")
            try:
                valid_timeout = self.timeout > 0 and -inf < self.timeout < inf
            except (OverflowError, TypeError, ValueError):
                valid_timeout = False
            if not valid_timeout:
                raise ValueError("timeout must be a positive finite number or None")

        if not isinstance(self.command_kind, CommandKind):
            raise TypeError("command_kind must be a CommandKind")

        if self.readonly is not None and not isinstance(self.readonly, bool):
            raise TypeError("readonly must be True, False, or None")

        if self.max_rows is not None:
            if isinstance(self.max_rows, bool) or not isinstance(self.max_rows, int):
                raise TypeError("max_rows must be a positive integer or None")
            if self.max_rows <= 0:
                raise ValueError("max_rows must be a positive integer or None")
