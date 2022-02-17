import datetime
from dataclasses import dataclass

from pydapper import connect


@dataclass
class Owner:
    id: int
    name: str


@dataclass
class Task:
    id: int
    description: str
    due_date: datetime.date
    owner_id: int


with connect() as commands:
    task, owner = commands.query_multiple(
        ("select * from task limit 1", "select * from owner limit 1"), models=(Task, Owner)
    )

print(task)
# [Task(id=1, description='Set up a test database', due_date=datetime.date(2021, 12, 31), owner_id=1)]
print(owner)
# [Owner(id=1, name='Zach Schumacher')]
