import asyncio
from dataclasses import dataclass

from pydapper import RawRow
from pydapper import connect_async


@dataclass
class Owner:
    id: int
    name: str


@dataclass
class TaskWithOwner:
    id: int
    description: str
    owner: Owner


def to_task_with_owner(row: RawRow) -> TaskWithOwner:
    return TaskWithOwner(
        id=row.values[0],
        description=row.values[1],
        owner=Owner(id=row.values[2], name=row.values[3]),
    )


query = """
select
    t.id,
    t.description,
    o.id,
    o.name
from task t
join owner o on t.owner_id = o.id
limit 1
"""


async def main():
    async with connect_async() as commands:
        data = await commands.query_async(query, mapper=to_task_with_owner)

    print(data)
    # [TaskWithOwner(id=1, description='Set up a test database', owner=Owner(id=1, name='Zach Schumacher'))]


asyncio.run(main())
