# MongoDB Integration Test Fixtures

This directory contains ADP manifest files for the MongoDB integration tests.

## Files

### physical.yaml

Defines the MongoDB backend configuration:
- **Backend ID**: `test_mongodb`
- **Type**: NOSQL (MongoDB)
- **Connection**: `mongodb://test:test@localhost:27017`
- **Database**: `test`

This configuration matches the MongoDB container setup in the integration tests.

### semantic.yaml

Defines the ADP resource mapping for the `users` collection:
- **Resource ID**: `com.test:users`
- **Intent Classes**: LOOKUP, QUERY
- **Backend**: References `test_mongodb` from physical.yaml
- **Source**: `users` collection

#### Schema

The `users` collection contains three fields:

| Field | Type | Description | Sample Values |
|-------|------|-------------|---------------|
| `_id` | STRING | MongoDB ObjectId | Auto-generated |
| `name` | STRING | User's name | Alice, Bob, Charlie |
| `age` | INTEGER | User's age | 25, 30, 35 |

## Test Data

The integration tests seed the `users` collection with:

```json
[
  {"name": "Alice", "age": 30},
  {"name": "Bob", "age": 25},
  {"name": "Charlie", "age": 35}
]
```

## Usage

These manifests demonstrate:

1. **Physical Layer**: How to configure a MongoDB backend with connection details
2. **Semantic Layer**: How to map a MongoDB collection to an ADP resource
3. **Schema Definition**: Explicit field definitions with types, descriptions, and samples
4. **Metadata**: Additional hints and cardinality information for fields

## Auto-Discovery Alternative

The semantic manifest could be simplified to use auto-discovery:

```yaml
version: "1.0.0"
defaultDomain: "com.test"

resources:
  - resourceId: "com.test:users"
    intentClasses: ["LOOKUP", "QUERY"]
    version: 1
    description: "Users collection"
    backendId: "test_mongodb"
    sources:
      - source: "users"
        # fields omitted - will be auto-discovered via document sampling
```

With auto-discovery, the MongoDB backend's `get_schema()` method would sample documents and infer field types automatically.
