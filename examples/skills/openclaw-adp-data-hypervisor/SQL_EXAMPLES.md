---
title: "ADP SQL Examples (OpenClaw)"
---

# SQL Examples

Use these examples **only after** `mcp_adp-mcp_adp_describe()` confirms a SQL resource.

## 1. QUERY — Orders by status

Filter shipped orders from `demo:orders`:

```python
mcp_adp-mcp_adp_execute(
  intent={
    "intentClass": "QUERY",
    "resourceId": "demo:orders",
    "predicates": {"op": "AND", "predicates": [{"fieldId": "status", "op": "EQ", "value": "shipped"}]},
    "projections": ["id", "customer_id", "total", "status"],
    "limit": 10
  }
)
```

## 2. LOOKUP — Customer by ID

Look up a single customer by primary key from `demo:customers`:

```python
mcp_adp-mcp_adp_execute(
  intent={
    "intentClass": "LOOKUP",
    "resourceId": "demo:customers",
    "key": {"fieldId": "id", "op": "EQ", "value": 1},
    "projections": ["id", "name", "email", "city", "created_at"]
  }
)
```

## 3. QUERY — Products by category

Find products in a specific category from `demo:products`:

```python
mcp_adp-mcp_adp_execute(
  intent={
    "intentClass": "QUERY",
    "resourceId": "demo:products",
    "predicates": {"op": "AND", "predicates": [{"fieldId": "category", "op": "EQ", "value": "Electronics"}]},
    "projections": ["id", "name", "category", "price", "in_stock"],
    "limit": 10
  }
)
```

## 4. QUERY — Recent orders with sorting

Get the 5 most recent orders, sorted by date descending:

```python
mcp_adp-mcp_adp_execute(
  intent={
    "intentClass": "QUERY",
    "resourceId": "demo:orders",
    "predicates": {"op": "AND", "predicates": [{"fieldId": "total", "op": "GT", "value": 0}]},
    "projections": ["id", "customer_id", "product_id", "total", "status", "ordered_at"],
    "orderBy": [{"fieldId": "ordered_at", "direction": "DESC"}],
    "limit": 5
  }
)
```

## 5. QUERY — Customers by city

Find all customers in a given city from `demo:customers`:

```python
mcp_adp-mcp_adp_execute(
  intent={
    "intentClass": "QUERY",
    "resourceId": "demo:customers",
    "predicates": {"fieldId": "city", "op": "EQ", "value": "Seattle"},
    "projections": ["id", "name", "email", "city"]
  }
)
```
