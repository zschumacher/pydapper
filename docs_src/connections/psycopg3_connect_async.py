import asyncio

import pydapper


async def main():
    async with pydapper.connect_async("postgresql+psycopg://pydapper:pydapper@localhost/pydapper") as commands:
        print(type(commands))
        # <class 'pydapper.postgresql.psycopg3.Psycopg3CommandsAsync'>

        print(type(commands.connection))
        # <class 'psycopg.AsyncConnection'>

        async with commands.cursor() as raw_cursor:
            print(type(raw_cursor))
            # <class 'psycopg.AsyncCursor'>


asyncio.run(main())
