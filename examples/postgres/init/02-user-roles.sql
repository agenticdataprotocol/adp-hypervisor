-- Gravitino release process: user-role assignments

CREATE TABLE user_roles (
    id         SERIAL PRIMARY KEY,
    username   VARCHAR(255) NOT NULL,
    role       VARCHAR(50)  NOT NULL CHECK (role IN ('release_manager', 'pmc', 'committer', 'viewer')),
    granted_at TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- Seed user_roles
INSERT INTO user_roles (username, role) VALUES
    ('alice',   'release_manager'),
    ('bob',     'pmc'),
    ('charlie', 'committer'),
    ('dave',    'committer'),
    ('eve',     'viewer'),
    ('frank',   'viewer');
