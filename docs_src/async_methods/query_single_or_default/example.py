import asyncio
import datetime
from dataclasses import dataclass

from pydapper import connect_async


@dataclass
class Task:
    id: int
    description: str
    due_date: datetime.date
    owner_id: int


sentinel = object()


async def main():
    async with connect_async() as commands:
        task = await commands.query_single_or_default_async(
            "select * from task where id = -1", model=Task, default=sentinel
        )

    if task is sentinel:
        print("No results found!")
    # No results found!


asyncio.run(main())
