# glassdesk 设计文档：过程可见的企业知识助手

2026-11-25 · 状态：草稿，待 owner 审批

## 1. 意图

**glassdesk** 是给某个企业客户**演示或交付**的知识助手 app：客户的员工向 agent 提问，agent 从受治理的知识库（KB）
和记忆里找答案，每句回答都带出处；对话中出现的新知识按治理规则进入 KB（自动 / 问用户 / 专家审核），也可以手工录入。
它的卖点是**过程可见**（glass box）：每次回答，客户都能在页面上看到 agent 做了什么——调了哪些工具、查到哪些段落、
花了多少钱和时间。

它同时是 lite-ai 这套栈的**第一个面向终端用户的 app**：用真实的 app 把 lite-agent、llm-steward（及其背后的
lite-rag / lite-mem）、lite-model 串起来，暴露各模块接口上的问题（已知缺口：token streaming、跨模块 tracing）。

### 目标

- 一个客户一套部署（docker compose），能在客户面前现场演示，也能交付给客户自己运行。
- 聊天：答案带引用；agent 的每一步实时推到页面（步骤级流式）。
- 执行过程页面：任意一次回答都能展开看完整的时间线（工具调用、检索结果、模型调用、token / 成本 / 耗时）。
- 知识进入 KB 的三条路：AI 自动判断（低风险自动生效）、问用户（确认卡片）、手工录入（条目或上传文档）。
- 知识库页面：文档、条目及其状态、待确认 / 待审核的 candidate、"KB 缺什么"。
- 可换品牌（客户名、logo、主色），可换模型端点（客户自己的 Ollama / OpenAI 兼容 / LiteLLM）。

### 非目标（v1 不做）

- 多租户 SaaS、公开注册、计费。一套部署只服务一个客户。
- 自己实现 RAG、记忆、治理：全部交给 llm-steward（它再交给 lite-rag / lite-mem / WeKnora）。
- token 级流式输出：lite-model 目前不做 streaming（`lite-model/docs/lite-model-design.md:46`），v1 只做步骤级流式；
  token 流式是后续阶段，要先改 lite-model（见 §10）。
- 跨模块统一 tracing（OpenTelemetry 等）：v1 的时间线来自 lite-agent 自己的 event log。
- 通用 agent 平台、可视化编排、插件市场。

### 反目标（做出来也算失败的情况）

- agent 能**直接写**生效的 KB 条目。agent 只能提议（生成 candidate），与 steward 规则 5（MCP 只能提议）一致。
- 回答编造出处：引用必须对应真实检索到的段落。
- 执行过程页面泄露密钥、API key、内部 URL 或原始 system prompt。
- 演示时依赖 owner 的 llm-gateway 订阅：客户部署必须用客户自己能用的模型端点。

## 2. 方案（已选 ①）

| 方案 | 做法 | 取舍 |
| --- | --- | --- |
| **① 自己的 FastAPI backend，以库的方式用 lite-agent（选定）** | backend 内定义 agent 与工具，用 `lite_agent.Agent` + `PgSessionStore` 跑 run，自己提供 HTTP / SSE、鉴权和页面需要的接口；KB 与记忆通过 llm-steward 的 Python SDK（HTTP）访问 | 客户相关的定制（鉴权、品牌、工具、页面数据形状）全在 glassdesk；steward 和 lite-agent 保持通用 |
| ② 直接用 `liteagent serve`，glassdesk backend 只做一层转发 | 代码最少 | lite-agent 的 HTTP 壳只绑 loopback、没有鉴权（lite-agent design §10），接口和数据形状被通用壳定死，客户定制要回头改库 |
| ③ 塞进 llm-steward 当一个新页面 | 部署最少 | 违反 steward 的非目标（"不做聊天应用或 agent 框架"），客户定制会污染通用服务 |

owner 于 2026-11-25 选定 ①。

## 3. 总体架构

