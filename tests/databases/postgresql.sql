CREATE TABLE IF NOT EXISTS owner (
    id serial,
    name text NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS task (
    id          serial,
    description text NOT NULL DEFAULT '',
    due_date    date NOT NULL,
    owner_id    integer NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (owner_id) REFERENCES owner(id)
);

INSERT INTO owner (id, name) VALUES
(1, 'Zach Schumacher')
ON CONFLICT DO NOTHING ;

SELECT setval(pg_get_serial_sequence('owner', 'id'), coalesce(max(id), 0)+1 , false) FROM owner;

INSERT INTO task (id, description, due_date, owner_id) VALUES
(1, 'Set up a test database', '2021-12-31', 1),
(2, 'Seed the test database', '2021-12-31', 1),
(3, 'Run the test suite', '2022-01-01', 1)
ON CONFLICT DO NOTHING;

SELECT setval(pg_get_serial_sequence('task', 'id'), coalesce(max(id), 0)+1 , false) FROM task;