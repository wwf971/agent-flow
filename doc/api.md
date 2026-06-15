# API Design

## Response Contract

All endpoints return JSON:

```json
{
  "code": 0,
  "data": {}
}
```

Rules:

- `code = 0` means completed without error.
- `code < 0` means failure.
- `data` is optional.
- `message` is optional and only included when useful.
- IDs are returned as strings.
- Event objects use `id`.
- Conversation APIs accept and return `conversationId`, which maps to `conversation.id`.

## Route Prefix

Use `/api` for backend routes.

Initial route groups:

- `/api/conversation/*`
- `/api/event/*`
- `/api/orchestrator/*`
- `/api/config/*`
- `/api/service/*`

IDs are passed through query params for `GET` and request body for `POST`, not path variables.

## Conversation Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/conversation/create` | create one conversation |
| `GET` | `/api/conversation/get` | get one conversation metadata row |
| `GET` | `/api/conversation/list` | list conversations |
| `POST` | `/api/conversation/metadata/update` | update metadata only |
| `POST` | `/api/conversation/delete` | delete one conversation and its events |

### `POST /api/conversation/create`

Request:

```json
{
  "metadata": {
    "title": "Tokyo train delay check",
    "tagList": ["experiment"]
  },
  "timezone": 540
}
```

Response:

```json
{
  "code": 0,
  "data": {
    "conversationId": "115321661721788416",
    "metadata": {
      "evetList": [],
      "title": "Tokyo train delay check",
      "tagList": ["experiment"]
    }
  }
}
```

### `GET /api/conversation/get`

Query:

```text
conversationId=115321661721788416
```

Response data:

```json
{
  "conversationId": "115321661721788416",
  "metadata": {
    "evetList": []
  },
  "createAt": "2026-06-02T00:45:00.000+09:00",
  "createAtTimezone": 540,
  "updateAt": "2026-06-02T00:45:00.000+09:00",
  "updateAtTimezone": 540
}
```

### `GET /api/conversation/list`

Query:

```text
pageIndex=1&pageSize=30&searchText=train
```

Response data:

```json
{
  "pageIndex": 1,
  "pageSize": 30,
  "totalCount": 1,
  "items": [
    {
      "conversationId": "115321661721788416",
      "metadata": {
        "evetList": ["115321665654145024"],
        "title": "Tokyo train delay check"
      },
      "createAt": "2026-06-02T00:45:00.000+09:00",
      "createAtTimezone": 540,
      "updateAt": "2026-06-02T00:46:00.000+09:00",
      "updateAtTimezone": 540
    }
  ]
}
```

List should order by `updateAt desc, conversationId desc`.

### `POST /api/conversation/metadata/update`

Request:

```json
{
  "conversationId": "115321661721788416",
  "metadata": {
    "title": "New title",
    "tagList": ["experiment", "web"]
  },
  "timezone": 540
}
```

This replaces the whole metadata object. Partial metadata updates can be added later if needed.

Backend should preserve or normalize `metadata.evetList`; clients should not use this endpoint to reorder events in the first version.

### `POST /api/conversation/delete`

Request:

```json
{
  "conversationId": "115321661721788416"
}
```

The first version can physically delete conversation and events. If archived conversations become important, use metadata `statusText = archived` instead of this endpoint.

## Event Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/event/create` | append one event |
| `GET` | `/api/event/list` | list events in one conversation |
| `GET` | `/api/event/get` | get one event |
| `POST` | `/api/event/update` | update event content and metadata |
| `POST` | `/api/event/delete` | delete one event |

### `POST /api/event/create`

Request for plain text:

```json
{
  "conversationId": "115321661721788416",
  "typeText": "userMessage",
  "subtypeText": "textSimple",
  "contentType": 1,
  "contentText": "Can you compare Tang and Song dynasties?",
  "metadata": {},
  "timezone": 540
}
```

Response data:

```json
{
  "conversationId": "115321661721788416",
  "id": "115321665654145024",
  "typeText": "userMessage",
  "subtypeText": "textSimple",
  "contentType": 1,
  "contentText": "Can you compare Tang and Song dynasties?",
  "contentJson": null,
  "metadata": {}
}
```

Backend assigns:

- `id`
- time fields

The first version only appends at the end of a conversation. The backend inserts the event row and appends the event ID to `conversation.metadata.evetList` inside one transaction.

### `GET /api/event/list`

Query:

```text
conversationId=115321661721788416&pageIndex=1&pageSize=100
```

Response data:

