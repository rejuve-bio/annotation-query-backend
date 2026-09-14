# WebSocket / Real-Time API

The annotation service uses **Socket.IO over WebSocket** for real-time query progress updates.  
The underlying transport is `websocket` only (no long-polling fallback).

> **Note:** Socket.IO events are not part of the OpenAPI spec and will not appear in the endpoint list below. This section documents the full real-time contract.

---

## Connection

### Endpoint
```
ws://<host>/
```

The Socket.IO server is mounted at the root of the ASGI app. Connect using any Socket.IO client library.

### Authentication
Pass your JWT token as a query parameter on connect:

```js
const socket = io("wss://api.example.com", {
  transports: ["websocket"],
  auth: { token: "<JWT>" }
});
```

---

## Client → Server Events

### `connect`
Emitted automatically by the Socket.IO client on connection.  
The server responds with a `message` event confirming the connection.

---

### `join`
Subscribe to real-time updates for a specific annotation query.  
Must be emitted immediately after connecting and receiving the `annotation_id` from the REST API.

**Payload:**
```json
{
  "room": "<annotation_id>"
}
```

**Behavior:**  
If the annotation result is already cached (query completed before the client connected), the server immediately emits an `update` event with the current status and graph availability.

---

## Server → Client Events

### `message`
Sent once on successful connection.

**Payload:**
```json
"Connected to server"
```

---

### `update`
The primary real-time event. Emitted to the annotation's room whenever any part of the query pipeline completes or changes state.

**Payload structure:**
```json
{
  "status": "<task_status>",
  "annotation_id": "<annotation_id>",
  "update": { }
}
```

The `update` object varies depending on which pipeline stage triggered the event:

#### Graph ready
```json
{
  "status": "pending",
  "annotation_id": "64a1f3c2b0e4a12d3c8f9e01",
  "update": {
    "graph": true
  }
}
```

#### Total node/edge count
```json
{
  "status": "pending",
  "annotation_id": "64a1f3c2b0e4a12d3c8f9e01",
  "update": {
    "node_count": 142,
    "edge_count": 318
  }
}
```

#### Count by label
```json
{
  "status": "pending",
  "annotation_id": "64a1f3c2b0e4a12d3c8f9e01",
  "update": {
    "node_count_by_label": [
      { "label": "gene", "count": 84 },
      { "label": "disease", "count": 58 }
    ],
    "edge_count_by_label": [
      { "label": "is_implicated_in", "count": 318 }
    ]
  }
}
```

#### Summary ready (query complete)
```json
{
  "status": "complete",
  "annotation_id": "64a1f3c2b0e4a12d3c8f9e01",
  "update": {
    "summary": "This graph shows 84 genes implicated in breast cancer..."
  }
}
```

#### Query failed
```json
{
  "status": "failed",
  "annotation_id": "64a1f3c2b0e4a12d3c8f9e01",
  "update": {
    "graph": false
  }
}
```

#### Query cancelled
```json
{
  "status": "cancelled",
  "annotation_id": "64a1f3c2b0e4a12d3c8f9e01",
  "update": {
    "summary": "Summary cancelled"
  }
}
```

---

## Task Status Values

| Status | Description |
|---|---|
| `pending` | Query is running — partial results may be available |
| `complete` | All pipeline stages finished successfully |
| `failed` | One or more pipeline stages encountered an unrecoverable error |
| `cancelled` | The user cancelled the query |

---

## Pipeline Stages

A single annotation query runs four parallel Celery tasks. Each fires its own `update` event independently:

| Stage | Celery Task | `update` key emitted |
|---|---|---|
| Graph data | `graph_task` | `graph: true/false` |
| Total count | `total_count_task` | `node_count`, `edge_count` |
| Count by label | `label_count_task` | `node_count_by_label`, `edge_count_by_label` |
| AI summary | `summary_task` | `summary` |

The final `complete` status is set only after all four stages finish.

---

## Typical Client Flow

```
1. POST /api/v1/graph/query          → { annotation_id: "64a1..." }
2. socket.emit("join", { room: "64a1..." })
3. socket.on("update", handler)

Updates received in any order:
  → { status: "pending", update: { graph: true } }
  → { status: "pending", update: { node_count: 142, edge_count: 318 } }
  → { status: "pending", update: { node_count_by_label: [...], edge_count_by_label: [...] } }
  → { status: "complete", update: { summary: "..." } }

4. GET /api/v1/graph/<annotation_id>  → fetch full graph JSON
```

---

## Queue Behaviour

Complex queries (high-cardinality predicates like `coexpressed_with`, `eqtl_association`, `expressed_in`, or queries with 4+ predicates) are routed to the **slow queue**. If the slow queue has more than 20 pending tasks, the query is rejected immediately with `status: failed` and an error message explaining the queue is full.

Simple queries run on the **fast queue** and are processed with lower latency.
