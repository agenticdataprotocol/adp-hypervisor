# Gravitino Release Manager Demo 设计文档

## 概述

使用 **Slack + OpenClaw + ADP Hypervisor** 构建一个端到端的 Apache Gravitino Release Manager 演示，展示 AI Agent 如何通过自然语言对话驱动整个发版流程。

### 架构

```
                                                           ┌──► Local Filesystem (release 状态/文档/凭证, CRUD)
Release Manager ──► Slack ──► OpenClaw ──► ADP Hypervisor ─┤──► PostgreSQL (历史/参考数据, 只读)
       PMC             │     (AI Agent)    (数据访问层)       └──► pgvector (历史文档语义搜索, 只读)
       Committer       │         │          RBAC 策略
       Viewer          │         │          (per-user isolation)
                       │         └──► GitHub API (issues, PRs, CI, milestones)
                       │         └──► ASF Infra (SVN, Maven, mailing lists)
                       │
                       └─ 交互界面
```

**数据访问分层：**
- **经 ADP 访问（契约驱动 + RBAC）**：Release 管理数据（状态、checklist、RC 记录、投票、凭证、生成文档）+ 历史参考数据 + 语义搜索
- **Agent 直接调用**：GitHub API（实时查询 issues/PRs/CI 状态）、ASF 基础设施（SVN/Maven/邮件列表）

> 详细的 ADP 集成架构设计见 [`adp-integration-with-release-agent.md`](./adp-integration-with-release-agent.md)

### 核心价值

- **对话式发版管理**：Release manager 通过 Slack 自然语言交互，替代手动翻 checklist
- **契约驱动的数据访问**：通过 ADP 的 discover → describe → validate → execute 流程，确保数据操作安全可控
- **多异构后端统一访问**：一个 ADP 实例同时管理 Local Filesystem（可写）和 PostgreSQL（只读）数据
- **RBAC 权限分层**：不同角色对不同资源有精确的操作权限控制
- **全流程可追踪**：每个 checklist 步骤的状态变更都有记录

### ADP Backend 能力概览

| Backend | LOOKUP | QUERY | INGEST | REVISE | 适用场景 |
|---|---|---|---|---|---|
| Local Filesystem (BLOB_STORAGE) | ✅ | ✅ | ✅ | ✅ | Release 状态、文档、凭证（完整 CRUD） |
| PostgreSQL (RDBMS) | ✅ | ✅ | ❌ | ❌ | 历史 release 记录、committer/PMC 名单（只读查询） |
| pgvector (VECTOR) | ✅ | ✅ + SIMILAR | ❌ | ❌ | 历史投票邮件/公告的语义搜索（只读） |
| MongoDB (NOSQL) | ✅ | ✅ | ❌ | ❌ | 非结构化数据查询（未来扩展） |

### RBAC 权限矩阵

| 资源 / 角色 | release_manager | pmc | committer | viewer |
|---|---|---|---|---|
| `release:releases` (文件系统) | LOOKUP/QUERY/INGEST/REVISE | LOOKUP/QUERY/REVISE | LOOKUP/QUERY | LOOKUP/QUERY |
| `release:checklist` (文件系统) | LOOKUP/QUERY/INGEST/REVISE | LOOKUP/QUERY/REVISE | LOOKUP/QUERY/REVISE | LOOKUP/QUERY |
| `release:candidates` (文件系统) | LOOKUP/QUERY/INGEST/REVISE | LOOKUP/QUERY | LOOKUP/QUERY | LOOKUP/QUERY |
| `release:votes` (文件系统) | LOOKUP/QUERY/INGEST/REVISE | LOOKUP/QUERY/INGEST | LOOKUP/QUERY/INGEST | LOOKUP/QUERY |
| `release:documents` (文件系统) | LOOKUP/QUERY/INGEST/REVISE | LOOKUP/QUERY | LOOKUP/QUERY | LOOKUP/QUERY |
| `release:credentials:<user>` (文件系统) | LOOKUP/QUERY (own only) | — | LOOKUP/QUERY (own only) | — |
| `gravitino:issues` (PG 只读) | LOOKUP/QUERY | LOOKUP/QUERY | LOOKUP/QUERY | QUERY |
| `gravitino:contributors` (PG 只读) | LOOKUP/QUERY | LOOKUP/QUERY | LOOKUP/QUERY | QUERY |
| `gravitino:release_history` (PG 只读) | LOOKUP/QUERY | LOOKUP/QUERY | LOOKUP/QUERY | QUERY |
| `gravitino:templates` (pgvector 只读) | LOOKUP/QUERY/SIMILAR | LOOKUP/QUERY/SIMILAR | LOOKUP/QUERY/SIMILAR | QUERY/SIMILAR |

**角色说明：**
- **release_manager**：全权限，唯一能创建 release 和 RC 的角色
- **pmc**：可以更新 release 状态（如投票结果）和 checklist，但不能创建新 release
- **committer**：可以更新自己负责的 checklist 步骤状态，但不能修改 release 和 RC 信息
- **viewer**：纯只读，适合关注发版进度的社区成员

---

## 当前状态

| 组件 | 状态 | 说明 |
|---|---|---|
| OpenClaw | ✅ 已部署 | GCP 虚拟机上运行，已接入 Slack channel |
| ADP Hypervisor | ✅ 源码就绪 | 支持 PostgreSQL/MongoDB/pgvector/本地文件系统，支持 LOOKUP/QUERY/INGEST/REVISE |
| OpenClaw ↔ ADP 集成 | ❌ 未开始 | ADP 当前只支持 stdio transport，需确认 OpenClaw 的 tool 调用方式 |
| Release 数据模型 | 🔄 设计中 | ADP 集成文档 [`adp-integration-with-release-agent.md`](./adp-integration-with-release-agent.md) 正在设计 |
| Release Workflow | ✅ 已完成 | 5 个 Phase 的 Slack 交互流程已全部确认（见下文） |
| ADP Integration Design | 🔄 设计中 | ADP 核心价值、架构、资源设计见 [`adp-integration-with-release-agent.md`](./adp-integration-with-release-agent.md) |
| Demo Script | ❌ 未开始 | 需要编写演示脚本 |

---

## Release Workflow 设计

### 流程总览

基于 `docs/checklist_for_gravitino_release.md` 和 Gravitino 的 `dev/release/` 脚本，将整个发版流程分为 **5 个阶段**：

```
Phase 1 ──► Phase 2 ──► Phase 3 ◄──► Phase 4 ──► Phase 5
Planning     Preparation  Build RC    Vote        Publish
                           ▲           │
                           └───────────┘
                          投票失败，修复后重新构建 RC
```

