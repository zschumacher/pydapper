IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='owner' and xtype='U')
    CREATE TABLE dbo.owner (
        id INT PRIMARY KEY IDENTITY (1, 1),
        name VARCHAR (255) NOT NULL
    );

IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='task' and xtype='U')
    CREATE TABLE dbo.task (
        id INT PRIMARY KEY IDENTITY (1, 1),
        description VARCHAR (255) NOT NULL,
        due_date DATE NOT NULL,
        owner_id INT,
        FOREIGN KEY (owner_id) REFERENCES dbo.owner (id)
);

DELETE FROM dbo.task;

DELETE FROM dbo.owner;

SET IDENTITY_INSERT dbo.owner ON;
INSERT INTO dbo.owner(id, name) VALUES(1, 'Zach Schumacher');
SET IDENTITY_INSERT dbo.owner OFF;

SET IDENTITY_INSERT dbo.task ON;
INSERT INTO dbo.task (id, description, due_date, owner_id) VALUES
(1, 'Set up a test database', '2021-12-31', 1),
(2, 'Seed the test database', '2021-12-31', 1),
(3, 'Run the test suite', '2022-01-01', 1);
SET IDENTITY_INSERT dbo.task OFF;
