-- Copyright 2026 Datastrato, Inc.
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
--     http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.

-- Sample product catalog with embeddings for ADP Hypervisor pgvector demo
--
-- Each product has a 3-dimensional embedding vector that encodes
-- a simplified semantic representation: [tech, office, home].
-- Real-world embeddings would come from a model like text-embedding-3-small
-- and have hundreds of dimensions; 3-D keeps the demo easy to reason about.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE items (
    id       SERIAL PRIMARY KEY,
    title    VARCHAR(200) NOT NULL,
    category VARCHAR(60)  NOT NULL,
    price    NUMERIC(10, 2) NOT NULL,
    embedding vector(3) NOT NULL
);

-- Create an IVFFlat index for cosine distance searches
CREATE INDEX ON items USING ivfflat (embedding vector_cosine_ops) WITH (lists = 1);

-- Seed items with 3-D embeddings [tech, office, home]
INSERT INTO items (title, category, price, embedding) VALUES
    ('Wireless Mouse',          'Electronics',  29.99, '[0.9, 0.7, 0.2]'),
    ('Mechanical Keyboard',     'Electronics',  89.99, '[0.9, 0.8, 0.1]'),
    ('USB-C Hub',               'Electronics',  45.00, '[0.95, 0.5, 0.1]'),
    ('Notebook (A5)',           'Stationery',   12.50, '[0.1, 0.9, 0.3]'),
    ('Ballpoint Pen Pack',      'Stationery',    5.99, '[0.05, 0.95, 0.2]'),
    ('Desk Lamp',               'Furniture',    39.99, '[0.2, 0.6, 0.9]'),
    ('Standing Desk Mat',       'Furniture',    49.99, '[0.1, 0.7, 0.8]'),
    ('Monitor Arm',             'Electronics',  59.99, '[0.85, 0.75, 0.15]'),
    ('Ergonomic Chair Cushion', 'Furniture',    34.99, '[0.1, 0.8, 0.7]'),
    ('Laptop Stand',            'Electronics',  27.99, '[0.9, 0.6, 0.3]');
