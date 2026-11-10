#!/bin/sh
# Run from the experiment-pilot root.
set -eu
target=${1:?usage: sh deploy/backup.sh /secure/path/pilot.dump}
test ! -e "$target" || { printf '%s\n' "Backup already exists" >&2; exit 1; }
umask 077
temp=$(mktemp "${target}.XXXXXX")
trap 'rm -f "$temp"' EXIT HUP INT TERM
docker compose --env-file .env.production -f compose.prod.yaml exec -T db \
  pg_dump --format=custom --no-owner --no-acl -U pilot -d pilot >"$temp"
ln "$temp" "$target"
printf '%s\n' "Backup written to $target"
