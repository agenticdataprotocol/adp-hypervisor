---
title: "ADP SQL Examples"
---

# SQL Examples

Use these examples **only after** `adp_describe()` confirms a SQL resource.

## 1. QUERY — Orders by status

Filter shipped orders from `pg_demo:orders`:

```python
adp_execute(
  resource_id="pg_demo:orders",
  intent={
    "intentClass": "QUERY",
    "predicates": {"op": "AND", "predicates": [{"fieldId": "status", "op": "EQ", "value": "shipped"}]},
    "projections": ["id", "customer_id", "total", "status"],
    "limit": 10
  }
)
```

## 2. LOOKUP — Customer by ID

Look up a single customer by primary key from `pg_demo:customers`:

```python
adp_execute(
  resource_id="pg_demo:customers",
  intent={
    "intentClass": "LOOKUP",
    "key": {"fieldId": "id", "op": "EQ", "value": 1},
    "projections": ["id", "name", "email", "city", "created_at"]
  }
)
```

## 3. QUERY — Feedback by product name

Find feedback for a specific product from `pgvector_demo:feedback`:

```python
adp_execute(
  resource_id="pgvector_demo:feedback",
  intent={
    "intentClass": "QUERY",
    "predicates": {"op": "AND", "predicates": [{"fieldId": "product_name", "op": "EQ", "value": "Wireless Mouse"}]},
    "projections": ["title", "content", "rating"],
    "limit": 10
  }
)
```

## 4. QUERY — Vector similarity search

Search feedback by semantic similarity on the `embedding` field:

```python
adp_execute(
  resource_id="pgvector_demo:feedback",
  intent={
    "intentClass": "QUERY",
    "predicates": {"op": "AND", "predicates": [{"fieldId": "embedding", "op": "SIMILAR", "value": "comfortable wireless mouse"}]},
    "projections": ["title", "content", "rating", "product_name"],
    "limit": 5
  }
)
```

## 5. QUERY — MongoDB orders by customer

Filter orders by customer name from `mongo_demo:orders`:

```python
adp_execute(
  resource_id="mongo_demo:orders",
  intent={
    "intentClass": "QUERY",
    "predicates": {"op": "AND", "predicates": [{"fieldId": "customer_name", "op": "EQ", "value": "Alice Johnson"}]},
    "projections": ["_id", "product_name", "quantity", "total", "status"],
    "limit": 10
  }
)
```
