CREATE TABLE IF NOT EXISTS owner (
    id integer PRIMARY KEY AUTOINCREMENT,
    name text NOT NULL
);

CREATE TABLE IF NOT EXISTS task (
    id          integer PRIMARY KEY AUTOINCREMENT,
    description text NOT NULL DEFAULT '',
    due_date    date NOT NULL,
    owner_id    integer NOT NULL,
    FOREIGN KEY (owner_id) REFERENCES owner(id)
);

INSERT INTO owner (id, name) VALUES
(1, 'Zach Schumacher')
ON CONFLICT DO NOTHING ;

UPDATE sqlite_sequence SET seq = (SELECT MAX(id) FROM owner) WHERE name="owner";

INSERT INTO task (id, description, due_date, owner_id) VALUES
(1, 'Set up a test database', '2021-12-31', 1),
(2, 'Seed the test database', '2021-12-31', 1),
(3, 'Run the test suite', '2022-01-01', 1)
ON CONFLICT DO NOTHING;

UPDATE sqlite_sequence SET seq = (SELECT MAX(id) FROM task) WHERE name="task";
