# Conversation Model

## Scope

The app stores each conversation as an ordered event timeline. The first stable boundary is the conversation and event model, not the current hard-coded template implementation.

This model covers:

- user messages
- orchestrator messages
- agent messages
- tool calls and tool results
- abnormal backend termination

Prompt versions, tool versions, model versions, flow definitions, and attachment storage are expected to become referenced resources later.

## Conversation

A conversation is a container with metadata and an ordered event list.

Recommended metadata keys:

| Key | Type | Notes |
|-----|------|-------|
| `title` | string | optional display title |
| `description` | string | optional longer note |
| `tagList` | string array | optional user labels |
| `statusText` | string | `active`, `completed`, `archived`, `failed`, or later status |
| `templateKey` | string | template key used by the orchestrator |
| `templateName` | string | display name copied from the template |
| `modelText` | string | current model label when useful |
| `sourceText` | string | `manual`, `experiment`, or other source |
| `isUserTurn` | boolean | true when user input should be enabled |
| `endStatusText` | string | optional final status such as `abnormal` |
| `evetList` | string array | ordered list of event IDs |

`evetList` is intentionally documented with the current stored spelling. A later migration can rename it once all code and existing data can move together.

Trashbin state is stored on the conversation row as `isInTrashbin`. Missing values should be treated as `false`.

## Event

An event is one append-first timeline item. Event order is controlled by the parent conversation metadata list.

Common event fields:

| Field | Notes |
|-------|-------|
| `id` | event ID returned as a string |
| `conversationId` | parent conversation ID returned as a string |
| `typeText` | canonical event type during development |
| `subtypeText` | canonical event subtype during development |
| `contentType` | content storage mode from config |
| `contentText` | text content when used |
| `contentJson` | structured content when used |
| `metadata` | optional event metadata |

## Event Types

During development, `typeText` and `subtypeText` are canonical. Numeric code fields can remain null until values stabilize.

Initial `typeText` values:

| typeText | Notes |
|----------|-------|
| `userMessage` | user-originated event |
| `orchestratorMessage` | backend or orchestrator event |
| `agentMessage` | model-originated event |
| `EndAbnormal` | conversation ended because the backend could not continue |

Initial `subtypeText` values:

| typeText | subtypeText | Notes |
|----------|-------------|-------|
| `userMessage` | `textSimple` | plain user text |
| `orchestratorMessage` | `textSimple` | plain orchestrator text |
| `agentMessage` | `textSimple` | plain model text |
| `agentMessage` | `toolCall` | model requested tool execution |
| `orchestratorMessage` | `toolResult` | tool execution result |
| `EndAbnormal` | `BackendException` | backend exception detail in `contentText` |

When a template startup or turn fails after a conversation exists, the backend should append `EndAbnormal` with subtype `BackendException`, set `statusText` to `failed`, and disable user input with `isUserTurn = false`.

Free chat conversations should use `templateKey = free-talk`, `statusText = active`, and `isUserTurn = true` at creation time.

One-shot templates such as `mcp-tool-all` should set `statusText` to `completed` and `isUserTurn` to false after startup finishes.

When an interactive tool call returns `is_terminated = true`, the backend should set `statusText` to `completed`, set `isUserTurn` to false, and keep the termination reason in metadata when available.

## Content Types

Content type values are resolved through `config/conversation_content_type.yaml`.

Initial usage:

| contentType | Meaning | Column rule |
|-------------|---------|-------------|
| `1` | text | `contentText` is required, `contentJson` is null |
| `2` | json | `contentJson` is required, `contentText` is null |
| `3` | text with structured data | both columns may be used |

For pure text conversation, use `contentType = 1`.

For tool results and later structured messages, `contentType = 3` should preserve the exact text sent to the agent in `contentText` and store displayable structured data in `contentJson`.

Structured `contentJson` uses a versioned segment envelope:

```json
{
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
      "data": { "status": "success" },
      "outputSchema": {},
      "displayRules": {}
    },
    {
      "type": "text",
      "data": "\nTools already completed: tool_web_fetch."
    }
  ]
}
```

Initial segment types:

| type | Notes |
|------|-------|
| `text` | plain text segment |
| `json` | structured JSON segment |

`displayRules` is an optional map of dot-paths to display behavior. The first supported behavior is `popup`, meaning the normal message card may show an abbreviated preview and provide a full-value popup.

## Service Rules

- Conversation creation allocates a new conversation ID.
- Event creation allocates a new event ID.
- Every event insert updates parent conversation ordering and update time.
- Event creation and parent conversation update must be in one transaction.
- Conversation delete should remove the conversation and all child events in one transaction.
- Events should be read in conversation order.
