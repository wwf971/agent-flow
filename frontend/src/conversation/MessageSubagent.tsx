import { useEffect } from 'react'
import { observer } from 'mobx-react-lite'
import { SpinningCircle } from '@wwf971/react-comp-misc'
import { appStore, EventItem } from '../store/appStore'
import RoleCard from './RoleCard'
import './Message.css'

type MessageSubagentProps = {
  data: EventItem
}

const MessageSubagent = observer(({ data }: MessageSubagentProps) => {
  useEffect(() => {
    void appStore.requestSubagentChildrenForEvent(data, true)
  }, [data])

  const childViewList = buildChildViewList(data)
  const childTotalCount = childViewList.length
  const childFinishedCount = childViewList.filter((item) => !item.isRunning).length
  const childFailedCount = childViewList.filter((item) => item.statusText === 'failed').length
  const isRunning = childViewList.some((item) => item.isRunning)

  return (
    <div className="conversation-message-row">
      <RoleCard roleText="Orchestrator" roleToneText="orchestrator" />
      <div className="conversation-message-box conversation-message-box-orchestrator">
        <div className="conversation-message-header">
          <div className="conversation-message-subagent-title">Subagents</div>
          <div className="conversation-message-event-type-inline">
            {data.typeText}
            {data.subtypeText ? ` / ${data.subtypeText}` : ''}
          </div>
        </div>
        <div className="conversation-message-subagent-summary">
          {isRunning ? <SpinningCircle width={14} height={14} /> : null}
          <div className="conversation-message-subagent-summary-text">
            {childFinishedCount} / {childTotalCount} finished
            {childFailedCount ? `, ${childFailedCount} failed` : ''}
          </div>
        </div>
        <div className="conversation-message-subagent-list">
          {childViewList.map((child) => (
            <div className="conversation-message-subagent-item" key={child.conversationId}>
              <div className="conversation-message-subagent-item-main">
                {child.isRunning ? <SpinningCircle width={12} height={12} /> : null}
                <button
                  type="button"
                  className="conversation-message-subagent-link"
                  onClick={() => appStore.selectConversation(child.conversationId)}
                >
                  {child.nameText}
                </button>
                <div className={`conversation-message-subagent-status conversation-message-subagent-status-${child.statusText}`}>
                  {child.statusText}
                </div>
              </div>
              <div className="conversation-message-subagent-detail">
                Turns: {child.turnCount}
                {child.latestToolCallText ? `, Tool: ${child.latestToolCallText}` : ''}
                {child.failureText ? `, Error: ${child.failureText}` : ''}
              </div>
            </div>
          ))}
          {!childViewList.length ? (
            <div className="conversation-message-subagent-detail">Loading child conversations</div>
          ) : null}
        </div>
      </div>
    </div>
  )
})

function buildChildViewList(event: EventItem) {
  const childIdList = appStore.getSubagentChildIdListFromEvent(event)
  return childIdList.map((conversationId, index) => buildChildView(conversationId, index))
}

function buildChildView(conversationId: string, index: number) {
  const conversation = appStore.conversationById[conversationId]
  const eventList = appStore.eventListByConversationId[conversationId] || []
  const metadata = conversation?.metadata || {}
  const result = metadata.subAgentResult || {}
  const statusText = resolveChildStatusText(conversation, result)
  const latestToolCall = getLatestToolCall(eventList) || result.latestToolCall || null
  return {
    conversationId,
    nameText: String(metadata.subAgentName || metadata.title || `subagent ${index + 1}`),
    statusText,
    isRunning: getIsChildRunning(conversation),
    turnCount: Number(result.turnCount || getTurnCount(eventList)),
    latestToolCallText: latestToolCall ? String(latestToolCall.toolName || '') : '',
    failureText: String(result.failureReason || metadata.endReasonText || ''),
  }
}

function resolveChildStatusText(conversation: any, result: any) {
  if (!conversation) return 'loading'
  const execStatusCode = Number(conversation.execStatusCode || 0)
  if (execStatusCode === 10) return 'pending'
  if (execStatusCode === 20) return 'running'
  if (execStatusCode === 30) return 'retryWait'
  if (result?.statusText) return String(result.statusText)
  if (conversation.metadata?.statusText) return String(conversation.metadata.statusText)
  return 'active'
}

function getIsChildRunning(conversation: any) {
  if (!conversation) return true
  const stateCode = Number(conversation.stateCode || 100)
  const execStatusCode = Number(conversation.execStatusCode || 0)
  return stateCode < 0 || execStatusCode === 10 || execStatusCode === 20 || execStatusCode === 30
}

function getTurnCount(eventList: EventItem[]) {
  return eventList.filter((event) => event.typeText === 'agentMessage').length
}

function getLatestToolCall(eventList: EventItem[]) {
  for (const event of [...eventList].reverse()) {
    if (event.subtypeText !== 'toolCall') continue
    const contentJson = event.contentJson || {}
    return {
      toolName: String(contentJson.tool_name || ''),
      args: contentJson.args || {},
    }
  }
  return null
}

export default MessageSubagent
