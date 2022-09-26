import pydapper
from dataclasses import dataclass

@dataclass
class Note:
    Title: str
    Body: str

example_note = Note("My test note", "Stuff")

with pydapper.connect("mssql://sa:pydapper!PYDAPPER@localhost:1434/pydapper") as commands:
    commands.execute("INSERT INTO [dbo].[Notes] (Title, Body) VALUES (?Title?, ?Body?);",
        param=example_note.__dict__)

    commands.connection.commit()
