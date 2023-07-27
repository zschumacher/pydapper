import asyncio

import pydapper


async def main():
    async with pydapper.connect_async("mssql+aioodbc://sa:pydapper@localhost/pydapper") as commands:
        print(type(commands))
        # <class 'pydapper.odbc.aioodbc.AioodbcCommands'>

        print(type(commands.connection))
        # <class 'aioodbc.connection.Connection'>

        async with commands.cursor() as raw_cursor:
            print(type(raw_cursor))
            # <class 'aioodbc.cursor.Cursor'>


asyncio.run(main())
