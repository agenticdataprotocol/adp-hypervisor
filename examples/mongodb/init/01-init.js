/*
 * Copyright 2026 Datastrato, Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

db = db.getSiblingDB("adp_mongo_demo");

db.users.createIndex({ user_id: 1 }, { unique: true });
db.users.createIndex({ segment: 1, status: 1, login_count: -1 });

db.users.deleteMany({});
db.users.insertMany([
  {
    _id: "usr_001",
    user_id: "usr_001",
    name: "Alicia Chen",
    email: "alicia.chen@example.com",
    segment: "enterprise",
    status: "active",
    login_count: 42,
  },
  {
    _id: "usr_002",
    user_id: "usr_002",
    name: "Bruno Diaz",
    email: "bruno.diaz@example.com",
    segment: "smb",
    status: "inactive",
    login_count: 5,
  },
  {
    _id: "usr_003",
    user_id: "usr_003",
    name: "Nia Patel",
    email: "nia.patel@example.com",
    segment: "enterprise",
    status: "active",
    login_count: 27,
  },
  {
    _id: "usr_004",
    user_id: "usr_004",
    name: "Maya Singh",
    email: "maya.singh@example.com",
    segment: "startup",
    status: "active",
    login_count: 18,
  },
  {
    _id: "usr_005",
    user_id: "usr_005",
    name: "Jordan Lee",
    email: "jordan.lee@example.com",
    segment: "enterprise",
    status: "trial",
    login_count: 9,
  },
]);
