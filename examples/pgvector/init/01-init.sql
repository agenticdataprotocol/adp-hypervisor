-- Customer feedback with vector embeddings for ADP Hypervisor pgvector demo

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE feedback (
    id           SERIAL PRIMARY KEY,
    title        VARCHAR(200) NOT NULL,
    content      TEXT NOT NULL,
    category     VARCHAR(60)  NOT NULL,
    product_name VARCHAR(120) NOT NULL,
    rating       INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    embedding    vector(3)    NOT NULL,
    created_at   TIMESTAMP    NOT NULL DEFAULT now()
);

-- Seed feedback with pre-computed 3-dimensional sentiment embeddings.
-- Positive reviews cluster near [0.9, 0.8, x], neutral near [0.5, 0.5, x],
-- negative near [0.1, 0.2, x].
INSERT INTO feedback (title, content, category, product_name, rating, embedding) VALUES
    ('Excellent wireless mouse',
     'This mouse fits perfectly in my hand and the battery lasts for weeks. The sensor is precise even on glass surfaces.',
     'Electronics', 'Wireless Mouse', 5,
     '[0.92, 0.85, 0.78]'),
    ('Keyboard is too loud',
     'The build quality is solid but the key switches are way too noisy for an open office. My coworkers were not happy.',
     'Electronics', 'Mechanical Keyboard', 2,
     '[0.12, 0.18, 0.25]'),
    ('Great value USB hub',
     'Connects all my peripherals without any dropouts. Compact design and the price is very reasonable for what you get.',
     'Electronics', 'USB-C Hub', 4,
     '[0.88, 0.78, 0.70]'),
    ('Pages too thin',
     'The cover looks nice but the paper is thinner than expected. Ink bleeds through if you use a fountain pen.',
     'Stationery', 'Notebook (A5)', 3,
     '[0.48, 0.52, 0.45]'),
    ('Smooth writing experience',
     'These pens write smoothly and the ink dries quickly. Great for everyday note-taking and the pack is a bargain.',
     'Stationery', 'Ballpoint Pen Pack', 5,
     '[0.91, 0.82, 0.75]'),
    ('Comfortable standing mat',
     'Really reduces fatigue during long work sessions. The cushioning is just right and it stays in place on hardwood floors.',
     'Furniture', 'Standing Desk Mat', 5,
     '[0.93, 0.88, 0.80]'),
    ('Mouse scroll wheel stiff',
     'Tracking is fine but the scroll wheel requires too much force. It gets tiring after a long browsing session.',
     'Electronics', 'Wireless Mouse', 3,
     '[0.50, 0.48, 0.42]'),
    ('Perfect for coding',
     'The tactile feedback on this keyboard is amazing for programming. Once you get used to the sound, you will love it.',
     'Electronics', 'Mechanical Keyboard', 4,
     '[0.85, 0.75, 0.68]'),
    ('Hub runs hot',
     'Works as advertised but it gets noticeably warm when charging a phone and transferring files at the same time.',
     'Electronics', 'USB-C Hub', 3,
     '[0.45, 0.50, 0.40]'),
    ('Beautiful notebook design',
     'The hardcover and elastic closure feel premium. Pages are decent for ballpoint pens and the A5 size is very portable.',
     'Stationery', 'Notebook (A5)', 4,
     '[0.87, 0.76, 0.72]');
