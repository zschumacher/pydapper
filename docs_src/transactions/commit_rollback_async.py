import asyncio
import datetime

from pydapper import connect_async


async def main():
    async with connect_async() as commands:
        await commands.execute_async(
            "insert into task (description, due_date, owner_id) values (?description?, ?due_date?, ?owner_id?)",
            params={"description": "A rollback example", "due_date": datetime.date.today(), "owner_id": 1},
        )
        # discard the uncommitted insert
        await commands.rollback()

        await commands.execute_async(
            "insert into task (description, due_date, owner_id) values (?description?, ?due_date?, ?owner_id?)",
            params={"description": "A commit example", "due_date": datetime.date.today(), "owner_id": 1},
        )
        # make the insert durable
        await commands.commit()


asyncio.run(main())
