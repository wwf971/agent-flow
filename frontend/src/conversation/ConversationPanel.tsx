import { KeyboardEvent, useEffect, useRef } from 'react'
import { observer } from 'mobx-react-lite'
import { ButtonWithDropDown, EditIcon, SpinningCircle } from '@wwf971/react-comp-misc'
import Message from './Message'
import MessagePending from './MessagePending'
import UserInput from './UserInput'
import { appStore } from '../store/appStore'
import '../panel/Panel.css'
import './ConversationPanel.css'

const ConversationPanel = observer(() => {
  const messageListEndRef = useRef<HTMLDivElement | null>(null)
  const conversation = appStore.conversationSelected
  const conversationIdSelected = appStore.conversationSelectedId
  const eventList = appStore.eventListCurrent
  const messagePendingData = appStore.messagePendingCurrent
  useEffect(() => {
    if (!appStore.isConversationAutoScrollEnabled) return
    messageListEndRef.current?.scrollIntoView({ block: 'end' })
  }, [conversationIdSelected, eventList.length, messagePendingData.isVisible])

  if (!conversation) {
    return <div className="panel-empty-text">No conversation selected</div>
  }
  const metadata = conversation.metadata || {}
  const statusText = String(metadata.statusText || 'active')
  const isInputEnabled = appStore.isConversationInputEnabled
  const messageConversationNoticeText = appStore.getMessageConversationNoticeText(conversation.conversationId)
  const inputPlaceholder = resolveInputPlaceholder(statusText, String(metadata.templateKey || 'free-talk'))
  const ButtonWithDropDownComp = ButtonWithDropDown as any

  return (
    <div className="conversation-root">
      <div className="conversation-header">
        <ConversationTitle conversationId={conversation.conversationId} titleText={String(metadata.title || metadata.templateName || 'Conversation')} />
        <div className="conversation-meta">
          <span className="conversation-tag">{String(metadata.templateName || metadata.templateKey || 'free-talk')}</span>
          <span className="conversation-tag">{statusText}</span>
          {conversation.isInTrashbin ? <span className="conversation-tag">trashbin</span> : null}
        </div>
        <div className="conversation-header-actions">
          <button
            type="button"
            className="main-btn"
            onClick={() => appStore.requestRefreshCurrentConversation(false)}
          >
            Refresh
          </button>
          <ButtonWithDropDownComp
            data={{
              label: 'Delete',
              items: [
                {
                  id: 'delete-permanently',
                  label: 'Delete Permanently',
                },
                {
                  id: 'delete-to-trashbin',
                  label: 'Delete to Trashbin',
                  isDisabled: conversation.isInTrashbin === true,
                },
              ],
            }}
            config={{
              className: 'conversation-delete-dropdown',
              minWidth: 150,
            }}
            onEvent={(eventType: string, eventData: any) => {
              if (eventType !== 'itemClick') return
              if (eventData?.itemId === 'delete-permanently') {
                appStore.deleteConversation(conversation.conversationId)
              }
              if (eventData?.itemId === 'delete-to-trashbin') {
                appStore.moveConversationToTrashbin(conversation.conversationId)
              }
            }}
          />
          <button
            type="button"
            className="main-btn"
            onClick={() => appStore.archiveConversation(conversation.conversationId)}
          >
            Archive
          </button>
        </div>
      </div>
      {appStore.errorText ? <div className="message-error">{appStore.errorText}</div> : null}
      {messageConversationNoticeText ? <div className="message-info">{messageConversationNoticeText}</div> : null}
      <div className="message-info">Update channel: {appStore.socketStatusText}</div>
      <div className="conversation-message-list">
        {eventList.length === 0 && !messagePendingData.isVisible ? (
          <div className="panel-empty-text">No events yet</div>
        ) : (
          eventList.map((event) => <Message key={event.id} data={event} />)
        )}
        <MessagePending data={messagePendingData} />
        <div ref={messageListEndRef} />
      </div>
      <UserInput isInputEnabled={isInputEnabled} placeholderText={inputPlaceholder} />
    </div>
  )
})

const ConversationTitle = observer(({ conversationId, titleText }: { conversationId: string, titleText: string }) => {
  const editRef = useRef<HTMLDivElement | null>(null)
  const isEditing = (
    appStore.conversationRenameEditId === conversationId
    && appStore.conversationRenameSurfaceText === 'title'
  )

  useEffect(() => {
    if (!isEditing) return
    const element = editRef.current
    if (!element) return
    element.textContent = appStore.conversationRenameDraftText
    element.focus()
    const range = document.createRange()
    range.selectNodeContents(element)
    range.collapse(false)
    const selection = window.getSelection()
    selection?.removeAllRanges()
    selection?.addRange(range)
  }, [isEditing])

  if (!isEditing) {
    return (
      <div className="conversation-title-view-root">
        <div className="conversation-title">
          {titleText}
        </div>
        <button
          type="button"
          className="conversation-title-edit-btn"
          onClick={() => appStore.startRenameConversation(conversationId, 'title')}
        >
          <EditIcon width={14} height={14} />
        </button>
      </div>
    )
  }

  return (
    <div className="conversation-title-edit-root">
      <div
        ref={editRef}
        className="conversation-title conversation-title-edit"
        contentEditable={!appStore.isConversationRenameSaving}
        suppressContentEditableWarning={true}
        onBlur={(event) => appStore.submitRenameConversation(conversationId, event.currentTarget.textContent || '')}
        onKeyDown={(event: KeyboardEvent<HTMLDivElement>) => {
          if (event.key === 'Escape') {
            event.preventDefault()
            appStore.cancelRenameConversation()
          }
          if (event.nativeEvent.isComposing) return
          if (event.key === 'Enter') {
            event.preventDefault()
            appStore.submitRenameConversation(conversationId, event.currentTarget.textContent || '')
          }
        }}
      />
      {appStore.isConversationRenameSaving ? <SpinningCircle width={14} height={14} /> : null}
    </div>
  )
})

function resolveInputPlaceholder(statusText: string, templateKey: string) {
  if (statusText === 'failed') return 'Conversation ended abnormally'
  if (statusText === 'completed') return 'Conversation completed'
  if (templateKey === 'mcp-tool-all') return 'MCP Tool Exercise is complete'
  return 'Waiting for user turn'
}

export default ConversationPanel
