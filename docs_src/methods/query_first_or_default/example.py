import datetime
from dataclasses import dataclass

from pydapper import connect


@dataclass
class Task:
    id: int
    description: str
    due_date: datetime.date
    owner_id: int


sentinel = object()


with connect("postgresql://pydapper:pydapper@localhost/pydapper") as commands:
    task = commands.query_first_or_default("select * from task where id = -1", model=Task, default=sentinel)

if task is sentinel:
    print("No results found!")
# No results found!
