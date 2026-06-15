import { KeyboardEvent, useEffect, useRef, useState } from 'react'
import { observer } from 'mobx-react-lite'
import { SpinningCircle, TreeView } from '@wwf971/react-comp-misc'
import { appStore } from './store/appStore'

type ContextMenuState = {
  conversationId: string
  position: {
    x: number
    y: number
  }
} | null

const ResourceTree = observer(() => {
  const TreeViewComp = TreeView as any
  const [itemExpandedById, setItemExpandedById] = useState<Record<string, boolean>>({
    templates: true,
    conversations: true,
    trashbin: true,
  })
  const [contextMenuState, setContextMenuState] = useState<ContextMenuState>(null)
  const conversationContext = contextMenuState ? appStore.conversationById[contextMenuState.conversationId] : null
  const isContextDeleteVisible = Boolean(
    conversationContext
    && conversationContext.isInTrashbin !== true,
  )
  const isContextDeletePermanentVisible = Boolean(
    conversationContext
    && conversationContext.isInTrashbin === true,
  )

  const openConversationContextMenu = (conversationId: string, event: MouseEvent) => {
    const conversationIdNormalized = appStore.normalizeConversationId(conversationId)
    if (!conversationIdNormalized) {
      setContextMenuState(null)
      return
    }
    void appStore.selectConversation(conversationIdNormalized)
    setContextMenuState(null)
    requestAnimationFrame(() => {
      setContextMenuState({
        conversationId: conversationIdNormalized,
        position: {
          x: event.clientX,
          y: event.clientY,
        },
      })
    })
  }

  const getConversationIdUnderContextMenu = (event: React.MouseEvent<HTMLDivElement>) => {
    const overlayElementList = Array.from(document.querySelectorAll('.resource-context-menu-backdrop, .resource-context-menu')) as HTMLElement[]
    const previousPointerEventList = overlayElementList.map((element) => ({
      element,
      pointerEvents: element.style.pointerEvents,
    }))
    overlayElementList.forEach((element) => {
      element.style.pointerEvents = 'none'
    })
    const targetElement = document.elementFromPoint(event.clientX, event.clientY)
    previousPointerEventList.forEach(({ element, pointerEvents }) => {
      element.style.pointerEvents = pointerEvents
    })
    const rowElement = targetElement?.closest?.('[data-tree-item-id]')
    const itemId = rowElement?.getAttribute('data-tree-item-id') || ''
    const itemData = itemDataById[itemId]
    return appStore.normalizeConversationId(itemData?.conversationId)
  }

  const itemDataById: Record<string, any> = {
    templates: {
      id: 'templates',
      text: `Templates (${appStore.templateList.length})`,
      isLeaf: false,
      isExpanded: itemExpandedById.templates === true,
      childrenIds: appStore.templateList.map((item) => `template:${item.key}`),
      childrenLoadState: appStore.isTemplateListLoading ? 'loading' : 'loaded',
    },
    conversations: {
      id: 'conversations',
      text: `Conversations (${appStore.conversationListActive.length + appStore.conversationListHistory.length})`,
      isLeaf: false,
      isExpanded: itemExpandedById.conversations === true,
      childrenIds: [
        'conversation:new',
        ...appStore.conversationListActive.map((item) => `conversation:${item.conversationId}`),
        ...appStore.conversationListHistory.map((item) => `conversation:${item.conversationId}`),
      ],
      childrenLoadState: appStore.isConversationListLoading ? 'loading' : 'loaded',
    },
    trashbin: {
      id: 'trashbin',
      text: `Trashbin (${appStore.conversationListTrashbin.length})`,
      isLeaf: false,
      isExpanded: itemExpandedById.trashbin === true,
      childrenIds: appStore.conversationListTrashbin.map((item) => `conversation:${item.conversationId}`),
      childrenLoadState: appStore.isConversationListLoading ? 'loading' : 'loaded',
    },
    'conversation:new': {
      id: 'conversation:new',
      text: 'New',
      isLeaf: true,
      isExpanded: false,
      childrenIds: [],
      childrenLoadState: 'loaded',
    },
  }
  appStore.templateList.forEach((template) => {
    itemDataById[`template:${template.key}`] = {
      id: `template:${template.key}`,
      text: template.name,
      isLeaf: true,
      isExpanded: false,
      childrenIds: [],
      childrenLoadState: 'loaded',
      templateKey: template.key,
    }
  })
  appStore.conversationList.forEach((conversation) => {
    const metadata = conversation.metadata || {}
    const titleText = String(metadata.title || metadata.templateName || conversation.conversationId)
    const isArchived = String(metadata.statusText || '') === 'archived'
    const isInTrashbin = conversation.isInTrashbin === true
    itemDataById[`conversation:${conversation.conversationId}`] = {
      id: `conversation:${conversation.conversationId}`,
      text: isInTrashbin ? `${titleText} [trashbin]` : (isArchived ? `${titleText} [history]` : titleText),
      isLeaf: true,
      isExpanded: false,
      childrenIds: [],
      childrenLoadState: 'loaded',
      conversationId: conversation.conversationId,
      isConversationItem: true,
    }
  })

  return (
    <>
      <TreeViewComp
        data={{
          itemRootIds: ['templates', 'conversations', 'trashbin'],
          itemDataById,
          itemSelectedId: appStore.treeSelectedItemId,
        }}
        config={{
          className: 'resource-tree-view',
          getItemComp: (itemData: any) => {
            if (itemData?.isConversationItem) return ConversationTreeItem
            return null
          },
          getItemRowClassName: (itemData: any) => {
            if (itemData?.isConversationItem) return 'resource-tree-conversation-row'
            return ''
          },
        }}
        onEvent={async (eventType: string, eventData: any) => {
          if (eventType === 'toggleExpand') {
            const itemId = String(eventData?.itemId || '')
            const isExpandedNext = eventData?.nextIsExpanded === true
            setItemExpandedById((itemExpandedPrevious) => ({
              ...itemExpandedPrevious,
              [itemId]: isExpandedNext,
            }))
            return { code: 0 }
          }
          if (eventType === 'itemClick') {
            const itemId = String(eventData?.itemId || '')
            const itemData = eventData?.itemData
            setContextMenuState(null)
            if (itemId === 'templates') return { code: 0 }
            if (itemId === 'conversations') return { code: 0 }
            if (itemId === 'trashbin') return { code: 0 }
            if (itemId === 'conversation:new') {
              appStore.selectNewConversation()
              return { code: 0 }
            }
            if (itemData?.templateKey) {
              appStore.selectTemplate(String(itemData.templateKey))
              return { code: 0 }
            }
            if (itemData?.conversationId) {
              appStore.selectConversation(String(itemData.conversationId))
            }
            return { code: 0 }
          }
          if (eventType === 'itemContextMenu') {
            const itemData = eventData?.itemData
            const event = eventData?.event as MouseEvent
            const conversationId = appStore.normalizeConversationId(itemData?.conversationId)
            if (!conversationId) {
              setContextMenuState(null)
              return { code: 0 }
            }
            openConversationContextMenu(conversationId, event)
          }
          return { code: 0 }
        }}
      />
      {contextMenuState ? (
        <>
          <div
            className="resource-context-menu-backdrop"
            onClick={() => setContextMenuState(null)}
            onContextMenu={(event) => {
              event.preventDefault()
              event.stopPropagation()
              const conversationId = getConversationIdUnderContextMenu(event)
              if (conversationId) {
                openConversationContextMenu(conversationId, event.nativeEvent)
                return
              }
              setContextMenuState(null)
            }}
          />
          <div
            className="resource-context-menu"
            style={{
              left: contextMenuState.position.x,
              top: contextMenuState.position.y,
            }}
            onContextMenu={(event) => {
              event.preventDefault()
              event.stopPropagation()
            }}
          >
            <button
              type="button"
              className="resource-context-menu-item"
              onClick={() => {
                const conversationId = contextMenuState.conversationId
                setContextMenuState(null)
                appStore.startRenameConversation(conversationId, 'tree')
              }}
            >
              Rename
            </button>
            {isContextDeleteVisible ? (
              <button
                type="button"
                className="resource-context-menu-item"
                onClick={() => {
                  const conversationId = contextMenuState.conversationId
                  setContextMenuState(null)
                  appStore.moveConversationToTrashbin(conversationId)
                }}
              >
                Delete
              </button>
            ) : null}
            {isContextDeletePermanentVisible ? (
              <button
                type="button"
                className="resource-context-menu-item"
                onClick={() => {
                  const conversationId = contextMenuState.conversationId
                  setContextMenuState(null)
                  appStore.deleteConversation(conversationId)
                }}
              >
                Delete Permanently
              </button>
            ) : null}
          </div>
        </>
      ) : null}
    </>
  )
})