```
浏览器（frontend：React SPA）
   │ REST + SSE（同源，经 backend）
   ▼
glassdesk backend（FastAPI，:8740）
   ├─ 鉴权、会话、品牌配置
   ├─ agent 运行：lite_agent.Agent（role 走 lite-model）+ PgSessionStore（数据库 glassdesk）
   │     工具：search_knowledge / propose_knowledge / …（§5）
   ├─ 时间线：读 lite-agent event log → 投影成页面用的步骤（§6）
   └─ llm-steward SDK（HTTP，namespace = 本客户）
            │
            ▼
   llm-steward（:8600）── KB provider（lite-rag / WeKnora / native）、memory provider（lite-mem）
            │
   lite-model ──HTTP──► 客户的模型端点（Ollama / OpenAI 兼容 / LiteLLM Proxy）
```

规则：

1. **glassdesk 不 import llm-steward**（workspace 规则），只用 `llm-steward-client` 的 HTTP 模式（不用 `embedded`）。
2. **每次 LLM 调用都走 lite-model role**（workspace 约定），role 名在配置里，不写死模型 id。
3. **KB 的写入只经过 steward**：glassdesk 自己不存知识；它只存 agent 的会话事件（lite-agent）和 app 自己的数据
   （用户、会话列表、品牌配置）。
4. **测试不调真实 LLM、不调真实 steward**：用 lite-model 的 `AsyncFakeModel` 和 steward 的假实现（§9）。

## 4. 页面

```
┌──────────────────────────────────────────────────────────────────────┐
│ [客户 logo] glassdesk    聊天 | 知识库 | 洞察            用户 ▾      │
├──────────────┬───────────────────────────────────┬───────────────────┤
│ 会话列表     │ 用户：报销上限是多少？            │ 执行过程           │
│ · 报销政策   │                                   │ ● 理解问题  0.4s   │
│ · 入职流程   │ 助手：差旅住宿上限每晚 800 元[1]，│ ● search_knowledge │
│              │ 超出需部门审批[2]。               │   "报销 上限"       │
│ + 新会话     │   [1] 差旅制度 v3 §2.1            │   → 5 条，top 0.82 │
│              │   [2] 条目「超标审批」(verified)  │ ● 生成回答  2.1s   │
│              │                                   │ ─────────────────  │
│              │ ┌ 要不要存进知识库？ ──────────┐  │ tokens 1.8k · $0.002│
│              │ │「海外差旅上限每晚 150 美元」 │  │ 总耗时 3.0s        │
│              │ │ [存为团队知识] [只给我] [不要]│  │                   │
│              │ └──────────────────────────────┘  │                   │
│              │ [输入框…]                  [发送] │                   │
└──────────────┴───────────────────────────────────┴───────────────────┘
```

| 页面 | 内容 |
| --- | --- |
| 聊天 | 会话列表；消息流；回答里的引用可点开看原文段落；确认卡片（steward 的 `suggestions[]`）；右侧执行过程面板实时更新 |
| 执行过程 | 单次回答的完整时间线（可从聊天点开；有固定 URL，**只有本部署的登录用户能看**，v1 不做公开分享链接——owner 2026-11-25 决定）：每一步的类型、输入摘要、输出摘要、耗时、token、成本（端点不报成本时显示"未知"，不显示 0）；失败步骤标红 |
| 知识库 | 上传文档；手工新建条目；条目列表（状态 active / verified / deprecated、出处、命中次数）；待确认和待审核的 candidate；reviewer 可批准 / 拒绝 |
| 洞察 | "KB 缺什么"（检索分低的高频问题）、回答的好评 / 差评、每日用量与成本 |

## 5. Agent 与工具

一个 agent（`desk`），role 例如 `desk.answer`（具体模型在 lite-model 配置里）。工具：

| 工具 | 背后 | 说明 |
| --- | --- | --- |
| `search_knowledge(query)` | steward `retrieve`（memory + KB 联合检索，带当前用户 scope） | 返回段落、来源、分数；回答的引用只能来自这里的结果 |
| `propose_knowledge(title, content, reason)` | steward `suggest` | 生成 candidate，按 steward 的风险策略走（自动 / 问用户 / 审核）；agent 不能直接写生效条目 |
| `get_entry(entry_id)` | steward `entry_get` | 读一条条目全文（引用展开用） |

每轮对话结束后，backend 把这一轮的消息交给 steward `episode_add`（`mode=sync`，steward 负责抽取记忆、打 KB
价值分、生成 candidate），把返回的 `suggestions[]` 推给前端显示卡片。用户在卡片上的决定调用
`candidate_accept` / `candidate_reject`。（`mode=sync` 会让回答后多等一次 LLM 调用；卡片在回答之后异步出现，
不阻塞回答显示——实现者的决定。）

