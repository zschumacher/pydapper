import asyncio

from pydapper import connect_async


async def main():
    async with connect_async() as commands:
        rowcount = await commands.execute_async("delete from task where id = ?id?", param={"id": 1})

    print(rowcount)
    # 1


asyncio.run(main())