const ConversationTreeItem = observer(({ itemData }: { itemData: any }) => {
  const editRef = useRef<HTMLDivElement | null>(null)
  const conversationId = appStore.normalizeConversationId(itemData?.conversationId)
  const isEditing = (
    appStore.conversationRenameEditId === conversationId
    && appStore.conversationRenameSurfaceText === 'tree'
  )

  useEffect(() => {
    if (!isEditing) return
    const element = editRef.current
    if (!element) return
    element.textContent = appStore.conversationRenameDraftText
    element.focus()
    const range = document.createRange()
    range.selectNodeContents(element)
    const selection = window.getSelection()
    selection?.removeAllRanges()
    selection?.addRange(range)
  }, [isEditing])

  if (!isEditing) {
    return <span className="tree-view-text-item">{String(itemData?.text || '')}</span>
  }

  return (
    <span className="tree-rename-root" onClick={(event) => event.stopPropagation()}>
      <span
        ref={editRef}
        className="tree-rename-text"
        contentEditable={!appStore.isConversationRenameSaving}
        suppressContentEditableWarning={true}
        onBlur={(event) => appStore.submitRenameConversation(conversationId, event.currentTarget.textContent || '')}
        onKeyDown={(event: KeyboardEvent<HTMLSpanElement>) => {
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
      {appStore.isConversationRenameSaving ? <SpinningCircle width={12} height={12} /> : null}
    </span>
  )
})

export default ResourceTree
