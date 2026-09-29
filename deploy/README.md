# Server deployment

This setup builds the frontend as a standalone Next.js Node server, runs the
FastAPI backend separately, and keeps Elasticsearch on an internal Docker
network. Nginx serves both frontend and API on port 80. Add a domain and HTTPS
before inviting visitors to use the site.

The commands below assume a Linux x86-64 server with Docker Compose. Allow at
least 4 GB of RAM; 8 GB leaves more room for Elasticsearch and builds. Build
and restore on the server instead of transferring `.next` or Python virtual
environments from Windows.

## Transfer

Copy the project source, the local `analysis-ik-9.5.4.zip` into `deploy/`, and
the latest `place-literally-es-*.zip` snapshot archive to the server. The plugin
archive and snapshot are intentionally ignored by Git; a Git clone alone does
not contain them. Do not transfer local `.env` files or API keys in an archive.
The prepared `place-literally-server-20260929T114248Z.zip` bundle contains all
three inputs. Unzip it and run the remaining commands from its
`place-literally/` directory.

The snapshot archive contains a `repository/` directory and `manifest.json`.
From the project root on the server:

```sh
mkdir -p deploy/snapshots
unzip place-literally-es-20260929T114248Z.zip -d deploy/snapshots
docker compose -f deploy/compose.yml build
docker compose -f deploy/compose.yml up -d elasticsearch
```

Wait until the Elasticsearch container is healthy. Then register the copied
repository read-only and restore both business indices into the empty data
volume:

```sh
docker compose -f deploy/compose.yml exec -T elasticsearch curl -fsS \
  -X PUT 'http://127.0.0.1:9200/_snapshot/transfer' \
  -H 'Content-Type: application/json' \
  -d '{"type":"fs","settings":{"location":"/usr/share/elasticsearch/snapshots/repository","readonly":true}}'

docker compose -f deploy/compose.yml exec -T elasticsearch curl -fsS \
  -X POST 'http://127.0.0.1:9200/_snapshot/transfer/place-literally-20260929t114248z/_restore?wait_for_completion=true' \
  -H 'Content-Type: application/json' \
  -d '{"indices":"features-v10,place-feedback-v1","include_global_state":false}'

docker compose -f deploy/compose.yml exec -T elasticsearch curl -fsS \
  'http://127.0.0.1:9200/features-v10,place-feedback-v1/_count'
```

The expected document counts for this archive are 13,881 features and 2
feedback records. Elasticsearch's `_cat/indices` count also includes nested
documents, so it is larger. A restore to an existing index will fail; do not
delete an existing data volume merely to retry these commands.

## Start

```sh
# Optional: set this server-side secret to enable vector similarity queries.
export DASHSCOPE_API_KEY='your-key'
docker compose -f deploy/compose.yml up -d api web proxy
curl -fsS 'http://127.0.0.1/atlas-api/map-features?limit=1'
```

The frontend calls `/atlas-api/*` on the same origin. Nginx forwards those
requests to FastAPI's `/api/*`; neither Elasticsearch nor FastAPI has a public
port. The vector cache uses a named volume and survives container replacement.
Nginx limits feedback and vector requests per client IP. The feedback endpoint
remains anonymous; configure HTTPS and public-edge abuse controls before
inviting visitors to submit feedback.

Never expose Elasticsearch's port 9200 to the internet. Keep the snapshot ZIP
off the web root and protect the server's Docker access. If you later take a
new snapshot, replace the archive and snapshot name in the restore commands.