```json
{
  "conversationId": "115321661721788416",
  "pageIndex": 1,
  "pageSize": 100,
  "items": [
    {
      "id": "115321665654145024",
      "typeText": "userMessage",
      "subtypeText": "textSimple",
      "contentType": 1,
      "contentText": "Can you compare Tang and Song dynasties?",
      "contentJson": null,
      "metadata": {},
      "createAt": "2026-06-02T00:45:00.000+09:00",
      "createAtTimezone": 540
    }
  ]
}
```

Events should be ordered by `conversation.metadata.evetList`.

### `POST /api/event/update`

Request:

```json
{
  "id": "115321665654145024",
  "contentType": 1,
  "contentText": "Can you compare Tang and Song dynasties in three points?",
  "contentJson": null,
  "metadata": {},
  "timezone": 540
}
```

This endpoint is optional for first implementation. It is useful for manually repairing experiment logs.

## Orchestrator Endpoint

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/orchestrator/turn/create` | add user event, call agent, store generated events |

### `POST /api/orchestrator/turn/create`

This is the main endpoint for pure text conversation.

Request:

```json
{
  "conversationId": "115321661721788416",
  "messageText": "What came after the Tang dynasty?",
  "timezone": 540,
  "metadata": {}
}
```

If `conversationId` is omitted, backend creates a new conversation first.

Response data:

```json
{
  "conversationId": "115321661721788416",
  "eventUser": {
    "id": "115321665654145024",
    "typeText": "userMessage",
    "subtypeText": "textSimple",
    "contentType": 1,
    "contentText": "What came after the Tang dynasty?"
  },
  "eventAgent": {
    "id": "115321666178433024",
    "typeText": "agentMessage",
    "subtypeText": "textSimple",
    "contentType": 1,
    "contentText": "After Tang came the Five Dynasties and Ten Kingdoms period, followed by the Song dynasty."
  }
}
```

For first implementation, this endpoint can rebuild model context by reading event IDs from `conversation.metadata.evetList` and selecting text events.

Context conversion:

| Event | Model role |
|-------|------------|
| `userMessage` + `textSimple` | `user` |
| `agentMessage` + `textSimple` | `assistant` |
| `orchestratorMessage` + `textSimple` | `user` or system-like instruction, depending on experiment |

Tool and sub-agent events should not be added to model context until the later orchestrator logic explicitly supports them.

For events with `contentType = 3`, `contentText` is the raw text form and `contentJson` is the structured form. Tool results should keep the exact agent-facing message in `contentText` and may use a segment envelope in `contentJson`:

```json
{
  "typeText": "orchestratorMessage",
  "subtypeText": "toolResult",
  "contentType": 3,
  "contentText": "Tool result: {\"status\":\"success\"}",
  "contentJson": {
    "metadata": {
      "schemaVersion": 1,
      "kind": "toolResult",
      "toolName": "tool_web_fetch"
    },
    "data": [
      {
        "type": "text",
        "data": "Tool result: "
      },
      {
        "type": "json",
        "data": {
          "status": "success",
          "text": "long extracted text"
        },
        "outputSchema": {},
        "displayRules": {
          "text": "popup"
        }
      },
      {
        "type": "text",
        "data": "\nTools already completed: tool_web_fetch."
      }
    ]
  }
}
```

## Config Endpoint

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/config/content-type/list` | read content type mapping |

Response data:

```json
{
  "items": [
    {
      "contentType": 1,
      "name": "text",
      "activeColumn": "contentText"
    },
    {
      "contentType": 2,
      "name": "json",
      "activeColumn": "contentJson"
    }
  ]
}
```

The backend should load this from `config/conversation_content_type.yaml`.

## Service Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health/ping` | public service health check |
| `GET` | `/api/health/database` | database config and bootstrap status |
| `POST` | `/api/service/database/reinit` | run `database/init_table.sql` |

`POST /api/service/database/reinit` requires write permission. It should drop and recreate the conversation tables according to `doc/database.md` as reflected in `database/init_table.sql`.

Response data:

```json
{
  "isReinitialized": true
}
```

## Authorization Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/login` | login with username and password |
| `POST` | `/login/token` | restore login with existing token |
| `GET` | `/login/check` | check current login |

Authenticated requests can provide token by bearer header, `X-Auth-Token`, `authToken` query param, or cookie.

Write endpoints require `W` permission. Read endpoints require `R` permission.

## Error Codes

Initial code values:

| Code | Meaning |
|------|---------|
| `0` | completed without error |
| `-1` | generic failure |
| `-10` | invalid request |
| `-20` | not found |
| `-30` | model call failed |
| `-40` | content type is not supported |

## Transaction Rules

- Conversation create and event create run in transactions.
- `/api/orchestrator/turn/create` should create the user event, call the model, then store the agent event.
- If model call fails after user event is stored, store an `orchestratorMessage` event with failure metadata and return `code < 0`.
- Parent conversation `updateAt` should be updated whenever an event changes.
