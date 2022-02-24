import asyncio
import datetime

from pydapper import connect_async


async def main():
    async with connect_async() as commands:
        rowcount = await commands.execute_async(
            "insert into task (description, due_date, owner_id) values (?description?, ?due_date?, ?owner_id?)",
            param={"description": "An insert example", "due_date": datetime.date.today(), "owner_id": 1},
        )

    print(rowcount)
    # 1


asyncio.run(main())