手工录入：知识库页面调用 `entry_create` / `document_upload`。

**Collection**（实现者的决定，owner 可改）：一个客户默认一个 collection `company`，由 `glassdesk setup`
（以及 `seed --demo`）创建，风险路由用 steward 默认策略（low 自动、medium 问用户、high 审核），再加一条演示用的
high 关键词规则，使三条写入路径在同一套配置下都能触发（G2 的 e2e 依赖这一点）。多 collection（按部门）以后按客户
需要再加。

### 后台数据与审计（实现者的决定）

- **洞察数据**：steward 的 KB 缺口、命中统计、用量只在 `/admin/v1`（`/admin/v1/ns/{slug}/stats`、
  `retrieval-logs?gaps=true`）上。backend 代持 `STEWARD_ADMIN_TOKEN`（只在服务器 `.env`，从不下发到浏览器），
  用一个很薄的 HTTP 客户端读这两个接口——owner 2026-11-25 决定，不改 steward。
- **审核身份**：backend 只代持一把 `review` 权限的 steward key，steward 的 change_log 里所有审核都记成同一个
  actor。glassdesk 自己记一张审计表（谁、何时、对哪个 candidate / 条目、做了什么），并把 glassdesk 用户名写进
  steward 决定的 `reason` / `note` 字段。让 steward 接收代理的 reviewer 身份是以后的跨 repo 改动，v1 不做。
- **回答反馈**：UI 对整条回答打好评 / 差评。glassdesk 存一份回答级反馈（洞察页的好评率用它）；同时把同一个评分
  记到这条回答**引用过的**每一项上（steward `feedback(retrieval_id, item_id, helpful)`），让 steward 的
  反馈驱动复审能工作。没被引用的检索结果不记。

## 6. 执行过程（时间线）

- 数据源：lite-agent 的 event log（`PgSessionStore`，数据库 `glassdesk`）。每次 run 的事件里已有 run 开始 / 结束、
  模型调用（含 usage）、工具调用与结果。
- backend 把事件**投影**成页面用的步骤（`step: {kind, title, input_summary, output_summary, started_at,
  duration_ms, usage, cost, status}`），只暴露摘要，不暴露 system prompt、密钥或内部 URL（反目标）。
- 实时：`GET /api/sessions/{id}/stream` 用 SSE 推送新步骤（做法参照 lite-agent HTTP 壳的 `events/stream`）。
- 引用：回答里的引用编号映射到 `search_knowledge` 结果里的段落；对不上的引用不显示链接，并在时间线上标记。

## 7. 鉴权与用户（v1）

- 部署内的本地账号：管理员在 CLI 里创建用户（`glassdesk user create`），角色 `member` / `reviewer` / `admin`。
- `reviewer` 能在知识库页面批准 / 拒绝 candidate（对应 steward 的 `review` 权限 API key，由 backend 代持）。
- glassdesk 用户 id 作为 steward 的 `user_id` scope，每个用户有自己的记忆。
- 客户 SSO（OIDC）留到有客户要求时再做。

## 8. 技术栈与部署

- backend：Python 3.12、uv、FastAPI、Pydantic v2、SQLAlchemy async + Alembic（app 自己的表），`lite-agent[pg]`
  （release wheel，当前 0.2.4，与 workspace 的 lite-model 0.8.0 一致），`llm-steward-client`（0.1.0 没有
  release，用 `git+…/llm-steward@<commit>#subdirectory=sdk/python` 固定到 commit）。
- frontend：pnpm、React + Vite + TypeScript、TanStack Router / Query、shadcn/ui + Tailwind、Playwright；
  客户端从 backend 的 OpenAPI 生成；确认卡片复用或参照 `@llm-steward/widget` 的 `SuggestionCard`。
