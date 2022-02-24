import asyncio

from pydapper import connect_async


async def main():
    async with connect_async() as commands:
        owner_name = await commands.execute_scalar_async("select name from owner")

    print(owner_name)
    # Zach Schumacher


asyncio.run(main())
