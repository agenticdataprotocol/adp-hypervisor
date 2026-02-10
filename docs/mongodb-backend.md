# MongoDB Backend Implementation

This document describes the MongoDB backend implementation for the ADP Hypervisor.

## Overview

The MongoDB backend enables ADP to interact with MongoDB databases through a unified intent-based interface. It follows the same architectural patterns as the PostgreSQL backend, with a layered design that separates query translation from connection management.

## Architecture

### Layered Design

```
Backend (ABC)
    ↓
NOSQLBackend (Template Method)
    ↓
MongoDBBackend (Concrete Implementation)
```

- **Backend**: Abstract base class defining the interface for all backends
- **NOSQLBackend**: Template method implementation for NoSQL query translation
- **MongoDBBackend**: MongoDB-specific connection management and schema discovery

## Features

### Supported Operations

- ✅ **LOOKUP**: Retrieve a single document by unique field
- ✅ **QUERY**: Retrieve multiple documents with filtering, sorting, and pagination
- ❌ **INGEST**: Not yet implemented (returns NotImplementedError)
- ❌ **REVISE**: Not yet implemented (returns NotImplementedError)

### Predicate Operators

| ADP Operator | MongoDB Operator | Description |
|--------------|------------------|-------------|
| EQ           | $eq              | Equal |
| NEQ          | $ne              | Not equal |
| GT           | $gt              | Greater than |
| LT           | $lt              | Less than |
| GTE          | $gte             | Greater than or equal |
| LTE          | $lte             | Less than or equal |
| IN           | $in              | Value in list |
| CONTAINS     | $regex           | Substring match (case-insensitive) |
| LIKE         | $regex           | Pattern match (SQL-style) |
| ILIKE        | $regex + $options | Case-insensitive pattern match |

### Logic Operators

- **AND**: `$and` operator
- **OR**: `$or` operator
- **NOT**: `$nor` operator

## Configuration

### Physical Manifest

```yaml
backends:
  - id: "my_mongodb"
    type: "NOSQL"
    config:
      type: "NOSQL"
      provider: "MONGODB"
      uri: "mongodb://localhost:27017"
      database: "myapp"
    credentials:
      type: "env"
      key: "MONGO_PASSWORD"
```

### Configuration Fields

- **uri**: MongoDB connection string (required)
- **database**: Database name (required)
- **provider**: Must be "MONGODB" (optional, for documentation)

## Schema Discovery

The MongoDB backend infers schema from document sampling:

1. Samples up to 100 documents using `$sample` aggregation
2. Analyzes field types across all samples
3. Maps Python/BSON types to ADP FieldTypes
4. Provides sample values for each field

### Type Mapping

| Python/BSON Type | ADP FieldType |
|------------------|---------------|
| str              | STRING        |
| int              | INTEGER       |
| float            | FLOAT         |
| bool             | BOOLEAN       |
| datetime         | TIMESTAMP     |
| date             | DATE          |
| list             | JSON          |
| dict             | JSON          |
| bytes            | BLOB          |
| ObjectId         | STRING        |

## Special Features

### ObjectId Handling

- MongoDB's `_id` field (ObjectId) is automatically converted to string in results
- String values for `_id` in queries are automatically converted to ObjectId
- Nested ObjectIds in documents are also converted

### Nested Documents

- Supports dot notation for nested field access (e.g., `"address.city"`)
- Nested documents are returned as JSON objects
- Recursive normalization of ObjectIds in nested structures

### Projections

- Field projections are translated to MongoDB projection syntax
- `projections: ["name", "age"]` → `{"name": 1, "age": 1}`

### Sorting

- ADP sort directions are translated to MongoDB sort values
- `"ASC"` → `1`, `"DESC"` → `-1`

## Usage Example

```python
from adp_hypervisor.manifest.physical import BackendDefinition, BackendType, NOSQLBackendConfig
from backends.nosql.mongodb import MongoDBBackend

# Create backend definition
config = NOSQLBackendConfig(type="NOSQL")
config.model_extra = {
    "uri": "mongodb://localhost:27017",
    "database": "myapp",
    "provider": "MONGODB"
}

definition = BackendDefinition(
    id="my_mongo",
    type=BackendType.NOSQL,
    config=config
)

# Create and connect backend
backend = MongoDBBackend(definition=definition)
await backend.connect()

# Discover schema
fields = await backend.get_schema("users")

# Execute LOOKUP intent
from adp_hypervisor.protocol.types import LookupIntent, IdentityPredicate

intent = LookupIntent(
    key=IdentityPredicate(field_id="name", value="Alice")
)
result = await backend.execute("users", intent)

# Execute QUERY intent
from adp_hypervisor.protocol.types import QueryIntent, PredicateGroup, Predicate, PredicateOperator

intent = QueryIntent(
    predicates=PredicateGroup(
        op="AND",
        predicates=[
            Predicate(field_id="age", op=PredicateOperator.GT, value=25)
        ]
    ),
    limit=10
)
result = await backend.execute("users", intent)

# Disconnect
await backend.disconnect()
```

## Testing

### Unit Tests

Run unit tests with mocked MongoDB client:

```bash
uv run python -m unittest tests.unit.backends.nosql.test_mongodb -v
```

### Integration Tests

Run integration tests with real MongoDB instance (requires Docker):

```bash
uv run pytest tests/integration/test_backend_mongodb.py -v
```

## Dependencies

- **motor**: Async MongoDB driver (>=3.3, <4.0)
- **pymongo**: MongoDB driver (>=4.6, <5.0)
- **testcontainers[mongodb]**: For integration tests (dev dependency)

## Limitations

1. **Write Operations**: INGEST and REVISE intents are not yet implemented
2. **Transactions**: No transaction support yet
3. **Vector Search**: SIMILAR operator not implemented (requires MongoDB Atlas or custom implementation)
4. **Schema Validation**: No strict schema enforcement (MongoDB is schemaless)
5. **Aggregation**: Complex aggregation pipelines not supported through standard intents

## Future Enhancements

- [ ] Implement INGEST intent (insert_many)
- [ ] Implement REVISE intent (update_many)
- [ ] Add transaction support for write operations
- [ ] Implement vector search for SIMILAR operator
- [ ] Add cursor-based pagination for large result sets
- [ ] Support for MongoDB aggregation pipelines
- [ ] Schema validation options
- [ ] Connection pooling configuration
- [ ] Retry logic for transient failures

## References

- [Motor Documentation](https://motor.readthedocs.io/)
- [MongoDB Query Language Reference](https://www.mongodb.com/docs/manual/reference/mql/#std-label-mql-reference)
- [ADP Protocol Specification](../schema/adp-protocol-2026-01-20.json)
