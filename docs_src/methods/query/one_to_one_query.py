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
    owner: Owner

    @classmethod
    def from_query_row(cls, id, description, due_date, owner_id, owner_name):
        return cls(id, description, due_date, Owner(owner_id, owner_name))


query = """
select t.id, t.description, t.due_date, o.id as owner_id, o.name as owner_name
  from task t join owner o on t.owner_id = o.id
  limit 1
"""

with connect() as commands:
    data = commands.query(query, model=Task.from_query_row)

print(data)
"""
[
    Task(
        id=1,
        description="Set up a test database",
        due_date=datetime.date(2021, 12, 31),
        owner=Owner(id=1, name="Zach Schumacher"),
    )
]
"""
