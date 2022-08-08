import asyncio
import typing
from dataclasses import dataclass

from pydapper import connect_async


@dataclass
class Owner:
    id: int
    name: str
    tasks: typing.List["Task"]


@dataclass
class Task:
    id: int
    description: str


query = """
select task.id as task_id,
       owner.id as owner_id,
       owner.name as owner_name,
       task.description as description
  from owner
  join task on owner.id = task.owner_id 
"""


async def main():
    async with connect_async() as commands:
        owners = dict()
        async for record in await commands.query_async(query, buffered=False):
            if (owner_id := record["owner_id"]) not in owners:
                owners[owner_id] = Owner(id=owner_id, name=record["owner_name"], tasks=list())
            owners[owner_id].tasks.append(
                Task(id=record["task_id"], description=record["description"])
            )

    print(list(owners.values()))
    """
    [
        Owner(
            id=1,
            name='Zach Schumacher',
            tasks=[
                Task(
                    id=1,
                    description='Set up a test database',
                ),
                Task(
                    id=2,
                    description='Seed the test database',
                ),
                Task(
                    id=3,
                    description='Run the test suite',
                ),
            ],
        ),
    ]
    """


asyncio.run(main())
