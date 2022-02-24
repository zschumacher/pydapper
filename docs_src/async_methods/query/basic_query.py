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


async def main():
    async with connect_async() as commands:
        data = await commands.query_async("select * from task limit 1", model=Task)

    print(data)
    # [Task(id=1, description='Set up a test database', due_date=datetime.date(2021, 12, 31), owner_id=1)]


asyncio.run(main())
