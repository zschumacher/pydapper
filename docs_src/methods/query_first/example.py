import datetime
from dataclasses import dataclass

from pydapper import connect


@dataclass
class Task:
    id: int
    description: str
    due_date: datetime.date
    owner_id: int


with connect() as commands:
    task = commands.query_first("select * from task", model=Task)

print(task)
# Task(id=1, description='Set up a test database', due_date=datetime.date(2021, 12, 31), owner_id=1)
