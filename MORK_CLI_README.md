# MORK CLI Integration (Docker)

This document covers how the backend runs the MORK CLI through Docker, how to build the MORK image, how to prepare ACT files, and how to query the API.

## Overview

- The backend calls a local wrapper script.
- The wrapper runs the MORK CLI inside a Docker container.
- The dataset directory is mounted into the container at the same path.
- Each query spawns a short-lived container.

## Prerequisites

- Docker with WSL integration enabled (if on WSL)
- Python venv already set up for the backend

## 1) Build the MORK image (one-time)

From the repo root:

```bash
docker build --network host -f app/services/mork/Dockerfile.mork -t mork:latest .
```

Notes:
- The first build is slow because it compiles PathMap and MORK.
- Rebuild only if you need newer MORK/PathMap commits.

## 2) Set the data directory

In `.env`:

```plaintext
MORK_DATA_DIR=/absolute/path/to/your/data
```

The directory must contain your `.metta` files and the generated `annotation.act`.

## 3) Build the ACT file

```bash
python scripts/build_act.py
```

This generates:

```
$MORK_DATA_DIR/annotation.act
```

## 4) Run the backend

```bash
flask run --port 5000
```

## 5) Query the API

Example:

```bash
curl -s -X POST "http://localhost:5000/query" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "requests": {
      "nodes": [
        {"type": "transcript", "node_id": "t1", "id": "", "properties": {}},
        {"type": "protein", "node_id": "p1", "id": "Q9NU02", "properties": {}}
      ],
      "predicates": [
        {"type": "translates_to", "predicate_id": "p0", "source": "t1", "target": "p1"}
      ]
    }
  }'
```

## How the wrapper works

- Wrapper script: `scripts/mork_docker_wrapper.py`
- It runs:

```bash
docker run --rm \
  -u "<uid>:<gid>" \
  -v "$MORK_DATA_DIR:$MORK_DATA_DIR:rw" \
  -v /dev/shm:/dev/shm \
  -w "$MORK_DATA_DIR" \
  mork:latest \
  /app/MORK/target/release/mork <args>
```

## Query Generator Selection

Update `config/config.yaml` to choose the query generator:

- `cypher`
- `metta`
- `mork_cli` (Dockerized MORK CLI)

Make sure this matches your data and `.env` settings.

## Troubleshooting

- **No such file or directory**: `annotation.act` is missing. Run `python scripts/build_act.py`.
- **Permission denied**: ensure `MORK_DATA_DIR` is writable by your user.
- **Docker not found (WSL)**: enable Docker Desktop WSL integration.
