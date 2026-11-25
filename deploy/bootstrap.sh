#!/usr/bin/env bash
# First deployment of one customer's stack (README). Safe to run again: secrets, keys and the
# admin account are created only when missing.
#
#   ./bootstrap.sh            bundled Ollama (pulls the models, about 6 GB)
#   USE_HOST_OLLAMA=1 ./bootstrap.sh   an Ollama the machine already runs (models already there)
#   DEMO=1 ./bootstrap.sh     also write the fictional demo company's knowledge
set -euo pipefail
cd "$(dirname "$0")"

CHAT_MODEL_DEFAULT="qwen3:8b"
EMBED_MODEL="bge-m3:567m"

log() { printf '\n== %s\n' "$*"; }
secret() { openssl rand -hex "${1:-24}"; }
env_get() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
env_set() {  # replace or append KEY=value in .env (value written as is)
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  grep -vE "^$key=" .env > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" .env
  chmod 600 .env
}

[ -f .env ] || { cp .env.example .env; chmod 600 .env; }
for key in POSTGRES_PASSWORD GLASSDESK_DB_PASSWORD STEWARD_DB_PASSWORD LITERAG_DB_PASSWORD; do
  [ -n "$(env_get $key)" ] || env_set "$key" "$(secret 16)"
done
[ -n "$(env_get GLASSDESK_SESSION_SECRET)" ] || env_set GLASSDESK_SESSION_SECRET "$(secret 32)"
[ -n "$(env_get STEWARD_ADMIN_TOKEN)" ] || env_set STEWARD_ADMIN_TOKEN "$(secret 32)"
CHAT_MODEL="$(env_get CHAT_MODEL)"; CHAT_MODEL="${CHAT_MODEL:-$CHAT_MODEL_DEFAULT}"

PROFILE=()
if [ "${USE_HOST_OLLAMA:-0}" = 1 ]; then
  env_set OLLAMA_URL "http://host.docker.internal:11434"
else
  PROFILE=(--profile ollama)
fi
# bash 3.2 (macOS) treats an empty array as unset under `set -u`
compose() { docker compose ${PROFILE[@]+"${PROFILE[@]}"} "$@"; }

log "building images (steward and lite-rag come from GitHub at pinned commits)"
compose build

log "database"
compose up -d --wait db

if [ "${USE_HOST_OLLAMA:-0}" != 1 ]; then
  log "Ollama and its models ($CHAT_MODEL, $EMBED_MODEL)"
  compose up -d ollama
  until compose exec -T ollama ollama list >/dev/null 2>&1; do sleep 2; done
  compose exec -T ollama ollama pull "$CHAT_MODEL"
  compose exec -T ollama ollama pull "$EMBED_MODEL"
else
  log "using the host's Ollama: checking it has $CHAT_MODEL and $EMBED_MODEL"
  tags="$(curl -fsS http://127.0.0.1:11434/api/tags)" || { echo "no Ollama on 127.0.0.1:11434"; exit 1; }
  for m in "$CHAT_MODEL" "$EMBED_MODEL"; do
    grep -q "\"$m\"" <<<"$tags" || { echo "the host's Ollama lacks $m: ollama pull $m"; exit 1; }
  done
fi

if [ -z "$(env_get STEWARD_LITERAG_API_KEY)" ]; then
  log "lite-rag key for steward"
  out="$(compose run --rm --no-deps -T lite-rag literag key create --name llm-steward --namespace 'steward/*' --mode write)"
  key="$(sed -n 's/^key (shown once, give it to llm-steward): //p' <<<"$out")"
  entry="$(tail -1 <<<"$out")"
  [ -n "$key" ] && [ "${entry:0:1}" = "{" ] || { echo "unexpected output from literag key create"; exit 1; }
  env_set STEWARD_LITERAG_API_KEY "$key"
  env_set LITERAG_SERVER__KEYS "[$entry]"
fi

log "lite-rag and steward"
compose up -d --wait lite-rag steward

if [ -z "$(env_get GLASSDESK_STEWARD_API_KEY)" ]; then
  log "steward namespace, its keyword rules and glassdesk's key (read, write, review)"
  compose exec -T steward steward ns create glassdesk --name glassdesk >/dev/null
  compose cp ./steward-ns.yaml steward:/tmp/steward-ns.yaml
  compose exec -T steward steward ns apply -f /tmp/steward-ns.yaml
  key="$(compose exec -T steward steward key create glassdesk --scope read --scope write --scope review --name glassdesk | tail -1 | tr -d '\r')"
  [[ "$key" == stw_* ]] || { echo "unexpected output from steward key create"; exit 1; }
  env_set GLASSDESK_STEWARD_API_KEY "$key"
fi

log "glassdesk"
compose up -d --wait glassdesk

if [ -z "$(env_get ADMIN_PASSWORD_SHOWN)" ]; then
  password="$(secret 12)"
  printf '%s\n' "$password" | compose exec -T glassdesk glassdesk user create admin --role admin --password-stdin
  env_set ADMIN_PASSWORD_SHOWN 1
  log "admin account: admin / $password   (shown once; change it by creating another admin)"
fi

if [ "${DEMO:-0}" = 1 ]; then
  log "demo knowledge (every title starts with [演示])"
  compose exec -T glassdesk glassdesk seed --demo
fi

log "ready: http://127.0.0.1:$(env_get GLASSDESK_PORT | grep . || echo 8740)"
