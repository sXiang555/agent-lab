#!/bin/sh
# Isolated launch rehearsal with an internal TLS root. Run from the project root.
set -eu
qa_dir=$(mktemp -d)
project="experiment-pilot-qa-$$"
export PILOT_SECRETS_DIR="$qa_dir/secrets"
export PILOT_SITE_ADDRESS=localhost
export PILOT_BIND_IP=127.0.0.1
export PILOT_HTTP_PORT=${PILOT_QA_HTTP_PORT:-18080}
export PILOT_HTTPS_PORT=${PILOT_QA_HTTPS_PORT:-18443}
export PILOT_PUBLIC_SHOWCASE=1
export PILOT_REQUESTS_PER_MINUTE=12
compose() { docker compose --env-file /dev/null -p "$project" -f compose.prod.yaml "$@"; }
cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    compose ps || true
    compose logs --tail=60 caddy web api db || true
  fi
  compose down --volumes --remove-orphans || true
  rm -rf "$qa_dir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

python3 deploy/init_secrets.py "$PILOT_SECRETS_DIR"
compose config --quiet
compose up --build --wait --wait-timeout 200
attempt=0
while ! compose cp caddy:/data/caddy/pki/authorities/local/root.crt "$qa_dir/root.crt" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  [ "$attempt" -lt 20 ] || exit 1
  sleep 1
done
smoke() {
  uv run --locked python deploy/prod_smoke.py "$1" --url "https://localhost:$PILOT_HTTPS_PORT" \
    --ca "$qa_dir/root.crt" --secrets-dir "$PILOT_SECRETS_DIR" --state "$qa_dir/review.json"
}
redirect=$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' "http://localhost:$PILOT_HTTP_PORT/")
[ "$redirect" = 308 ]
smoke prepare
compose restart db
smoke resume
compose exec -T db pg_dump --format=custom --no-owner --no-acl -U pilot -d pilot >"$qa_dir/pilot.dump"
compose exec -T db pg_restore --list <"$qa_dir/pilot.dump" >"$qa_dir/backup-list"
test -s "$qa_dir/backup-list"
compose exec -T db createdb -U pilot pilot_restore_check
compose exec -T db pg_restore --exit-on-error --no-owner --no-acl -U pilot \
  -d pilot_restore_check <"$qa_dir/pilot.dump"
restored_jobs=$(compose exec -T db psql -U pilot -d pilot_restore_check -Atqc 'SELECT count(*) FROM pilot_queue')
[ "$restored_jobs" = 1 ]
printf '%s\n' "Production HTTPS, Postgres recovery, approval and backup verification passed"
