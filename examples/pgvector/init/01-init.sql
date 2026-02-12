-- Sample documents schema with vector embeddings for ADP Hypervisor pgvector demo

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id         SERIAL PRIMARY KEY,
    title      VARCHAR(200) NOT NULL,
    content    TEXT NOT NULL,
    category   VARCHAR(60)  NOT NULL,
    embedding  vector(3)    NOT NULL,
    created_at TIMESTAMP    NOT NULL DEFAULT now()
);

-- Seed documents with pre-computed 3-dimensional embeddings.
-- Embeddings are illustrative: similar topics produce closer vectors.
INSERT INTO documents (title, content, category, embedding) VALUES
    ('Introduction to PostgreSQL',
     'PostgreSQL is a powerful open-source relational database system with over 35 years of active development.',
     'database',
     '[0.9, 0.1, 0.05]'),
    ('Getting Started with pgvector',
     'pgvector is an open-source extension for PostgreSQL that adds support for vector similarity search.',
     'database',
     '[0.85, 0.15, 0.1]'),
    ('Understanding Vector Embeddings',
     'Vector embeddings represent data as points in high-dimensional space, enabling similarity comparisons.',
     'machine-learning',
     '[0.6, 0.8, 0.2]'),
    ('Cosine Similarity Explained',
     'Cosine similarity measures the cosine of the angle between two vectors, commonly used in NLP and search.',
     'machine-learning',
     '[0.5, 0.85, 0.15]'),
    ('Building a Semantic Search Engine',
     'Combine embedding models with vector databases to build powerful semantic search applications.',
     'application',
     '[0.7, 0.6, 0.5]'),
    ('RAG Architecture Patterns',
     'Retrieval-Augmented Generation uses vector search to ground LLM responses in factual data.',
     'application',
     '[0.65, 0.55, 0.6]'),
    ('SQL Fundamentals',
     'SQL is the standard language for managing and querying relational databases.',
     'database',
     '[0.8, 0.05, 0.1]'),
    ('Neural Network Basics',
     'Neural networks are computing systems inspired by biological neural networks in the brain.',
     'machine-learning',
     '[0.3, 0.9, 0.3]');
