# glassdesk 部署（一个客户一套）

这套 compose 包含：glassdesk（网页 + API）、llm-steward（知识库治理，知识用 lite-rag、记忆用 lite-mem）、
PostgreSQL（三个库：glassdesk、steward、lite_rag）、Ollama（聊天模型 qwen3:8b、向量模型 bge-m3:567m）。
只有 glassdesk 对外（绑在本机 127.0.0.1），其余服务只在 compose 的内部网络里。

## 机器要求

- Docker 24+（含 compose v2）、`openssl`、`curl`、`git`（构建时 Docker 从 GitHub 拉 steward 和 lite-rag 的源码）。
- 内存 16 GB 起（qwen3:8b 约 6 GB，加上数据库和三个服务）；磁盘 20 GB 起（镜像约 6 GB，模型约 6 GB）。
- 有 GPU 更快；纯 CPU 也能跑，一次回答几十秒。
- 能访问 Docker Hub、GitHub、Ollama 模型库（首次部署时）。

## 第一次部署

```bash
git clone https://github.com/ArthurGao/glassdesk.git && cd glassdesk/deploy
cp .env.example .env          # 改客户名称、颜色、欢迎语、示例问题、时区
./bootstrap.sh                # 自带 Ollama，会下载约 6 GB 模型
# 机器上已经有 Ollama 且有这两个模型：USE_HOST_OLLAMA=1 ./bootstrap.sh
# 演示用：DEMO=1 ./bootstrap.sh（写入一家虚构公司的知识，标题都带"[演示]"）
```

`bootstrap.sh` 做的事（可以重复运行，已有的不会重建）：

1. 生成数据库密码、会话密钥、steward 的 Admin token，写进 `deploy/.env`（权限 600，不要提交）。
2. 构建镜像（glassdesk 用本仓库；steward、lite-rag 用 GitHub 上固定的 commit）。
3. 启动数据库；自带 Ollama 时拉取模型。
4. 生成 lite-rag 给 steward 用的 key。
5. 启动 lite-rag、steward；在 steward 里建命名空间 `glassdesk`，应用 `steward-ns.yaml` 的高风险关键词规则，
   生成 glassdesk 用的两把 key：日常读写用的（read、write），和只用于审核的（read、write、review）。
   steward 把带审核权限的 key 自己写入的内容当作已审核，所以两把不能合成一把。
6. 启动 glassdesk，创建管理员 `admin`，**密码只打印一次**。

结束时打印访问地址，默认 http://127.0.0.1:8740 。

## 日常

```bash
cd deploy
docker compose --profile ollama up -d      # 开（用宿主机 Ollama 时去掉 --profile ollama）
docker compose --profile ollama down       # 关（数据在 volume 里，不会丢）
docker compose logs -f glassdesk           # 看日志
docker compose exec glassdesk glassdesk user create alice --role member     # 加用户（会提示输入密码）
docker compose exec glassdesk glassdesk user create rita --role reviewer    # 审核员：能看"待审核"和"洞察"
```

角色：`member` 提问、确认卡片、录入知识；`reviewer` 另外能审核和看洞察；`admin` 同 reviewer。

## 让其他人访问（HTTPS）

glassdesk 只监听本机。给其他人用时，在前面放一个终止 TLS 的反向代理（Caddy、Nginx），转发到
`127.0.0.1:8740`，并在 `.env` 里设 `GLASSDESK_SERVE_FLAGS=--proxy-headers`，然后
`docker compose up -d glassdesk`。这样登录 cookie 会带 `Secure`。Caddy 的例子：

```
desk.example.com {
    reverse_proxy 127.0.0.1:8740
}
```

## 高风险关键词

`steward-ns.yaml` 里的 `high_risk_keywords`：标题或内容含这些词的知识（手工录入、AI 提议、上传文档的标题）
一律进审核队列，审核员批准前不会生效。改完后：

```bash
docker compose cp ./steward-ns.yaml steward:/tmp/steward-ns.yaml
docker compose exec steward steward ns apply -f /tmp/steward-ns.yaml
```

## 演示数据

`DEMO=1 ./bootstrap.sh` 或 `docker compose exec glassdesk glassdesk seed --demo` 写入"示例科技"的 6 条知识，
标题都以"[演示] "开头（其中一条含"价格"，会进审核队列，用来演示审核）。重复运行不会重复写入。
正式使用前删掉：在 steward 里停用这些条目（标题以"[演示]"开头的），或者部署一套新的。

## 换模型

改 `.env` 的 `CHAT_MODEL`，自带 Ollama 时先 `docker compose exec ollama ollama pull <模型>`，然后
`docker compose up -d steward glassdesk`。向量模型（bge-m3:567m）绑定在已建的索引上，不要改。

## 备份

数据都在 volume `pgdata`（三个库）里：

```bash
docker compose exec -T db pg_dumpall -U postgres > backup.sql
```
