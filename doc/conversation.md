# Conversation Model

## Scope

The app stores each conversation as an ordered event timeline. The stable boundary is the conversation and event model, not template implementation details.

This model covers:

- user messages
- orchestrator messages
- agent messages
- tool calls and tool results
- subagent start, result, and return events
- abnormal backend termination

Prompt versions, tool versions, model versions, flow definitions, and attachment storage can be referenced resources.

## Relationship To Orchestrator

The conversation model describes durable state.

The orchestrator model describes how state changes. An orchestrator reads conversation metadata and ordered events, then produces new events. Backend code persists those events and related metadata changes.

The conversation document owns event meaning and storage rules. The orchestrator document owns template selection, iteration input, model calls, tool loops, and subagent flow.

## Conversation

A conversation is a container with metadata and an ordered event list.

Recommended metadata keys:

| Key | Type | Notes |
|-----|------|-------|
| `title` | string | optional display title |
| `description` | string | optional longer note |
| `tagList` | string array | optional user labels |
| `statusText` | string | `starting`, `active`, `completed`, `archived`, `failed`, or other status |
| `templateKey` | string | template key used by the orchestrator |
| `templateName` | string | display name copied from the template |
| `modelText` | string | model label when useful |
| `sourceText` | string | `manual`, `experiment`, or other source |
| `isUserTurn` | boolean | true when user input should be enabled |
| `endStatusText` | string | optional final status such as `abnormal` |
| `eventList` | string array | ordered list of event IDs |

`eventList` stores event IDs in timeline order.

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
| `orchestratorMessage` | `subAgentStart` | parent started child conversations |
| `orchestratorMessage` | `subAgentResult` | child conversations returned to parent |
| `orchestratorMessage` | `subAgentReturn` | child conversation returned its final value |
| `EndAbnormal` | `BackendException` | backend exception detail in `contentText` |

When a template startup or turn fails after a conversation exists, the backend should append `EndAbnormal` with subtype `BackendException`, set `statusText` to `failed`, and disable user input with `isUserTurn = false`.

Free chat conversations should use `templateKey = free-talk`, `statusText = active`, and `isUserTurn = true` at creation time.

One-shot templates such as `mcp-tool-all` should set `statusText` to `completed` and `isUserTurn` to false after startup finishes.

When an interactive tool call returns `is_terminated = true`, the backend should set `statusText` to `completed`, set `isUserTurn` to false, and keep the termination reason in metadata when available.

## Turn Shape

The timeline is an event list, but it is useful to think about three major turn shapes:

- User turn: the latest committed input is `userMessage / textSimple`. The backend sends this plus history to the agent or template orchestrator.
- Agent turn: the latest agent output is either `agentMessage / textSimple` or `agentMessage / toolCall`.
- Orchestrator turn: the orchestrator appends instructions or tool feedback as `orchestratorMessage / textSimple` or `orchestratorMessage / toolResult`.

Normal free chat is simple:

```text
userMessage / textSimple
agentMessage / textSimple
```

The user can type again when conversation metadata has `statusText = active` and `isUserTurn = true`.

Tool calling adds an orchestrator turn between agent steps:

```text
orchestratorMessage / textSimple
agentMessage / toolCall
orchestratorMessage / toolResult
agentMessage / textSimple
userMessage / textSimple
agentMessage / toolCall
orchestratorMessage / toolResult
```

The first `orchestratorMessage / textSimple` is often the template startup prompt. A tool call itself is stored as `agentMessage / toolCall`; the tool execution result is stored as `orchestratorMessage / toolResult`. The agent sees the orchestrator result text as the next model input, but the persisted source stays `orchestratorMessage`, not `userMessage`.

Subagent orchestration adds parent and child events:

```text
agentMessage / toolCall
orchestratorMessage / subAgentStart
orchestratorMessage / subAgentResult
```

The child conversation ends by appending:

```text
orchestratorMessage / subAgentReturn
```

## Source Of Truth

The database does not have a separate `turnType` column. Turn shape is inferred from durable state:

- `event.typeText`
- `event.subtypeText`
- `conversation.metadata.statusText`
- `conversation.metadata.isUserTurn`
- the ordered event IDs in `conversation.metadata.eventList`

The backend appends events with `create_event_in_db()`. That function inserts one event row and updates the parent conversation `eventList` in the same transaction.

The conversation model does not decide how the next event is produced. Orchestration concepts and templates are documented in `doc/orchesatrator.md`.

## Content Types

Content type values are resolved through `config/conversation_content_type.yaml`.

Initial usage:

| contentType | Meaning | Column rule |
|-------------|---------|-------------|
| `1` | text | `contentText` is required, `contentJson` is null |
| `2` | json | `contentJson` is required, `contentText` is null |
| `3` | text with structured data | both columns may be used |

For pure text conversation, use `contentType = 1`.

For tool results and structured messages, `contentType = 3` should preserve the exact text sent to the agent in `contentText` and store displayable structured data in `contentJson`.

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

Segment types:

| type | Notes |
|------|-------|
| `text` | plain text segment |
| `json` | structured JSON segment |

`displayRules` is an optional map of dot-paths to display behavior. `popup` means the normal message card may show an abbreviated preview and provide a full-value popup.

## Service Rules

- Conversation creation allocates a new conversation ID.
- Event creation allocates a new event ID.
- Every event insert updates parent conversation ordering and update time.
- Event creation and parent conversation update must be in one transaction.
- Conversation delete should remove the conversation, descendant conversations, and all descendant events in one transaction.
- Events should be read in conversation order.
