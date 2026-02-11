// Sample e-commerce data for ADP Hypervisor MongoDB demo

db = db.getSiblingDB("adp_demo");

// Seed customers
db.customers.insertMany([
  { name: "Alice Johnson", email: "alice@example.com", city: "Seattle", created_at: new Date("2025-11-01T08:00:00Z") },
  { name: "Bob Smith", email: "bob@example.com", city: "Portland", created_at: new Date("2025-11-05T10:30:00Z") },
  { name: "Carol White", email: "carol@example.com", city: "San Francisco", created_at: new Date("2025-11-10T14:00:00Z") },
  { name: "David Brown", email: "david@example.com", city: "Austin", created_at: new Date("2025-11-15T09:45:00Z") },
  { name: "Eva Martinez", email: "eva@example.com", city: "New York", created_at: new Date("2025-11-20T16:20:00Z") },
]);

// Seed products
db.products.insertMany([
  { name: "Wireless Mouse", category: "Electronics", price: 29.99, in_stock: true },
  { name: "Mechanical Keyboard", category: "Electronics", price: 89.99, in_stock: true },
  { name: "USB-C Hub", category: "Electronics", price: 45.00, in_stock: true },
  { name: "Notebook (A5)", category: "Stationery", price: 12.50, in_stock: true },
  { name: "Ballpoint Pen Pack", category: "Stationery", price: 5.99, in_stock: true },
  { name: "Standing Desk Mat", category: "Furniture", price: 39.99, in_stock: false },
]);

// Seed orders
db.orders.insertMany([
  { customer_name: "Alice Johnson", product_name: "Wireless Mouse", quantity: 1, total: 29.99, status: "shipped", ordered_at: new Date("2025-12-01T10:00:00Z") },
  { customer_name: "Alice Johnson", product_name: "Mechanical Keyboard", quantity: 1, total: 89.99, status: "delivered", ordered_at: new Date("2025-12-03T14:30:00Z") },
  { customer_name: "Bob Smith", product_name: "USB-C Hub", quantity: 2, total: 90.00, status: "shipped", ordered_at: new Date("2025-12-05T09:15:00Z") },
  { customer_name: "Bob Smith", product_name: "Ballpoint Pen Pack", quantity: 3, total: 17.97, status: "delivered", ordered_at: new Date("2025-12-05T09:15:00Z") },
  { customer_name: "Carol White", product_name: "Wireless Mouse", quantity: 1, total: 29.99, status: "pending", ordered_at: new Date("2025-12-10T16:45:00Z") },
  { customer_name: "Carol White", product_name: "Notebook (A5)", quantity: 5, total: 62.50, status: "shipped", ordered_at: new Date("2025-12-11T08:00:00Z") },
  { customer_name: "David Brown", product_name: "Mechanical Keyboard", quantity: 1, total: 89.99, status: "pending", ordered_at: new Date("2025-12-15T11:20:00Z") },
  { customer_name: "David Brown", product_name: "Standing Desk Mat", quantity: 1, total: 39.99, status: "cancelled", ordered_at: new Date("2025-12-15T11:20:00Z") },
  { customer_name: "Eva Martinez", product_name: "USB-C Hub", quantity: 1, total: 45.00, status: "shipped", ordered_at: new Date("2025-12-18T13:00:00Z") },
  { customer_name: "Eva Martinez", product_name: "Wireless Mouse", quantity: 2, total: 59.98, status: "delivered", ordered_at: new Date("2025-12-20T17:30:00Z") },
]);
