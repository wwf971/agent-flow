import { type CSSProperties, KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { observer } from 'mobx-react-lite'
import { SpinningCircle, TreeView } from '@wwf971/react-comp-misc'
import { appStore } from './store/appStore'
import './ResourceTree.css'

type ContextMenuState = {
  conversationId: string
  itemId: string
  anchorOffset: {
    x: number
    y: number
  }
  position: {
    x: number
    y: number
  }
} | null

const ResourceTree = observer(() => {
  const TreeViewComp = TreeView as any
  const treeShellRef = useRef<HTMLDivElement | null>(null)
  const [itemExpandedById, setItemExpandedById] = useState<Record<string, boolean>>({
    templates: true,
    conversations: true,
    trashbin: true,
  })
  const [contextMenuState, setContextMenuState] = useState<ContextMenuState>(null)
  const [conversationOverlayStyle, setConversationOverlayStyle] = useState<CSSProperties | null>(null)
  const conversationContext = contextMenuState ? appStore.conversationById[contextMenuState.conversationId] : null
  const contextMenuConversationId = contextMenuState?.conversationId || ''
  const contextMenuItemId = contextMenuState?.itemId || ''
  const contextMenuAnchorOffsetX = contextMenuState?.anchorOffset.x || 0
  const contextMenuAnchorOffsetY = contextMenuState?.anchorOffset.y || 0
  const conversationListPresent = appStore.conversationListPresent
  const isConversationBranchLocked = appStore.isConversationReorderSaving
  const isContextDeleteVisible = Boolean(
    conversationContext
    && !conversationContext.parentId
    && conversationContext.isInTrashbin !== true,
  )
  const isContextDeletePermanentVisible = Boolean(
    conversationContext
    && !conversationContext.parentId
    && conversationContext.isInTrashbin === true,
  )
  const isContextRenameVisible = Boolean(
    conversationContext
    && !conversationContext.parentId
  )

  useLayoutEffect(() => {
    if (!contextMenuConversationId || !contextMenuItemId) return undefined

    let frameId = 0
    const updateContextMenuPosition = () => {
      frameId = 0
      const rowElement = getTreeRowElementByItemId(contextMenuItemId)
      if (!rowElement) {
        setContextMenuState(null)
        return
      }
      const rowRect = rowElement.getBoundingClientRect()
      setContextMenuState((statePrevious) => {
        if (!statePrevious) return statePrevious
        return {
          ...statePrevious,
          position: {
            x: rowRect.left + contextMenuAnchorOffsetX,
            y: rowRect.top + contextMenuAnchorOffsetY,
          },
        }
      })
    }

    const requestUpdate = () => {
      if (frameId) return
      frameId = requestAnimationFrame(updateContextMenuPosition)
    }

    requestUpdate()
    document.addEventListener('scroll', requestUpdate, true)
    window.addEventListener('resize', requestUpdate)

    return () => {
      if (frameId) window.cancelAnimationFrame(frameId)
      document.removeEventListener('scroll', requestUpdate, true)
      window.removeEventListener('resize', requestUpdate)
    }
  }, [contextMenuAnchorOffsetX, contextMenuAnchorOffsetY, contextMenuConversationId, contextMenuItemId])

  useLayoutEffect(() => {
    if (!isConversationBranchLocked || itemExpandedById.conversations !== true) {
      setConversationOverlayStyle(null)
      return undefined
    }

    let frameId = 0
    const updateConversationOverlayStyle = () => {
      frameId = 0
      const shellElement = treeShellRef.current
      const conversationRowElement = shellElement?.querySelector('[data-tree-item-id="conversations"]') as HTMLElement | null
      const trashbinRowElement = shellElement?.querySelector('[data-tree-item-id="trashbin"]') as HTMLElement | null
      if (!shellElement || !conversationRowElement) {
        setConversationOverlayStyle(null)
        return
      }

      const shellRect = shellElement.getBoundingClientRect()
      const conversationRect = conversationRowElement.getBoundingClientRect()
      const trashbinRect = trashbinRowElement?.getBoundingClientRect()
      const top = Math.max(0, conversationRect.bottom - shellRect.top)
      const bottom = trashbinRect ? trashbinRect.top - shellRect.top : shellRect.height
      const height = Math.max(22, bottom - top)
      setConversationOverlayStyle({
        top,
        left: 0,
        right: 0,
        height,
      })
    }

    const requestUpdate = () => {
      if (frameId) return
      frameId = requestAnimationFrame(updateConversationOverlayStyle)
    }

    requestUpdate()
    const treeElement = treeShellRef.current?.querySelector('.resource-tree-view')
    treeElement?.addEventListener('scroll', requestUpdate)
    window.addEventListener('resize', requestUpdate)

    return () => {
      if (frameId) window.cancelAnimationFrame(frameId)
      treeElement?.removeEventListener('scroll', requestUpdate)
      window.removeEventListener('resize', requestUpdate)
    }
  }, [conversationListPresent.length, isConversationBranchLocked, itemExpandedById.conversations])

  const getTreeRowElementByItemId = (itemId: string) => {
    const shellElement = treeShellRef.current
    if (!shellElement) return null
    const rowElementList = Array.from(shellElement.querySelectorAll('[data-tree-item-id]')) as HTMLElement[]
    return rowElementList.find((element) => element.getAttribute('data-tree-item-id') === itemId) || null
  }

  const getTreeRowElementFromEvent = (event: MouseEvent) => {
    const targetElement = event.target instanceof Element ? event.target : null
    return targetElement?.closest?.('[data-tree-item-id]') as HTMLElement | null
  }

  const openConversationContextMenu = (conversationId: string, event: MouseEvent, itemIdRaw = '') => {
    const conversationIdNormalized = appStore.normalizeConversationId(conversationId)
    if (!conversationIdNormalized) {
      setContextMenuState(null)
      return
    }
    const itemId = itemIdRaw || getTreeRowElementFromEvent(event)?.getAttribute('data-tree-item-id') || `conversation:${conversationIdNormalized}`
    const rowElement = getTreeRowElementByItemId(itemId) || getTreeRowElementFromEvent(event)
    const rowRect = rowElement?.getBoundingClientRect()
    const anchorOffset = rowRect
      ? {
          x: event.clientX - rowRect.left,
          y: event.clientY - rowRect.top,
        }
      : {
          x: 0,
          y: 0,
        }
    void appStore.selectConversation(conversationIdNormalized)
    setContextMenuState(null)
    requestAnimationFrame(() => {
      setContextMenuState({
        conversationId: conversationIdNormalized,
        itemId,
        anchorOffset,
        position: {
          x: rowRect ? rowRect.left + anchorOffset.x : event.clientX,
          y: rowRect ? rowRect.top + anchorOffset.y : event.clientY,
        },
      })
    })
  }

  const getConversationContextUnderMenu = (event: React.MouseEvent<HTMLDivElement>) => {
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
    return {
      conversationId: appStore.normalizeConversationId(itemData?.conversationId),
      itemId,
    }
  }

  const getConversationIdFromTreeItemId = (itemId: unknown) => {
    const itemIdText = String(itemId || '')
    if (!itemIdText.startsWith('conversation:') || itemIdText === 'conversation:new') return ''
    return appStore.normalizeConversationId(itemIdText.slice('conversation:'.length))
  }

  const getIsPresentConversationTreeItem = (itemId: unknown) => {
    const conversationId = getConversationIdFromTreeItemId(itemId)
    if (!conversationId) return false
    return itemDataById[`conversation:${conversationId}`]?.isConversationPresentItem === true
  }

  const getIsConversationDropTargetAllowed = (targetItemId: unknown, drop: any) => {
    const targetItemIdText = String(targetItemId || '')
    if (getIsPresentConversationTreeItem(targetItemIdText)) return true
    return (
      targetItemIdText === 'conversation:new'
      && drop?.type === 'after'
      && drop?.itemParentId === 'conversations'
    )
  }

  const getIsConversationDropBoundaryAllowed = (drop: any) => {
    const itemBeforeId = String(drop?.itemBeforeId || '')
    const itemAfterId = String(drop?.itemAfterId || '')
    if (itemBeforeId && itemBeforeId !== 'conversation:new' && !getIsPresentConversationTreeItem(itemBeforeId)) return false
    if (itemAfterId && !getIsPresentConversationTreeItem(itemAfterId)) return false
    return true
  }

  const getIsConversationDropAllowed = (itemId: unknown, targetItemId: unknown, drop: any) => {
    if (appStore.isConversationReorderSaving) return false
    if (drop?.type !== 'before' && drop?.type !== 'after') return false
    if (drop?.itemParentId !== 'conversations') return false
    if (!getIsPresentConversationTreeItem(itemId)) return false
    if (!getIsConversationDropTargetAllowed(targetItemId, drop)) return false
    return getIsConversationDropBoundaryAllowed(drop)
  }

  const getIsConversationMoveAllowed = (itemId: unknown, drop: any) => {
    if (appStore.isConversationReorderSaving) return false
    if (drop?.type !== 'before' && drop?.type !== 'after') return false
    if (drop?.itemParentId !== 'conversations') return false
    if (!getIsPresentConversationTreeItem(itemId)) return false
    return getIsConversationDropBoundaryAllowed(drop)
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
      text: `Conversations (${conversationListPresent.length})`,
      isLeaf: false,
      isExpanded: itemExpandedById.conversations === true,
      childrenIds: [
        'conversation:new',
        ...conversationListPresent.map((item) => `conversation:${item.conversationId}`),
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
  appStore.conversationListAll.forEach((conversation) => {
    const metadata = conversation.metadata || {}
    const titleText = String(metadata.title || metadata.templateName || conversation.conversationId)
    const isArchived = String(metadata.statusText || '') === 'archived'
    const isInTrashbin = conversation.isInTrashbin === true
    const childConversationIdList = appStore.getChildConversationIdList(conversation.conversationId)
    const itemId = `conversation:${conversation.conversationId}`
    const isRootConversation = !conversation.parentId
    itemDataById[itemId] = {
      id: itemId,
      text: isInTrashbin ? `${titleText} [trashbin]` : (isArchived ? `${titleText} [history]` : titleText),
      isLeaf: childConversationIdList.length < 1,
      isExpanded: itemExpandedById[itemId] === true,
      childrenIds: childConversationIdList.map((conversationId) => `conversation:${conversationId}`),
      childrenLoadState: 'loaded',
      conversationId: conversation.conversationId,
      isConversationItem: true,
      isConversationPresentItem: !isInTrashbin && isRootConversation,
    }
  })

  return (
    <>
      <div ref={treeShellRef} className="resource-tree-shell">
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
              const classNameList = []
              if (itemData?.id === 'conversations') classNameList.push('resource-tree-conversation-root-row')
              if (itemData?.id === 'conversation:new') classNameList.push('resource-tree-conversation-new-row')
              if (itemData?.isConversationItem) classNameList.push('resource-tree-conversation-row')
              if (
                isConversationBranchLocked
                && (
                  itemData?.id === 'conversations'
                  || itemData?.id === 'conversation:new'
                  || itemData?.isConversationItem
                )
              ) {
                classNameList.push('resource-tree-conversation-locked-row')
              }
              return classNameList.join(' ')
            },
            isItemDragEnabled: true,
            getIsItemDraggable: (itemData: any) => {
              if (appStore.isConversationReorderSaving) return false
              if (appStore.conversationRenameEditId === appStore.normalizeConversationId(itemData?.conversationId)) return false
              return itemData?.isConversationPresentItem === true
            },
            getItemDropStatus: ({ itemId, targetItemId, drop }: any) => ({
              isDropAllowed: getIsConversationDropAllowed(itemId, targetItemId, drop),
            }),
          }}
          onEvent={async (eventType: string, eventData: any) => {
          if (eventType === 'toggleExpand') {
            const itemId = String(eventData?.itemId || '')
            if (isConversationBranchLocked && itemId === 'conversations') return { code: 0 }
            const isExpandedNext = eventData?.nextIsExpanded === true
            setItemExpandedById((itemExpandedPrevious) => ({
              ...itemExpandedPrevious,
              [itemId]: isExpandedNext,
            }))
            if (isExpandedNext && eventData?.itemData?.conversationId) {
              await appStore.requestChildConversationList(String(eventData.itemData.conversationId), true)
            }
            return { code: 0 }
          }
          if (eventType === 'itemClick') {
            const itemId = String(eventData?.itemId || '')
            const itemData = eventData?.itemData
            setContextMenuState(null)
            if (
              isConversationBranchLocked
              && (
                itemId === 'conversations'
                || itemId === 'conversation:new'
                || itemData?.isConversationItem
              )
            ) {
              return { code: 0 }
            }
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
            if (
              isConversationBranchLocked
              && (
                eventData?.itemId === 'conversations'
                || eventData?.itemId === 'conversation:new'
                || itemData?.isConversationItem
              )
            ) {
              setContextMenuState(null)
              return { code: 0 }
            }
            const conversationId = appStore.normalizeConversationId(itemData?.conversationId)
            if (!conversationId) {
              setContextMenuState(null)
              return { code: 0 }
            }
            openConversationContextMenu(conversationId, event, String(eventData?.itemId || ''))
          }
          if (eventType === 'moveItem') {
            const itemId = eventData?.itemId
            const drop = eventData?.drop
            if (!getIsConversationMoveAllowed(itemId, drop)) return { code: -1 }
            const conversationId = getConversationIdFromTreeItemId(itemId)
            if (!conversationId) return { code: -1 }
            await appStore.reorderConversation(
              conversationId,
              getConversationIdFromTreeItemId(drop?.itemBeforeId),
              getConversationIdFromTreeItemId(drop?.itemAfterId),
            )
            return { code: 0 }
          }
          return { code: 0 }
          }}
        />
        {isConversationBranchLocked && conversationOverlayStyle ? (
          <div className="resource-tree-conversation-lock-overlay" style={conversationOverlayStyle}>
            <div className="resource-tree-conversation-lock-spinner">
              <SpinningCircle width={16} height={16} color="#6f7d92" />
            </div>
          </div>
        ) : null}
      </div>
      {contextMenuState ? (
        <>
          <div
            className="resource-context-menu-backdrop"
            onClick={() => setContextMenuState(null)}
            onContextMenu={(event) => {
              event.preventDefault()
              event.stopPropagation()
              const contextMenuNext = getConversationContextUnderMenu(event)
              if (contextMenuNext.conversationId) {
                openConversationContextMenu(contextMenuNext.conversationId, event.nativeEvent, contextMenuNext.itemId)
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
            {isContextRenameVisible ? (
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
            ) : null}
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
