import asyncio

import pydapper


async def main():
    async with pydapper.connect_async("postgresql+aiopg://pydapper:pydapper@localhost/pydapper") as commands:
        print(type(commands))
        # <class 'pydapper.postgresql.aiopg.AiopgCommands'>

        print(type(commands.connection))
        # <class 'aiopg.connection.Connection'>

        async with commands.cursor() as raw_cursor:
            print(type(raw_cursor))
            # <class 'aiopg.connection.Cursor'>


asyncio.run(main())