| 阶段 | 名称 | 核心活动 | 主要参与者 |
|---|---|---|---|
| Phase 1 | **Release Planning** | 指定 RM、确认 feature 完成、整理 issues | pmc, release_manager |
| Phase 2 | **Release Preparation** | Cut branch、检查 license、更新文档、准备 release note | release_manager, committer |
| Phase 3 | **Build RC** | 运行 `do-release.sh`、发布 Docker 镜像、验证产物 | release_manager |
| Phase 4 | **Vote & Verify** | 发起 PMC 投票、社区验证 RC、处理投票结果 | release_manager, pmc |
| Phase 5 | **Publish & Announce** | Finalize release、更新 playground/website、全渠道宣布 | release_manager, pmc |

### Phase Gate 机制

每个 Phase 之间有严格的门控条件，Bot 会自动检查是否满足进入下一阶段的前置条件：

| 转换 | 进入条件 |
|---|---|
| → Phase 1 | PMC 成员指定 release manager |
| Phase 1 → Phase 2 | 所有 milestone issues 已关闭或明确 deferred，RM 确认进入 |
| Phase 2 → Phase 3 | 所有 Phase 2 checklist 步骤标记为 done 或 skipped |
| Phase 3 → Phase 4 | RC 构建成功，产物验证通过 |
| Phase 4 → Phase 3 | 投票失败，回退修复，构建下一个 RC |
| Phase 4 → Phase 5 | 投票通过 |

**门控检查示例 — 条件满足：**
```
RM:  "All planned features are ready. Move to preparation phase."
Bot: 🔍 Checking Phase 1 completion criteria...
     ✅ Release Manager designated: @mchades
     ✅ Milestone v1.2.0: 138/138 issues closed (4 deferred to 1.3.0)
     ✅ All planned PRs merged

     Phase 1 ✅ Complete → Entering Phase 2: Release Preparation
```

**门控检查示例 — 条件不满足：**
```
RM:  "Move to preparation phase."
Bot: ❌ Cannot enter Phase 2. Unmet criteria:
     - 4 issues still open in milestone v1.2.0
       • #1234 - Add S3 catalog support
       • #1235 - Fix Iceberg REST API compatibility
       • #1240 - Update Trino connector docs
       • #1242 - Bump Hadoop dependency to 3.4
     - 2 PRs unmerged
     Please resolve or defer these items first.
```

---

### Phase 1: Release Planning

**目标**：由 PMC 发起，指定 Release Manager，确认所有计划 feature 就绪。

**Slack 交互流程：**

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Phase 1: Release Planning                                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Step 1 — 未授权用户尝试发起 release（RBAC 拦截 ❌）                       │
│                                                                         │
│  @mchades (committer):                                                  │
│       "I'd like to start the release process for Gravitino 1.2.0."      │
│  Bot: ❌ Permission denied. Only PMC members can initiate a release      │
│       and designate a Release Manager.                                  │
│       Your current role: committer                                      │
│       Please ask a PMC member to designate a Release Manager first.     │
│                                                                         │
│  Step 2 — PMC 指定 Release Manager                                      │
│                                                                         │
│  @pmc_member (pmc):                                                     │
│       "Designate @mchades as the release manager for Gravitino 1.2.0"   │
│  Bot: ✅ @mchades has been designated as the Release Manager for 1.2.0  │
│       Checking release readiness for v1.2.0...                          │
│                                                                         │
│       📋 Milestone `v1.2.0` Summary:                                    │
│       - Total Issues: 142                                               │
│       - Closed: 138                                                     │
│       - Open: 4                                                         │
│         • #1234 - Add S3 catalog support                                │
│         • #1235 - Fix Iceberg REST API compatibility                    │
│         • #1240 - Update Trino connector docs                           │
│         • #1242 - Bump Hadoop dependency to 3.4                         │
│       - Unmerged PRs: 2                                                 │
│         • PR #1238 - feat: S3 catalog implementation                    │
│         • PR #1241 - docs: Trino connector guide                        │
│       ⚠️ Recommend closing remaining issues before proceeding.          │
│                                                                         │
│  Step 3 — RM 尝试创建 release 计划（门控条件不满足 ❌）                     │
│                                                                         │
│  RM:  "Create the release plan for 1.2.0."                              │
│  Bot: ❌ Cannot create release plan. Unmet criteria:                     │
│       - 4 issues still open in milestone v1.2.0                         │
│         • #1234 - Add S3 catalog support                                │
│         • #1235 - Fix Iceberg REST API compatibility                    │
│         • #1240 - Update Trino connector docs                           │
│         • #1242 - Bump Hadoop dependency to 3.4                         │
│       - 2 PRs unmerged                                                  │
│         • PR #1238 - feat: S3 catalog implementation                    │
│         • PR #1241 - docs: Trino connector guide                        │
│       Please close, merge, or defer these items first.                  │
│                                                                         │
│  Step 4 — RM 处理遗留项后再次尝试（门控条件满足 ✅）                        │
│                                                                         │
│  RM:  "Defer #1234 and #1238 to 1.3.0. The rest are ready. Create the  │
│        release plan."                                                   │
│  Bot: 🔍 Re-checking release readiness for v1.2.0...                    │
│       ✅ Milestone v1.2.0: 140/142 issues resolved                      │
│          (138 closed, 2 deferred to 1.3.0)                              │
│       ✅ All planned PRs merged                                         │
│                                                                         │
│       ✅ Gravitino 1.2.0 Release Plan Created                           │
│       Release Manager: @mchades (designated by @pmc_member)             │
│       Target Branch: branch-1.2                                         │
│       Checklist generated (15 steps):                                   │
│         Phase 2 - Preparation: 7 steps                                  │
│         Phase 3 - Build RC: 4 steps                                     │
│         Phase 4 - Vote: 2 steps                                         │
│         Phase 5 - Publish: 4 steps (activates after vote passes)        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Agent 在 Phase 1 中的能力：**
- 👤 **记录 RM 指定**：由 PMC 发起，记录谁是 release manager 以及指定人
- 🔍 **查询 GitHub**：获取 milestone 下的 issues/PRs 状态，给出 readiness 报告
- 🚧 **门控检查**：在创建 release 计划前自动验证前置条件，不满足时阻止并给出明确指引
- 📝 **创建 Release 计划**：条件满足后初始化 release 记录和 checklist
- 🏷️ **整理 Issues**：帮助迁移未完成 issues 到下一个 milestone

