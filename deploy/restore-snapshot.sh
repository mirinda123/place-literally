#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
compose=(sudo docker compose -f deploy/compose.yml)

for index in features-v10 place-feedback-v1; do
    status=$("${compose[@]}" exec -T elasticsearch curl -sS -o /dev/null \
        -w '%{http_code}' "http://127.0.0.1:9200/$index")
    if [[ "$status" != 404 ]]; then
        echo "Refusing to restore: $index returned HTTP $status (expected 404)." >&2
        exit 1
    fi
done

"${compose[@]}" exec -T elasticsearch curl -fsS -X PUT \
    'http://127.0.0.1:9200/_snapshot/transfer' \
    -H 'Content-Type: application/json' \
    --data '{"type":"fs","settings":{"location":"/usr/share/elasticsearch/snapshots/repository","readonly":true}}'
echo

"${compose[@]}" exec -T elasticsearch curl -fsS -X POST \
    'http://127.0.0.1:9200/_snapshot/transfer/place-literally-20260929t114248z/_restore?wait_for_completion=true' \
    -H 'Content-Type: application/json' \
    --data '{"indices":"features-v10,place-feedback-v1","include_global_state":false}'
echo

for index in features-v10 place-feedback-v1; do
    "${compose[@]}" exec -T elasticsearch curl -fsS \
        "http://127.0.0.1:9200/$index/_count"
    echo
done