- 数据库：共享 PG 上新建数据库 `glassdesk`（app 表 + lite-agent 的 session schema）。
- 端口：backend `127.0.0.1:8740`，frontend dev `8741`，e2e `8742`（写进 workspace AGENTS.md 的端口表）。
- 部署（owner 2026-11-25 决定：一体化 Ollama）：一个客户一个 docker compose，包含 glassdesk（backend 同时
  托管前端静态文件）、llm-steward（KB provider **lite-rag**，memory provider **lite-mem**）、PG + pgvector、
  **Ollama**（chat 模型 + embedding 模型 bge-m3）。不依赖客户的云账号，离线也能演示；代价是需要一台性能够的机器，
  部署文档要写明最低配置（内存 / GPU / 磁盘）。具体 chat 模型由实现者按选模型流程定（`llm-model-eval` skill），
  写进 lite-model 配置。换成客户的 OpenAI 兼容端点只是改 lite-model 配置，v1 不做验证。品牌配置放在一个 yaml 里（客户名、logo、主色、欢迎语、示例问题）。
- **一个部署一个 backend 进程**：「这个会话是否有 run 在跑」记在进程内存里（`runs.py`），同一会话同时只允许一个 run；
  多 worker 或多副本需要先把这个状态移到数据库或事件日志里（run 没有 `run_finished` 就是还在跑）。
- 演示数据：`glassdesk seed --demo` 写入一套虚构公司的文档和条目（明确标注是演示数据），演示完可清除。

## 9. 测试

- 单元 / 集成：`AsyncFakeModel` 驱动 agent；steward 用 HTTP 层的假实现（`respx` 或进程内假服务），断言工具调用的
  请求和投影出的时间线步骤。
- e2e：Playwright 跑生产构建，后端用 fake model + 假 steward；关键流程：提问 → 时间线出现 → 回答带引用 →
  确认卡片 → 知识库里出现 candidate。
- 可选的真实运行（`-m live`）：本地 Ollama + 本地 steward，只在 owner 要求时跑。

## 10. 阶段

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| G0 骨架 | 仓库、backend / frontend 骨架、检查命令（ruff、mypy、pytest、typecheck、lint、build）、CI | 所有检查在空项目上通过 |
| G1 竖切：一问一答 | 登录 → 聊天 → agent 调 `search_knowledge` → 带引用的回答；时间线经 SSE 实时显示 | e2e：提问后时间线出现搜索步骤，回答引用可点开 |
| G2 知识进入 KB | episode 上报、确认卡片、`propose_knowledge`、知识库页面（上传、手工条目、candidate、审核） | e2e：三条写入路径各一条 |
| G3 洞察与反馈 | 回答反馈（steward `feedback`）、KB 缺口、用量成本 | 页面数据与 steward 返回一致 |
| G4 交付 | compose、品牌配置、演示数据、部署文档，从零部署验证 | 一台干净机器按文档部署成功 |
| 后续 | 跨 repo 的改进（G1 审查记下）：lite-agent 导出 run 登记与事件流轮询，供 glassdesk 复用；`ToolResultEvent` 带结构化数据，引用不再单独存 `run_passages` 表、也不再从文本里数条数；lite-agent 加每个 run 的轮数上限（现在预算按整个会话累计，glassdesk 设为 200 轮） | 另行规划 |
| 后续 | token 流式（先改 lite-model）、跨模块 tracing、SSO | 另行规划 |

## 11. 留给实现者决定的

- 目录结构、模块划分、具体表结构。
- 引用格式（回答里的编号与 `search_knowledge` 结果的对应方式）。
- 时间线步骤的分组和文案、投影的细节。
- 假 steward 的形式（respx 还是进程内服务）。
- 前端组件库细节、`SuggestionCard` 是复用还是参照重写（取决于 widget 能否在 steward 仓库外安装）。

## 12. 阶段记录

### G0 + G1（2026-11-25，分支 `feat/g0-g1`）

- 完成：仓库与检查命令；本地账号登录（签名 cookie，带 `session_version`，退出后旧 cookie 失效）；`desk` agent 与
  `search_knowledge`；事件日志投影为步骤与带引用的回答；会话、提问（同一会话同时只有一个 run，409）、SSE 步骤流
  （游标续传，结尾 `answer` + `end`）；聊天页（会话列表、问答、引用弹窗、执行过程面板）；`glassdesk serve --fake`
  演示模式；e2e（登录 → 提问 → 时间线 → 引用）。
