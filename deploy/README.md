# Server deployment

This setup builds the frontend as a standalone Next.js Node server, runs the
FastAPI backend separately, and keeps Elasticsearch on an internal Docker
network. Caddy serves the public domain over HTTPS and forwards requests to an
internal Nginx proxy, which routes the frontend and API and applies rate limits.

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
docker compose -f deploy/compose.yml up -d api web proxy gateway
curl -fsS 'http://127.0.0.1/atlas-api/map-features?limit=1'
```

The default public hostname is `place-literally.duckdns.org`; set
`PUBLIC_DOMAIN` in the Compose environment to use another hostname. Point its
DNS A record at the server and allow inbound TCP ports 80 and 443 in the cloud
firewall. Caddy obtains and renews the certificate automatically, storing it in
the persistent `caddy_data` volume. Domain HTTP requests redirect to HTTPS;
direct-IP HTTP access remains available for diagnostics.

The frontend calls `/atlas-api/*` on the same origin. Nginx forwards those
requests to FastAPI's `/api/*`; neither Elasticsearch nor FastAPI has a public
port. Vector similarity uses the precomputed vectors in Elasticsearch and needs
no model API key or query cache. A model key is only needed for offline embedding
generation when adding or updating meanings.
Nginx limits feedback and vector requests per client IP. The feedback endpoint
remains anonymous; add public-edge abuse controls before inviting visitors to
submit feedback.

Never expose Elasticsearch's port 9200 to the internet. Keep the snapshot ZIP
off the web root and protect the server's Docker access. If you later take a
new snapshot, replace the archive and snapshot name in the restore commands.
