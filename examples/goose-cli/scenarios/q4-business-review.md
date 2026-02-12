# Q4 2025 Business Review

## Overview

This scenario walks through a quarterly business review performed by a data
analyst using **Goose CLI** with the **ADP Data Hypervisor** skill. The analyst
needs to pull together sales figures, product information, customer feedback, and
invoice records — all spread across four heterogeneous backends — into a single
coherent report.

The ADP Data Hypervisor abstracts away the differences between PostgreSQL,
MongoDB, pgvector, and POSIX filesystems, letting the analyst work in plain
English while the system translates each request into the correct backend
operations.

---

## Steps

### Step 1: Discover Available Data Sources

**Context:** The analyst begins by surveying what data is available across the
company's systems. This establishes the landscape before diving into specific
queries.

**Prompt:**

> Show me all the data sources available in the ADP system

**Expected Outcome:** The system returns 9 resources across 4 backends:

| Backend        | Resources                          |
|:---------------|:-----------------------------------|
| `pg_demo`      | customers, products, orders        |
| `pgvector_demo`| feedback                           |
| `mongo_demo`   | customers, products, orders        |
| `posix_demo`   | products, invoices                 |

This confirms the analyst has access to structured transactional data (PostgreSQL),
denormalized document data (MongoDB), semantic search data (pgvector), and
unstructured files (POSIX).

---

### Step 2: Analyze Sales Performance (PostgreSQL)

**Context:** The analyst checks Q4 order trends to understand which orders were
shipped or delivered versus those still pending or cancelled.

**Prompt:**

> Query the PostgreSQL orders to show me all shipped orders, sorted by date,
> with the order ID, customer, total amount, and status

**Expected Outcome:** The system queries `pg_demo:orders` with a QUERY intent
filtering by `status = "shipped"`, sorted by `ordered_at DESC`, projecting
`order_id`, `customer_id`, `total`, and `status`. The result shows all shipped
orders with their details, giving the analyst a clear picture of fulfilled sales.

---

### Step 3: Identify Top Products (PostgreSQL)

**Context:** The analyst needs the full product catalog to identify which items
are available and how they are priced for the sales report.

**Prompt:**

> Show me the full product catalog from PostgreSQL — I need to see which
> products are in stock and their prices

**Expected Outcome:** The system queries `pg_demo:products` and returns all 6
products:

- Wireless Mouse
- Mechanical Keyboard
- USB-C Hub
- Notebook A5
- Ballpoint Pen Pack
- Standing Desk Mat

Each entry includes `name`, `category`, `price`, and `in_stock` status.

---

### Step 4: Cross-Reference with MongoDB

**Context:** MongoDB stores denormalized order data with customer and product
names embedded directly in each document. This makes it easy to get a quick
per-customer breakdown without joins.

**Prompt:**

> Now check the MongoDB orders for Alice Johnson — I want to see all her
> purchases with product names and totals

**Expected Outcome:** The system queries `mongo_demo:orders` with a predicate
filtering by `customer_name = "Alice Johnson"`, projecting `product_name`,
`total`, and `ordered_at`. The analyst sees Alice's complete purchase history
with human-readable product names and order totals.

---

### Step 5: Search Customer Feedback (pgvector)

**Context:** The Wireless Mouse appears to be the top seller. Before including
it in the report, the analyst wants to see what customers are actually saying
about it.

**Prompt:**

> Search the customer feedback for reviews about the Wireless Mouse — I want
> to see the ratings and what people are saying

**Expected Outcome:** The system queries `pgvector_demo:feedback` filtering by
`product_name = "Wireless Mouse"`, returning `title`, `content`, and `rating`.
The analyst sees individual review entries with star ratings and written
feedback, confirming customer sentiment is mostly positive.

---

### Step 6: Review Invoice Details (POSIX)

**Context:** The analyst pulls up a specific invoice file to verify that billing
details match the order data retrieved from PostgreSQL and MongoDB.

**Prompt:**

> Read the invoice INV-2025-001 from the filesystem — I need to verify the
> billing details

**Expected Outcome:** The system performs a LOOKUP on `posix_demo:invoices` with
key `INV-2025-001`. The returned content of `INV-2025-001.txt` shows:

- Customer: Alice Johnson
- Product: Wireless Mouse
- Total: $32.99 (including tax)

This matches the order data from the previous steps.

---

### Step 7: Read Product Description (POSIX)

**Context:** The analyst retrieves the product description file for the Wireless
Mouse to include marketing copy in the quarterly report.

**Prompt:**

> Show me the product description file for the wireless mouse

**Expected Outcome:** The system performs a LOOKUP on `posix_demo:products` with
key `wireless-mouse`. The content of `wireless-mouse.txt` is returned, containing
the full product description including features, specifications, and marketing
text.

---

### Step 8: Generate Summary Report (POSIX INGEST)

**Context:** With all the data gathered, the analyst writes a summary of the Q4
findings to a new file that can be shared with the team.

**Prompt:**

> Create a new report file called 'q4-sales-summary.txt' in the products
> directory with a brief summary of our Q4 findings: top seller is Wireless
> Mouse, 4 shipped orders, customer feedback is positive

**Expected Outcome:** The system executes an INGEST intent on `posix_demo:products`,
creating a new file `q4-sales-summary.txt` with the summary content. The analyst
confirms the file was written successfully and can be accessed by the team.

---

## Conclusion

This scenario demonstrated the power of the ADP Data Hypervisor as a unified
data access layer:

- **4 heterogeneous backends** (PostgreSQL, MongoDB, pgvector, POSIX) accessed
  through a single natural-language interface
- **Read and write operations** — from querying structured tables to writing new
  files on the filesystem
- **Structured and unstructured data** — SQL rows, JSON documents, semantic
  embeddings, and plain text files all handled seamlessly
- **Cross-referencing** — the analyst verified data consistency across backends
  without writing a single line of code

The ADP Data Hypervisor abstracts backend complexity so analysts can focus on
the business questions, not the plumbing.