---

### Phase 2: Release Preparation

**目标**：完成发版前所有准备工作，包括 branch 创建、license 检查、release note 编写和文档更新。

**Slack 交互流程：**

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Phase 2: Release Preparation                                              │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  Step 1 — 进入 Phase 2（Phase Gate ✅）                                    │
│                                                                           │
│  RM:  "All planned features are ready. Move to preparation phase."        │
│  Bot: 🔍 Checking Phase 1 completion criteria...                          │
│       ✅ Release Manager designated: @mchades                             │
│       ✅ Milestone v1.2.0: 140/142 issues resolved                        │
│          (138 closed, 2 deferred to 1.3.0)                                │
│       ✅ All planned PRs merged                                           │
│                                                                           │
│       Phase 1 ✅ Complete → Entering Phase 2: Release Preparation         │
│                                                                           │
│       📋 Phase 2 Checklist (6 steps):                                     │
│       1. ⬜ Raise PR for auto cherry-pick workflow                        │
│       2. ⬜ Cut release branch (branch-1.2)                               │
│       3. ⬜ Check and refine jar licenses                                 │
│       4. ⬜ Update version in docs/docker-image-details.md                │
│       5. ⬜ Prepare release note                                          │
│       6. ⬜ Review docs structure (coordinate with frontend)              │
│                                                                           │
│  Step 2 — Bot 执行 cherry-pick PR & cut branch（Agent 执行 + RM 确认）     │
│                                                                           │
│  RM:  "Start preparation for cherry-pick workflow and branch cut."        │
│  Bot: 📋 I'll perform the following operations:                           │
│       1. Create PR to add branch-1.2 to auto-cherry-pick.yml              │
│          Target file: .github/workflows/auto-cherry-pick.yml              │
│          Change: Add "branch-1.2" to branch list                          │
│       2. Create release branch: branch-1.2 from current main HEAD         │
│          (commit: abc1234 "Merge PR #1241: docs: Trino connector")        │
│                                                                           │
│       ⚠️ Please confirm before I proceed. [Confirm / Modify / Cancel]    │
│                                                                           │
│  RM:  "Confirm"                                                           │
│  Bot: ⏳ Executing...                                                     │
│       ✅ PR #1250 created: "Add branch-1.2 to auto cherry-pick workflow"  │
│       ✅ Branch branch-1.2 created from main (abc1234)                     │
│       Steps 1, 2 marked as done. Progress: 2/6                           │
│                                                                           │
│  Step 3 — License 检查（构建发布包 + diff + LICENSE.bin 校验）              │
│                                                                           │
│  RM:  "Check the license status for 1.2.0"                               │
│  Bot: 🔍 Starting license check...                                       │
│       1. Building release package from branch-1.2 using release scripts   │
│          ⏳ Running `dev/release/release-build.sh package` ...             │
│          ✅ Build completed. Package: gravitino-1.2.0.tar.gz              │
│                                                                           │
│       2. Extracting jars and comparing with v1.1.0 release...            │
│          Total jars in 1.2.0: 186                                         │
│          Total jars in 1.1.0: 179                                         │
│          New jars (+7):                                                    │
│          ┌──────────────────────────┬─────────────┬──────────────────┐    │
│          │ Jar                      │ License     │ In LICENSE.bin?  │    │
│          ├──────────────────────────┼─────────────┼──────────────────┤    │
│          │ commons-csv-1.11.0       │ Apache-2.0  │ ✅ Yes           │    │
│          │ snappy-java-1.1.10.5     │ Apache-2.0  │ ✅ Yes           │    │
│          │ error-prone-2.28.0       │ Apache-2.0  │ ❌ No            │    │
│          │ jackson-datatype-jsr310  │ Apache-2.0  │ ❌ No            │    │
│          │ proto-google-common-1.0  │ Apache-2.0  │ ✅ Yes           │    │
│          │ re2j-1.7                 │ BSD-3       │ ❌ No            │    │
│          │ animal-sniffer-1.23      │ MIT         │ ❌ No            │    │
│          └──────────────────────────┴─────────────┴──────────────────┘    │
│          Removed jars (-0): none                                          │
│                                                                           │
│       3. License compatibility: All 7 new jars are Apache-2.0 compatible  │
│       ⚠️ 4 new jars missing from LICENSE.bin:                             │
│          • error-prone-2.28.0                                             │
│          • jackson-datatype-jsr310                                        │
│          • re2j-1.7                                                       │
│          • animal-sniffer-1.23                                            │
│                                                                           │
│       Shall I create a PR to add these to LICENSE.bin? [Yes / No]         │
│                                                                           │
│  RM:  "Yes"                                                               │
│  Bot: ✅ PR #1251 created: "Add missing jars to LICENSE.bin for 1.2.0"   │
│       Step 3 will be marked done after PR is merged.                      │
│                                                                           │
│  Step 4 — Release Note 编写 + 投票                                       │
│                                                                           │
│  RM:  "Generate a draft release note for 1.2.0"                          │
│  Bot: 🔍 Fetching historical release notes for reference...               │
│       - v1.1.0: https://github.com/apache/gravitino/releases/tag/v1.1.0  │
│       - v1.0.0: https://github.com/apache/gravitino/releases/tag/v1.0.0  │
│       Analyzing format and style patterns...                              │
│                                                                           │
│       📝 Draft release note for Gravitino 1.2.0:                         │
│       (following v1.1.0 format)                                           │
│                                                                           │
│       ## What's New                                                       │
│       ### Paimon Catalog Support                                          │
│       Gravitino now supports Apache Paimon as a catalog backend. (#1023)  │
│       ### Improved Iceberg REST Catalog Performance                       │
│       Query latency reduced by 40% for Iceberg REST catalog. (#1085)     │
│       ## Breaking Changes                                                 │
│       - Removed deprecated `CatalogOperations` API. (#1050)               │
│         Migration: Use `CatalogService` instead.                          │
│       ## Bug Fixes                                                        │
│       - Fixed credential vending for S3 FileSets (#1072)                  │
│       - Fixed partition handling in Hive catalog (#1089)                  │
│       - ... (21 more)                                                     │
│       ## Contributors                                                     │
│       Thanks to 25 contributors for this release!                         │
│                                                                           │
│       Please review and let me know if you'd like any changes.            │
│                                                                           │
│  RM:  "Add the credential vending improvement to highlights. Otherwise    │
│        looks good. Finalize it."                                          │
│  Bot: ✅ Release note updated and finalized by RM.                        │
│       Starting committer vote on release note...                          │
│       📢 @committers: Please vote on the release note for Gravitino      │
│       1.2.0. React with 👍 to approve or 👎 to reject.                   │
│       (Requires approval from >50% of committers to pass)                │
│       Current: 0/12 votes received, need 7 approvals.                     │
│                                                                           │
│  ... (time passes, votes come in)                                         │
│                                                                           │
│  Bot: 📊 Release note vote result:                                        │
│       👍 9 approvals / 👎 1 rejection / 2 abstained                       │
│       ✅ Vote passed (9/12 > 50%). Step 5 marked as done.                 │
│                                                                           │
│  Step 5 — Bot 协助 docs review（Agent 执行 + RM 确认）                    │
│                                                                           │
│  RM:  "Check if any docs need updates for 1.2.0"                         │
│  Bot: 🔍 Scanning branch-1.2 for doc changes...                          │
│       Compared docs/ directory between v1.1.0 and branch-1.2:            │
│       - New docs added (3):                                               │
│         • docs/paimon-catalog-guide.md                                    │
│         • docs/credential-vending-v2.md                                   │
│         • docs/migration-guide-1.2.md                                     │
│       - Modified docs (5):                                                │
│         • docs/iceberg-rest-catalog.md (perf section updated)             │
│         • docs/getting-started.md (version references)                    │
│         • ...                                                             │
│       - docs/docker-image-details.md: ⚠️ Still references v1.1.0         │
│                                                                           │
│       Suggested actions:                                                  │
│       1. Update version in docs/docker-image-details.md to 1.2.0         │
│       2. Add new docs to sidebar navigation                               │
│       Shall I create a PR for these changes? [Yes / No]                   │
│                                                                           │
│  RM:  "Yes"                                                               │
│  Bot: ✅ PR #1253 created: "Update docs for 1.2.0 release"               │
│       Steps 4, 6 marked as done after PR merges. Progress: 6/6           │
│                                                                           │
│  Step 6 — 进入 Phase 3（Phase Gate ✅）                                    │
│                                                                           │
│  RM:  "All preparation done. Move to Build RC."                           │
│  Bot: 🔍 Checking Phase 2 completion criteria...                          │
│       ✅ 6/6 checklist steps completed                                     │
│       ✅ Release branch branch-1.2 exists                                  │
│       ✅ Release note finalized and approved by committer vote             │
│       ✅ LICENSE.bin updated                                               │
│       ✅ Docs updated                                                      │
│                                                                           │
│       Phase 2 ✅ Complete → Entering Phase 3: Build RC                    │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

**Agent 在 Phase 2 中的能力：**
- 🤖 **Agent 执行 + 人工确认**：Bot 提出操作方案，RM 确认后执行（GitHub PR、branch 操作等）
- 🔍 **License 深度检查**：构建发布包 → 提取 jars → 对比上一版本 → 检查 license 兼容性 → 校验 LICENSE.bin 覆盖
- 📝 **Release Note 生成**：参考历史版本格式风格 → 生成草稿 → RM 审定修改 → committer 投票（>50% 通过）
- 📄 **Docs 扫描与更新**：自动检测文档变更、版本号过期，生成更新 PR
- 👥 **多角色协作**：committer 参与 release note 投票
- 🚧 **Phase Gate**：所有步骤完成 + 关键产物就绪后才可进入 Phase 3

---

### Phase 3: Build RC

**目标**：运行 release 脚本构建 RC 候选版本，验证所有发布产物，发布 Docker 镜像并通过 Playground 做 smoke test。

**Slack 交互流程：**

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Phase 3: Build RC                                                         │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  Step 1 — RM 发起 RC 构建（Bot 自动判断状态）                              │
│                                                                           │
│  Bot 根据当前 release 状态自动决定行为，RM 无需指定 RC 编号。               │
│                                                                           │
│  === 场景 A: 首次进入 Phase 3，自动构建 RC1 ===                             │
│                                                                           │
│  RM:  "Let's build the RC."                                               │
│  Bot: 🔍 Checking release state for v1.2.0...                             │
│       No previous RC found. This will be RC1.                             │
│                                                                           │
│       📋 RC1 build plan:                                                  │
│       Target: v1.2.0-rc1                                                  │
│       Branch: branch-1.2                                                  │
│       Release steps (via do-release.sh):                                  │
│       1. ⬜ Create release tag (v1.2.0-rc1)                               │
│       2. ⬜ Build Gravitino package                                       │
│       3. ⬜ Build documentation                                           │
│       4. ⬜ Publish to Apache SVN + Maven staging + PyPI                  │
│                                                                           │
│       Required environment:                                               │
│       ✅ GCP VM ready (release-vm-01)                                     │
│       ✅ GPG key configured                                               │
│       ✅ ASF credentials set                                              │
│       ✅ PYPI_API_TOKEN set                                               │
│                                                                           │
│       ⚠️ This will create a tag and publish artifacts.                   │
│       Shall I proceed? [Confirm / Cancel]                                 │
│                                                                           │
│  === 场景 B: RC1 vote 失败后回退，自动构建 RC2 ===                          │
│                                                                           │
│  RM:  "Let's build the RC."                                               │
│  Bot: 🔍 Checking release state for v1.2.0...                             │
│       Previous RC: RC1 (vote failed)                                      │
│       This will be RC2.                                                   │
│                                                                           │
│       🔍 Pre-build check — verifying RC1 action items resolved:           │
│       ✅ #1260 Fix GPG signature issue — cherry-picked (commit: def5678) │
│       ✅ #1261 Fix Python client on macOS arm64 — cherry-picked (ef9012) │
│       All 2 action items from RC1 vote resolved.                          │
│                                                                           │
│       📋 RC2 build plan:                                                  │
│       Target: v1.2.0-rc2                                                  │
│       Branch: branch-1.2 (HEAD: ef9012)                                   │
│       Changes since RC1: 2 fix commits                                    │
│       Release steps: same as RC1 (tag → build → docs → publish)          │
│                                                                           │
│       ⚠️ This will create a tag and publish artifacts.                   │
│       Shall I proceed? [Confirm / Cancel]                                 │
│                                                                           │
│  === 场景 C: 修复未完成时 Bot 拦截（门控 ❌）===                            │
│                                                                           │
│  RM:  "Let's build the RC."                                               │
│  Bot: 🔍 Checking release state for v1.2.0...                             │
│       Previous RC: RC1 (vote failed)                                      │
│       This will be RC2.                                                   │
│                                                                           │
│       🔍 Pre-build check — verifying RC1 action items resolved:           │
│       ✅ #1260 Fix GPG signature issue — cherry-picked (commit: def5678) │
│       ❌ #1261 Fix Python client on macOS arm64 — NOT on branch-1.2      │
│                                                                           │
│       ❌ Cannot build RC2. 1 action item still unresolved:                 │
│       • #1261 - Fix has not been cherry-picked to branch-1.2              │
│       Please cherry-pick the fix and try again.                           │
│                                                                           │
│  RM:  "Confirm"                                                           │
│  Bot: ⏳ Running do-release.sh on release-vm-01...                        │
│                                                                           │
│       [1/4] Creating release tag v1.2.0-rc1... ✅ Done                    │
│       ℹ️ Please verify the tag is available on GitHub:                    │
│       https://github.com/apache/gravitino/releases/tag/v1.2.0-rc1        │
│       Ready to continue? [Yes / Retry]                                    │
│                                                                           │
│  RM:  "Yes"                                                               │
│  Bot: [2/4] Building Gravitino package... ⏳ (this may take ~15 min)      │
│       ...                                                                 │
│       ✅ Build completed. Output: gravitino-1.2.0-bin.tar.gz (256 MB)     │
│       [3/4] Building documentation... ✅ Done                             │
│       [4/4] Publishing release artifacts...                               │
│       ⏳ Uploading to Apache SVN...                                       │
│       ⏳ Publishing to Maven staging repo...                              │
│       ⏳ Publishing to PyPI (apache-gravitino 1.2.0rc1)...                │
│       ✅ All artifacts published                                          │
│                                                                           │
│  Step 2 — 验证发布产物                                                    │
│                                                                           │
│  Bot: 🔍 Verifying release artifacts...                                   │
│                                                                           │
│       Apache SVN:                                                         │
│       ✅ https://dist.apache.org/repos/dist/dev/gravitino/v1.2.0-rc1/     │
│          - gravitino-1.2.0-bin.tar.gz (256 MB) ✅                         │
│          - gravitino-1.2.0-bin.tar.gz.sha512 ✅                           │
│          - gravitino-1.2.0-bin.tar.gz.asc ✅ (GPG signature valid)        │
│                                                                           │
│       Maven Staging:                                                      │
│       ✅ https://repository.apache.org/#stagingRepositories               │
│          Staging repo: orgapachegravitino-1042 (status: OPEN)             │
│                                                                           │
│       PyPI:                                                               │
│       ✅ https://pypi.org/project/apache-gravitino/1.2.0rc1/              │
│                                                                           │
│       GitHub Release:                                                     │
│       ✅ https://github.com/apache/gravitino/releases/tag/v1.2.0-rc1      │
│                                                                           │
│       All artifacts verified successfully.                                │
│                                                                           │
│  Step 3 — 发布 Docker 镜像（Agent 执行 + RM 确认）                        │
│                                                                           │
│  RM:  "Release Docker image for RC1."                                     │
│  Bot: 📋 I'll trigger the Docker image release via GitHub CI:             │
│       Workflow: .github/workflows/docker-image.yml                        │
│       Tag: v1.2.0-rc1                                                     │
│       Image: apache/gravitino:1.2.0-rc1                                   │
│                                                                           │
│       ⚠️ Please confirm. [Confirm / Cancel]                              │
│                                                                           │
│  RM:  "Confirm"                                                           │
│  Bot: ⏳ GitHub Actions workflow triggered...                              │
│       Run: https://github.com/apache/gravitino/actions/runs/12345         │
│       ...                                                                 │
│       ✅ Docker image published: apache/gravitino:1.2.0-rc1               │
│                                                                           │
│  Step 4 — 使用 Playground 验证                                            │
│                                                                           │
│  RM:  "Verify RC1 with the playground."                                   │
│  Bot: 📋 I'll update the Gravitino playground to use v1.2.0-rc1 and run  │
│       a basic smoke test:                                                 │
│       1. Update playground docker-compose to use image 1.2.0-rc1          │
│       2. Start playground environment                                     │
│       3. Run basic catalog operations (create/list/drop)                  │
│       4. Verify REST API endpoints                                        │
│                                                                           │
│       ⚠️ Please confirm. [Confirm / Cancel]                              │
│                                                                           │
│  RM:  "Confirm"                                                           │
│  Bot: ⏳ Running playground verification...                                │
│       ✅ Playground started with gravitino:1.2.0-rc1                      │
│       ✅ Created Hive catalog — OK                                        │
│       ✅ Listed catalogs — OK (3 catalogs)                                │
│       ✅ REST API /api/version returns "1.2.0" — OK                      │
│       ✅ All smoke tests passed                                           │
│                                                                           │
│  Step 5 — 记录 RC 信息并进入 Phase 4                                      │
│                                                                           │
│  Bot: 📝 RC1 Summary:                                                     │
│       Version: v1.2.0-rc1                                                 │
│       SVN: https://dist.apache.org/repos/dist/dev/gravitino/v1.2.0-rc1/  │
│       Maven: orgapachegravitino-1042                                      │
│       PyPI: apache-gravitino 1.2.0rc1                                     │
│       Docker: apache/gravitino:1.2.0-rc1                                  │
│       GitHub: https://github.com/apache/gravitino/releases/tag/v1.2.0-rc1│
│       Playground verification: ✅ Passed                                  │
│                                                                           │
│       All Phase 3 steps completed.                                        │
│       Ready to proceed to Phase 4: Vote & Verify? [Yes / Not yet]        │
│                                                                           │
│  RM:  "Yes"                                                               │
│  Bot: Phase 3 ✅ Complete → Entering Phase 4: Vote & Verify               │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

**Agent 在 Phase 3 中的能力：**
- 🔧 **Release 脚本编排**：逐步执行 `do-release.sh` 的 tag → build → docs → publish 流程，每步报告进度
- ✅ **产物自动验证**：检查 SVN 文件完整性（tarball + sha512 + GPG 签名）、Maven staging repo 状态、PyPI 包可用性
- 🐳 **Docker 发布**：触发 GitHub CI workflow 构建并发布 Docker 镜像
- 🎮 **Playground 验证**：自动化 smoke test，用 playground 环境验证 RC 可用性
- 📝 **RC 信息记录**：汇总所有产物链接，为 Phase 4 投票邮件做准备

---

### Phase 4: Vote & Verify

**目标**：先在 Slack 内部进行 committer 投票，通过后由 RM 发起 ASF 社区邮件投票，跟踪投票结果，处理通过或失败场景。

**Slack 交互流程：**

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Phase 4: Vote & Verify                                                    │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  Step 1 — Bot 生成投票邮件草稿 + 内部 committer 投票                       │
│                                                                           │
│  RM:  "Draft the vote email."                                             │
│  Bot: 🔍 Checking release state...                                        │
│       Current RC: v1.2.0-rc1 (all artifacts verified ✅)                   │
│       Fetching historical vote email for reference...                     │
│       - v1.1.0-rc2: https://lists.apache.org/thread/yddh62...             │
│       Generating vote email following ASF conventions...                  │
│                                                                           │
│       📧 Draft vote email:                                                │
│       ──────────────────────────────────────────                          │
│       Subject: [VOTE] Release Apache Gravitino 1.2.0 (rc1)               │
│                                                                           │
│       Hi Gravitino community,                                             │
│                                                                           │
│       I'd like to call a vote on releasing Apache Gravitino 1.2.0-rc1.   │
│                                                                           │
│       The release candidate can be found at:                              │
│       https://dist.apache.org/repos/dist/dev/gravitino/v1.2.0-rc1/       │
│                                                                           │
│       Maven staging repo:                                                 │
│       https://repository.apache.org/content/repositories/                 │
│       orgapachegravitino-1042/                                            │
│                                                                           │
│       PyPI: https://pypi.org/project/apache-gravitino/1.2.0rc1/          │
│       Docker: apache/gravitino:1.2.0-rc1                                  │
│       GitHub: https://github.com/apache/gravitino/releases/tag/v1.2.0-rc1│
│                                                                           │
│       Release notes:                                                      │
│       https://github.com/apache/gravitino/blob/branch-1.2/RELEASE.md     │
│                                                                           │
│       The vote will be open for at least 72 hours.                        │
│       [ ] +1 approve                                                      │
│       [ ] +0 no opinion                                                   │
│       [ ] -1 disapprove (with reason)                                     │
│       ──────────────────────────────────────────                          │
│                                                                           │
│       Before sending to the ASF mailing list, let's do an internal review │
│       and verification first.                                             │
│       📢 @committers: Please review the vote email and RC artifacts.     │
│       React with 👍 to approve or 👎 to reject (with reason).            │
│       (Requires 100% approval from all committers to proceed)            │
│       Current: 0/12 votes received, need 12 approvals.                    │
│                                                                           │
│  === 场景 A1: 内部投票不通过 — 邮件问题（不需重建 RC）❌ ===                 │
│                                                                           │
│  Bot: 📊 Internal vote status for v1.2.0-rc1:                            │
│       👍 11 approvals / 👎 1 rejection                                     │
│         • @committer_x: "Vote email has wrong Maven staging repo link"   │
│       ❌ Internal vote not passed (need 100%, got 91%).                    │
│       ⚠️ Issue type: vote email content (no artifact rebuild needed).     │
│       @mchades Please fix the email and re-initiate internal vote.        │
│                                                                           │
│  RM:  "Fixed the staging repo link. Re-vote."                            │
│  Bot: ✅ Email updated: staging repo link corrected.                      │
│       📢 @committers: Vote email fixed. Please re-vote.                  │
│       Changes: corrected Maven staging repo URL.                          │
│       React with 👍 to approve or 👎 to reject.                           │
│       Current: 0/12 votes, need 12 approvals.                             │
│                                                                           │
│  === 场景 A2: 内部投票不通过 — Artifact 问题（需回退重建 RC）❌ ===          │
│                                                                           │
│  Bot: 📊 Internal vote status for v1.2.0-rc1:                            │
│       👍 10 approvals / 👎 2 rejections                                    │
│         • @committer_x: "Release note is missing the Hive catalog fix"   │
│         • @committer_y: "PyPI package has wrong dependency version"      │
│       ❌ Internal vote not passed (need 100%, got 83%).                    │
│       ⚠️ Issue type: artifact/code issues detected.                      │
│       These issues require code changes → must rebuild RC.                │
│       @mchades Recommend: fix issues on branch-1.2, then rebuild RC.     │
│       This will roll back to **Phase 3** (RC number auto-increments).     │
│       [Proceed to fix & rebuild / Discuss further]                        │
│                                                                           │
│  RM:  "Proceed."                                                          │
│  Bot: 🔄 Rolling back to Phase 3...                                      │
│       (→ continues from Phase 3, Step 1 — 场景 B: 自动构建下一个 RC)      │
│                                                                           │
│  === 场景 B: 内部投票通过 ✅ ===                                           │
│                                                                           │
│  Bot: 📊 Internal vote result for v1.2.0-rc1:                            │
│       👍 12 approvals / 👎 0 rejections                                    │
│       ✅ Internal vote passed (12/12 = 100%).                              │
│       @mchades Ready to send the vote email to dev@gravitino.apache.org?  │
│       [Send / Modify / Cancel]                                            │
│                                                                           │
│  Step 2 — RM 确认后发送社区投票邮件                                        │
│                                                                           │
│  RM:  "Send"                                                              │
│  Bot: ✅ Vote email sent to dev@gravitino.apache.org                      │
│       Vote thread: https://lists.apache.org/thread/abc123...              │
│       Vote closes: 2026-03-08 06:00 UTC (72 hours)                       │
│       I'll push vote status updates twice daily (10:00 & 16:00 UTC)      │
│       and you can ask me anytime for a real-time update.                  │
│                                                                           │
│  Step 3 — Bot 定时推送 + 按需查询投票进度                                  │
│                                                                           │
│  Bot: [Scheduled 10:00 UTC] 📊 Daily vote status for v1.2.0-rc1:         │
│       +1: 2 (binding: 2, non-binding: 0)                                 │
│         • @pmc_member_1 (binding) ✅                                      │
│         • @pmc_member_2 (binding) ✅                                      │
│       +0: 0                                                               │
│       -1: 0                                                               │
│       Need at least 3 binding +1 votes. 1 more needed.                   │
│       Time remaining: 48 hours                                            │
│                                                                           │
│  @viewer_a: "What's the current vote status for 1.2.0?"                   │
│  Bot: 📊 Real-time vote status for v1.2.0-rc1:                           │
│       +1: 4 (binding: 3, non-binding: 1)                                 │
│       +0: 1                                                               │
│       -1: 0                                                               │
│       ✅ Minimum binding votes reached (3/3).                             │
│       Time remaining: 24 hours                                            │
│                                                                           │
│  ═══════════════════════════════════════════════════════════════════════   │
│  === Scenario A: Vote Passes ✅ ===                                       │
│  ═══════════════════════════════════════════════════════════════════════   │
│                                                                           │
│  Bot: [Scheduled 16:00 UTC] 🎉 Vote PASSED for v1.2.0-rc1!              │
│       +1: 5 (binding: 3, non-binding: 2)                                 │
│       +0: 1                                                               │
│       -1: 0                                                               │
│       Vote duration: 74 hours (met 72-hour minimum ✅)                    │
│       Binding votes: 3 (met minimum 3 ✅)                                 │
│                                                                           │
│       Phase 4 ✅ Complete → Ready for Phase 5: Publish & Announce         │
│       Shall I proceed? [Yes / Not yet]                                    │
│                                                                           │
│  ═══════════════════════════════════════════════════════════════════════   │
│  === Scenario B: Vote Fails ❌ (回退到 Phase 3) ===                       │
│  ═══════════════════════════════════════════════════════════════════════   │
│                                                                           │
│  Bot: [Scheduled 10:00 UTC] ❌ Vote FAILED for v1.2.0-rc1.               │
│       +1: 2 (binding: 1, non-binding: 1)                                 │
│       +0: 0                                                               │
│       -1: 2 (binding: 2)                                                  │
│         • @pmc_member_3: "Signature verification failed on tarball"       │
│         • @pmc_member_4: "Python client test failure on macOS arm64"      │
│                                                                           │
│       📋 Suggested action items based on -1 feedback:                     │
│       1. Fix GPG signature issue on release tarball                       │
│       2. Fix Python client compatibility on macOS arm64                   │
│       @mchades Shall I create GitHub issues to track these?               │
│       [Create Issues / Modify / Skip]                                     │
│                                                                           │
│  RM:  "Create Issues"                                                     │
│  Bot: ✅ Created GitHub issues:                                            │
│       • #1260 - Fix GPG signature issue for v1.2.0 release                │
│         (labeled: release-1.2.0, priority/critical)                       │
│       • #1261 - Fix Python client test failure on macOS arm64             │
│         (labeled: release-1.2.0, priority/critical)                       │
│                                                                           │
│       Returning to Phase 3 to build RC2 after fixes are applied.          │
│       Phase 4 → Phase 3 (RC2)                                             │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

**Agent 在 Phase 4 中的能力：**
- 📧 **投票邮件生成**：参考历史投票邮件格式，自动填入所有 RC 产物链接
- 🗳️ **内部先行投票**：在 Slack 中先进行 committer 内部审核投票（100% 通过才可发社区邮件），不通过时帮助协调解决
- 📊 **投票进度推送**：每天早晚（10:00 / 16:00 UTC）定时推送状态，支持任何人随时查询实时状态
- ✅ **ASF 规则校验**：自动检查是否满足 ≥3 binding +1 和 ≥72 小时最短投票周期
- 📋 **失败处理**：汇总 -1 反馈生成 action items，RM 确认后自动创建 GitHub issues 追踪
- 🔄 **Phase 回退**：投票失败时自动回退到 Phase 3，与 Phase 3 的 RC 回退流程衔接

---

### Phase 5: Publish & Announce

**门控条件：**
- Phase 4 的 ASF 社区投票已通过（≥3 binding +1, ≥72 hours, no -1 from binding voters）
- 当前用户具有 `release_manager` 角色

```
┌───────────────────────────────────────────────────────────────────────────┐
│  Phase 5: Publish & Announce                                             │
│  Slack Interaction Flow                                                   │
│                                                                           │
│  Step 1 — Finalize Release                                                │
│                                                                           │
│  RM:  "The vote passed. Let's finalize the release."                      │
│  Bot: 🔍 Checking vote result for v1.2.0-rc1...                          │
│       ✅ ASF community vote passed:                                       │
│       +1: 5 (binding: 3, non-binding: 2), -1: 0                          │
│       Vote duration: 76 hours (≥72h requirement met).                     │
│                                                                           │
│       📋 Finalization plan:                                               │
│       1. Run `do-release.sh finalize` — move artifacts from dev → release│
│       2. Close & Release Maven staging repo                               │
│       3. Publish PyPI package (remove rc suffix)                          │
│       4. Mark GitHub Release as official (remove pre-release flag)         │
│       5. Publish Docker image with release tag                            │
│                                                                           │
│       ⚠️ This action is irreversible. Shall I proceed?                   │
│       [Confirm / Cancel]                                                  │
│                                                                           │
│  RM:  "Confirm"                                                           │
│  Bot: 🚀 Finalizing Apache Gravitino 1.2.0...                            │
│       ⏳ Running `do-release.sh finalize`...                              │
│       ✅ SVN: moved from dist/dev → dist/release                          │
│       ✅ Maven: staging repo closed & released                            │
│          https://repository.apache.org/#orgapachegravitino-1042           │
│       ✅ PyPI: apache-gravitino 1.2.0 published                          │
│          https://pypi.org/project/apache-gravitino/1.2.0/                 │
│       ✅ Docker: apache/gravitino:1.2.0 pushed                           │
│       ✅ GitHub: Release v1.2.0 marked as latest                         │
│          https://github.com/apache/gravitino/releases/tag/v1.2.0          │
│       All artifacts finalized. ✅                                         │
│                                                                           │
│  Step 2 — Post-publish Verification                                       │
│                                                                           │
│  Bot: 🔍 Running post-publish verification...                            │
│       📦 Downloading release tarball from dist/release...                 │
│       ✅ SHA-512 checksum: matches                                        │
│       ✅ GPG signature: valid (signed by mchades@apache.org)              │
│       ✅ Maven Central sync: artifacts available                          │
│          https://repo1.maven.org/maven2/org/apache/gravitino/             │
│       ✅ PyPI install test: `pip install apache-gravitino==1.2.0` OK     │
│       ✅ Docker pull test: `docker pull apache/gravitino:1.2.0` OK       │
│       All post-publish checks passed. ✅                                  │
│                                                                           │
│  Step 3 — Update Playground & Website                                     │
│                                                                           │
│  Bot: 📝 Preparing PRs for downstream updates...                         │
│                                                                           │
│       1️⃣ Gravitino Playground:                                           │
│       Updating version from 1.1.0 → 1.2.0 in playground config...       │
│       ✅ PR created: apache/gravitino-playground#89                       │
│          "Update Gravitino version to 1.2.0"                              │
│                                                                           │
│       2️⃣ Gravitino Website (gravitino-site):                             │
│       Generating release page from release notes...                       │
│       ✅ PR created: apache/gravitino-site#115                            │
│          "Add release notes for Apache Gravitino 1.2.0"                   │
│          (ref: gravitino-site#100, gravitino-site#104)                    │
│                                                                           │
│       @mchades Please review and merge when ready.                        │
│       [View PR #89 / View PR #115]                                        │
│                                                                           │
│  Step 4 — Multi-channel Announcement                                      │
│                                                                           │
│  RM:  "Draft the release announcement."                                   │
│  Bot: 🔍 Fetching historical announcement for reference...                │
│       - v1.1.0: https://lists.apache.org/thread/pxvjzpwgs1...             │
│       Generating announcements for all channels...                        │
│                                                                           │
│       📢 ASF Mailing List (announce@apache.org):                          │
│       ──────────────────────────────────────────                          │
│       Subject: [ANNOUNCE] Apache Gravitino 1.2.0 Released                 │
│                                                                           │
│       The Apache Gravitino community is pleased to announce               │
│       the release of Apache Gravitino 1.2.0.                              │
│                                                                           │
│       Apache Gravitino is a high-performance, geo-distributed,            │
│       and federated metadata/data lake.                                    │
│                                                                           │
│       Download: https://gravitino.apache.org/downloads/                   │
│       Release Notes: https://github.com/apache/gravitino/...              │
│       Website: https://gravitino.apache.org/                               │
│       ──────────────────────────────────────────                          │
│                                                                           │
│       📢 Slack / WeChat / LinkedIn:                                       │
│       ──────────────────────────────────────────                          │
│       🎉 Apache Gravitino 1.2.0 is released!                             │
│                                                                           │
│       Key highlights:                                                      │
│       • Hive catalog performance improvements                             │
│       • New Iceberg REST catalog support                                   │
│       • Python client enhancements                                         │
│                                                                           │
│       📦 Download: https://gravitino.apache.org/downloads/               │
│       📄 Release Notes: https://github.com/apache/gravitino/...          │
│       ──────────────────────────────────────────                          │
│                                                                           │
│       @mchades Review the announcements?                                  │
│       [Send All / Modify / Send Individually]                             │
│                                                                           │
│  RM:  "Send All"                                                          │
│  Bot: ✅ Announcements sent:                                              │
│       • ASF announce@apache.org ✅                                        │
│       • ASF dev@gravitino.apache.org ✅                                   │
│       • Slack #gravitino-release ✅                                       │
│       • WeChat group ✅                                                   │
│       • LinkedIn ✅                                                       │
│       All channels notified. 📢                                           │
│                                                                           │
│  Step 5 — Bump to Next Snapshot Version                                   │
│                                                                           │
│  Bot: 📝 Preparing version bump PR for main branch...                    │
│       Updating version: 1.2.0 → 1.3.0-SNAPSHOT                          │
│       Files to update:                                                     │
│       • gradle.properties (version=1.3.0-SNAPSHOT)                        │
│       • clients/client-python/pyproject.toml                               │
│       • docs/open-api/openapi.yaml                                         │
│       • ... (12 files total)                                               │
│                                                                           │
│       ✅ PR created: apache/gravitino#1285                                │
│          "Bump version to 1.3.0-SNAPSHOT after 1.2.0 release"             │
│       @mchades Please review and merge.                                   │
│                                                                           │
│  Step 6 — Release Complete Summary                                        │
│                                                                           │
│  Bot: 🎉 Apache Gravitino 1.2.0 release is complete!                     │
│                                                                           │
│       📊 Release Summary:                                                 │
│       ────────────────────                                                │
│       Version:       1.2.0                                                 │
│       Release Manager: @mchades                                           │
│       Timeline:      2026-02-15 → 2026-03-12 (25 days)                   │
│       RC Attempts:   1 (rc1 passed)                                        │
│       Commits:       148 commits from 23 contributors                     │
│       Issues Closed: 86 issues, 12 improvements, 3 bug fixes             │
│                                                                           │
│       📦 Artifacts:                                                       │
│       • SVN: dist.apache.org/repos/dist/release/gravitino/1.2.0/         │
│       • Maven: repo1.maven.org/maven2/org/apache/gravitino/              │
│       • PyPI: pypi.org/project/apache-gravitino/1.2.0/                    │
│       • Docker: apache/gravitino:1.2.0                                    │
│       • GitHub: github.com/apache/gravitino/releases/tag/v1.2.0          │
│                                                                           │
│       🗳️ Vote:                                                            │
│       • Internal: 12/12 committers approved (100%)                        │
│       • Community: +1: 5 (3 binding), -1: 0, duration: 76h               │
│                                                                           │
│       📢 Announcements sent to 5 channels.                               │
│       📝 Next version: 1.3.0-SNAPSHOT (PR #1285)                         │
│                                                                           │
│       Thank you to all contributors and voters! 🙏                       │
│       Release checklist archived. ✅                                      │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

**Agent 在 Phase 5 中的能力：**
- 🚀 **Finalize 执行**：自动执行 `do-release.sh finalize`，完成 SVN/Maven/PyPI/Docker/GitHub 全链路发布
- 🔍 **发布后验证**：自动下载产物验证签名、校验和，确认 Maven Central 同步，测试 pip/docker 安装
- 📝 **下游更新**：自动向 playground 和 website 提交 PR，附带历史 PR 参考
- 📢 **多渠道公告**：参考历史公告格式，为 ASF 邮件 / Slack / WeChat / LinkedIn 生成对应公告
- 🔄 **版本升级**：自动扫描需要更新版本号的文件，提交 snapshot 版本 PR
- 📊 **Release 总结**：生成完整的 release 报告（时间线、统计、产物链接、投票结果）

---

## 待讨论问题

1. **数据预填充**：Demo 时是从空白开始，还是预先填入一些历史 release 数据？
2. **真实 vs 模拟**：是否需要 demo 中真实调用 Gravitino 的 release 脚本（如 `do-release.sh`），还是仅做数据层面的管理？
3. **通知机制**：当 checklist 步骤被完成时，是否需要 bot 主动通知 Slack channel？
4. **User Identity Propagation**：Slack 用户身份如何传播到 ADP 的 RBAC 层？候选方案见 [`adp-integration-with-release-agent.md` — Section 3](./adp-integration-with-release-agent.md#user-identity-propagation-to-be-discussed)

---

## 参考资料

- Release Checklist: `docs/checklist_for_gravitino_release.md`
- ADP Hypervisor 源码: 当前仓库 `src/adp_hypervisor/`
- Gravitino 源码: `/Users/mchades/projects/datastrato/graviton`
- Gravitino Release Scripts: `/Users/mchades/projects/datastrato/graviton/dev/release/`
