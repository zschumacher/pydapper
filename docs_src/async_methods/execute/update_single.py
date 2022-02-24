import asyncio

from pydapper import connect_async


async def main():
    async with connect_async() as commands:
        rowcount = await commands.execute_async(
            "update task set description = ?desc? where id = ?id?", param={"desc": "A single update!", "id": 1}
        )

    print(rowcount)
    # 1


asyncio.run(main())
