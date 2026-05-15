# MORK CLI Integration (Docker)

This document covers how the backend runs the MORK CLI through Docker, how to build the
MORK image, how to prepare ACT files, and how to query the API.

## Overview

- One long-running `mork:latest` container is kept alive per dataset path per worker
  process. Queries are dispatched via `docker exec` (~100 ms) instead of spawning a new
  container per query (~1–2 s). The session restarts automatically if the container
  crashes and is cleaned up on process exit.
- The dataset directory is mounted into the container at the same path.
- For large chromosomal queries the backend caps results at `QUERY_MAX_NODES` (default
  200 000) and enriches node properties with one batch query per property type rather
  than one query per node.

## Prerequisites

- Docker (with `docker-ce-cli` available inside Celery worker containers — provided by
  the bundled `Dockerfile`)
- The `mork:latest` image built locally (see step 1)

## 1) Build the MORK image (one-time)

From the repo root:

```bash
docker build --network host -f app/services/mork/Dockerfile.mork -t mork:latest .
```

Notes:
- The first build is slow because it compiles PathMap and MORK from source.
- Rebuild only if you need a newer MORK/PathMap version.

## 2) Set the data directory

In `.env` (copy from `example.env`):

```plaintext
MORK_DATA_DIR=/absolute/path/to/your/metta_out
# For multi-species deployments you can also set:
# HUMAN_MORK_DATA_DIR=...
# FLY_MORK_DATA_DIR=...
```

## 3) Configure config.yaml

```yaml
database:
  type: mork_cli
  human:
    data_dir: /absolute/path/to/metta_out
    act_file: human_v6.act          # filename of your ACT binary
    graph_info_path: ./Data/graph_info/hsa_v6.json
```

## 4) Build the ACT file

```bash
python scripts/build_act.py
```

This generates `$MORK_DATA_DIR/<act_file>` from the `.metta` files in that directory.

## 5) Run the backend

```bash
docker compose up -d
```

Or for local dev:

```bash
flask run --port 5000
```

## 6) Query the API

Example — single gene lookup:

```bash
curl -s -X POST "http://localhost:5000/query" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "nodes": [{"type": "gene", "node_id": "n1", "id": "", "properties": {"gene_name": "IGF1"}}],
    "predicates": [],
    "source": ["all"],
    "species": "human"
  }'
```

## Query Generator Selection

`config/config.yaml` `database.type`:

| Value | Backend |
|-------|---------|
| `cypher` | Neo4j |
| `metta` | MeTTa files |
| `mork_cli` | MORK binary via Docker (recommended) |

## Troubleshooting

- **`Missing ACT file`**: run `python scripts/build_act.py`.
- **`Failed to start mork:latest container`**: the image hasn't been built yet. Run the
  `docker build` command in step 1.
- **Empty results / no error**: check that `mork:latest` exists (`docker images mork`).
- **Permission denied on data dir**: ensure `MORK_DATA_DIR` is readable/writable by your
  user (the container runs as `uid:gid` of the host process).
- **Docker not found inside container**: the `Dockerfile` installs `docker-ce-cli` and
  mounts `/var/run/docker.sock` — make sure those are present in `docker-compose.yml`.