- 与计划的偏差（详见计划执行记录）：lite-model 配置放在 `GLASSDESK_LLM__*`（同 llm-steward），不是单独文件；
  预算 200 轮（lite-agent 预算按会话累计）；e2e 由 backend 直接托管构建好的前端（8743），8742 暂未使用；
  e2e 暂不进 CI（需要 PG）。
- 收尾中修掉的问题：引用段落按 `call_id` 跨 run 分组，端点每轮重复用同一 call id 时会串引用（改为按 run 分组）；
  SSE 每 250ms 读整段日志（改为只读新事件）；引用编号改为**整个会话连续编号**（原来每次搜索都从 [1] 开始，
  搜两次时 [1] 会指错来源）；首次 run 未写入就中断的会话不再永久失效；run 无法完成时流里发 `failed`；
  搜索结果不完整时时间线标"部分结果"；失败的回答显示提示而不是空白；流被浏览器放弃（如 401）时发送按钮恢复。
- 延后（G2 前后再处理）：
  - 运行中断在工具调用中间（`tool_started` 无结果）时，下一次提问会报 `UnresolvedCalls`，需要用 lite-agent 的
    `resume` 把这些调用标为结果未知；现在这次提问会以 `failed` 显示。
  - 发送按钮在 POST 返回前没有防重复点击，双击会看到一次误导的"上一个问题还在处理中"。
  - 登录 cookie 的 `Secure` 取决于请求协议；放在终止 TLS 的反向代理后面时要给 uvicorn 加 `--proxy-headers`
    （G4 部署文档写明，或做成设置）。
  - 会话预算是整个会话 200 次模型调用（约 100 个问题），超出后回答以失败显示；需要 lite-agent 提供每个 run 的上限。
  - `keep()` 写数据库失败时会把一次成功的搜索标成失败。

### G2（2026-11-25，分支 `feat/g2`）

- 完成：三条写入路径都经过 steward——回答之后上报 episode（steward 抽取、打分，medium 风险出确认卡片）、
  agent 的 `propose_knowledge`、知识库页面手工录入条目与上传文档；卡片在聊天里确认（存为团队知识 / 只给我 / 不要）；
  知识库页面（条目、文档、待审核），审核员批准或拒绝并写 `review_audit`；演示模式里"记住…"会触发提议；
  e2e 覆盖提议 → 确认 → 生效，以及高风险条目 → 审核 → 已验证。
- 授权：steward 信任持 key 的服务器传来的任何 `user_id`，所以"这张卡片是不是你的"由 glassdesk 在决定前检查
  （只认该用户的待确认卡片）；审核只认 steward 的待审核队列（审核 key 能决定任何 candidate）。
- 回答不等 steward 抽取：run 一结束就放开会话、发出回答；上报 episode 在会话占用之外进行，流跟到它结束再发卡片和 `end`。
- 与计划的偏差：steward 的建议接口没有 `reason` 字段，`propose_knowledge` 的理由只给模型看；steward 没有按 id
  取 candidate 的接口，归属检查用列表的第一页（一个用户待确认的卡片超过一页时，旧卡片会 404）。
- 延后：真实 steward 上的高风险关键词规则是命名空间配置（`steward ns apply`），API key 改不了，G4 的部署文档写明；
  演示模式里的关键词规则只在假 steward 里。

### G3（2026-11-25，分支 `feat/g3`）

- 完成：回答下的 有帮助 / 没帮助（每人每个回答一条，最新的算数；同一个评价重复点不会再发给 steward）；评价按回答引用过的
  每一项转给 steward 的 feedback；每次 run 记一行用量（抛异常的 run 也记为失败）；洞察页（审核员 / 管理员）：
  部署时区内最近 7 天的回答、失败、tokens、成本（未知成本不算 0，单独计数；全未知显示"未知"）、好评率（未评价的不进分母；
  没有评价显示"—"）、steward 的知识库统计和"知识库缺什么"（Admin API，未配置或连不上时显示"未配置"）；演示模式标"演示数据"。
- 已知局限：用户改主意（有帮助 → 没帮助）时 steward 会再记一次相反的评价，同一个人被算两次——steward 没有按人覆盖评价的接口；
  要准确需要 steward 按 (retrieval, item, user) 存一条（跨 repo，以后再说）。
- 收尾中修掉：上一个回答刚出现、run 还没放开会话时提问会被 409（提问最多等 3 秒）。
