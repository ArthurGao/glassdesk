# glassdesk deployment (one per customer)

This compose stack contains: glassdesk (web + API), llm-steward (knowledge-base governance, using lite-rag for
knowledge and lite-mem for memory), PostgreSQL (three databases: glassdesk, steward, lite_rag), and Ollama (chat model
qwen3:8b, embedding model bge-m3:567m). Only glassdesk is exposed (bound to 127.0.0.1 on the machine); the other
services are only on compose's internal network.

## Machine requirements

- Docker 24+ (with compose v2), `openssl`, `curl`, `git` (during the build Docker pulls the steward and lite-rag source
  from GitHub).
- Memory from 16 GB (qwen3:8b takes about 6 GB, plus the database and three services); disk from 20 GB (images about
  6 GB, models about 6 GB).
- A GPU is faster; CPU only also works, with an answer taking tens of seconds.
- Access to Docker Hub, GitHub and the Ollama model library (at the first deployment).

## First deployment

```bash
git clone https://github.com/ArthurGao/glassdesk.git && cd glassdesk/deploy
cp .env.example .env          # change the UI language (LOCALE), customer name, colour, welcome text, sample questions, time zone
./bootstrap.sh                # brings its own Ollama, downloads about 6 GB of models
# the machine already has Ollama with these two models: USE_HOST_OLLAMA=1 ./bootstrap.sh
# for demos: DEMO=1 ./bootstrap.sh (writes the knowledge of a fictional company, all titles carry "[演示]" (demo))
```

What `bootstrap.sh` does (it can be re-run; what already exists is not rebuilt):

1. Generates the database password, the session secret and steward's Admin token, and writes them into `deploy/.env`
   (permissions 600, do not commit it).
2. Builds the images (glassdesk from this repository; steward and lite-rag from pinned commits on GitHub).
3. Starts the databases; with the bundled Ollama, pulls the models.
4. Generates the key lite-rag gives to steward.
5. Starts lite-rag and steward; creates the namespace `glassdesk` in steward, applies the high-risk keyword rules of
   `steward-ns.yaml`, and generates the two keys glassdesk uses: one for everyday reads and writes (read, write), and
   one used only for review (read, write, review). Steward treats content written by a key with review permission as
   already reviewed, so the two cannot be merged into one.
6. Starts glassdesk and creates the administrator `admin`; **the password is printed only once**.

At the end it prints the access address, by default http://127.0.0.1:8740 .

## Day to day

```bash
cd deploy
docker compose --profile ollama up -d      # start (drop --profile ollama when using the host's Ollama)
docker compose --profile ollama down       # stop (data is in volumes and is not lost)
docker compose logs -f glassdesk           # view logs
docker compose exec glassdesk glassdesk user create alice --role member     # add a user (prompts for a password)
docker compose exec glassdesk glassdesk user create rita --role reviewer    # reviewer: can see "待审核" (pending review) and "洞察" (Insights)
```

Roles: `member` asks questions, confirms cards and enters knowledge; `reviewer` can also review and see Insights
(洞察); `admin` is the same as reviewer.

## Letting other people in (HTTPS)

glassdesk listens only on the local machine. To let other people use it, put a TLS-terminating reverse proxy (Caddy,
Nginx) in front of it, forward to `127.0.0.1:8740`, set `GLASSDESK_SERVE_FLAGS=--proxy-headers` in `.env`, and then run
`docker compose up -d glassdesk`. This way the login cookie carries `Secure`. A Caddy example:

```
desk.example.com {
    reverse_proxy 127.0.0.1:8740
}
```

## High-risk keywords

`high_risk_keywords` in `steward-ns.yaml`: knowledge whose title or content contains these words (manual entry, AI
proposals, the title of an uploaded document) always goes into the review queue and does not take effect until a
reviewer approves it. After changing it:

```bash
docker compose cp ./steward-ns.yaml steward:/tmp/steward-ns.yaml
docker compose exec steward steward ns apply -f /tmp/steward-ns.yaml
```

## Demo data

`DEMO=1 ./bootstrap.sh` or `docker compose exec glassdesk glassdesk seed --demo` writes 6 knowledge items of "示例科技"
(Example Tech), all with titles starting "[演示] " (demo) (one of them contains "价格" (price) and goes into the review
queue, to demonstrate review). Running it again does not write duplicates. Before real use, remove them: deactivate
these entries in steward (the ones whose title starts with "[演示]"), or deploy a fresh stack.

## Changing the model

Change `CHAT_MODEL` in `.env`; with the bundled Ollama, first run `docker compose exec ollama ollama pull <model>`, then
`docker compose up -d steward glassdesk`. The embedding model (bge-m3:567m) is bound to the index already built, so do
not change it.

## Backup

All data is in the volume `pgdata` (three databases):

```bash
docker compose exec -T db pg_dumpall -U postgres > backup.sql
```
