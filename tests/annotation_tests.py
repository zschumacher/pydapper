import datetime
from dataclasses import dataclass
from typing import Any
from typing import Dict
from typing import Generator
from typing import List

from typing_extensions import assert_type
from typing_extensions import reveal_type

import pydapper


class Task:
    id: int
    description: str
    due_date: datetime.date
    owner_id: int


def command_annotations():
    with pydapper.connect() as commands:
        assert_type(
            commands.query("select * from task", buffered=True),
            List[Dict[str, Any]],
        )
        assert_type(
            commands.query("select * from task", buffered=False),
            Generator[Dict[str, Any], None, None],
        )
        assert_type(
            commands.query("select * from task", model=Task, buffered=False),
            Generator[Task, None, None],
        )
        assert_type(
            commands.query("select * from task", model=Task, param=None, buffered=True),
            List[Task],
        )
