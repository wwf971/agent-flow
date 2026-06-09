import { makeAutoObservable, runInAction } from 'mobx'
import { ApiRequestError, requestAuthenticatedJson } from '../apiRequest'
import { resolveWebSocketUrl } from '../publicPath'

export const PAGE_KEY = {
  template: 'template',
  conversationNew: 'conversation-new',
  conversation: 'conversation',
} as const

export type TemplateItem = {
  key: string
  name: string
  description: string
}

export type ConversationItem = {
  conversationId: string
  metadata: Record<string, any>
  isInTrashbin?: boolean
  createAt: string
  updateAt: string
}

export type EventItem = {
  id: string
  conversationId: string
  typeText: string
  subtypeText: string
  contentType: number
  contentText: string
  contentJson?: any
  metadata: Record<string, any>
  createAt: string
}

export type MessagePendingData = {
  isVisible: boolean
  roleText: string
  typeText: string
  subtypeText: string
}

export type OperationState = {
  statusText: 'idle' | 'running' | 'success' | 'error'
  messageText: string
}

const OPERATION_KEY = {
  conversationCreate: 'conversation-create',
  messageSend: 'message-send',
} as const

function createOperationState(statusText: OperationState['statusText'], messageText = ''): OperationState {
  return {
    statusText,
    messageText,
  }
}

class AppStore {
  pageCurrentKey: string = PAGE_KEY.conversationNew
  templateList: TemplateItem[] = []
  conversationById: Record<string, ConversationItem> = {}
  conversationIdList: string[] = []
  eventListByConversationId: Record<string, EventItem[]> = {}
  templateSelectedKey = ''
  conversationSelectedId = ''
  messageDraftText = ''
  errorText = ''
  noticeText = ''
  operationByKey: Record<string, OperationState> = {}
  operationByConversationId: Record<string, Record<string, OperationState>> = {}
  conversationRenameEditId = ''
  conversationRenameSurfaceText = ''
  conversationRenameDraftText = ''
  isConversationRenameSaving = false
  isTemplateListLoading = false
  isConversationListLoading = false
  isEventListLoading = false
  isBootstrapped = false
  socketUpdate: WebSocket | null = null
  socketStatusText = 'not connected'
  refreshTimer: number | null = null
  isConversationAutoScrollEnabled = true

  constructor() {
    makeAutoObservable(this, {}, { autoBind: true })
  }

  normalizeConversationId(conversationId: unknown) {
    const text = String(conversationId || '').trim()
    if (!text || text === 'undefined' || text === 'null') return ''
    return text
  }

  normalizeConversationItem(item: Partial<ConversationItem> & { conversationId: string }) {
    return {
      conversationId: this.normalizeConversationId(item.conversationId),
      metadata: item.metadata || {},
      isInTrashbin: item.isInTrashbin === true,
      createAt: String(item.createAt || ''),
      updateAt: String(item.updateAt || ''),
    }
  }

  getOperationByKey(operationKey: string) {
    return this.operationByKey[operationKey] || createOperationState('idle')
  }

  setOperationByKey(operationKey: string, operationState: OperationState) {
    this.operationByKey[operationKey] = operationState
  }

  setOperationByConversationId(conversationId: string, operationKey: string, operationState: OperationState) {
    const conversationIdNormalized = this.normalizeConversationId(conversationId)
    if (!conversationIdNormalized) return
    this.operationByConversationId[conversationIdNormalized] = {
      ...(this.operationByConversationId[conversationIdNormalized] || {}),
      [operationKey]: operationState,
    }
  }

  appendEventIfMissing(event: EventItem) {
    const conversationId = this.normalizeConversationId(event.conversationId)
    if (!conversationId || !event.id) return
    const eventList = this.eventListByConversationId[conversationId] || []
    if (eventList.some((item) => item.id === event.id)) return
    this.eventListByConversationId[conversationId] = [...eventList, event]
  }

  syncConversationOperationState(item: ConversationItem) {
    const operationByKey = this.operationByConversationId[item.conversationId] || {}
    const operationTemplateStart = operationByKey['template-start']
    if (operationTemplateStart?.statusText === 'running' && item.metadata?.statusText !== 'starting') {
      this.setOperationByConversationId(
        item.conversationId,
        'template-start',
        createOperationState(item.metadata?.statusText === 'failed' ? 'error' : 'success'),
      )
    }
    const operationMessageSend = operationByKey[OPERATION_KEY.messageSend]
    if (operationMessageSend?.statusText !== 'running') return
    const statusText = String(item.metadata?.statusText || 'active')
    const isTurnFinished = (
      item.metadata?.isUserTurn !== false
      || statusText === 'completed'
      || statusText === 'archived'
      || item.isInTrashbin === true
    )
    if (!isTurnFinished && statusText !== 'failed') return
    this.setOperationByConversationId(
      item.conversationId,
      OPERATION_KEY.messageSend,
      createOperationState(statusText === 'failed' ? 'error' : 'success'),
    )
  }

  getMessageGlobalErrorText() {
    const operationError = Object.values(this.operationByKey).find((operation) => operation.statusText === 'error')
    return operationError?.messageText || this.errorText
  }

  getMessageGlobalNoticeText() {
    const operationRunning = Object.values(this.operationByKey).find((operation) => operation.statusText === 'running')
    return operationRunning?.messageText || this.noticeText
  }

  getMessageConversationNoticeText(conversationId: string) {
    const conversationIdNormalized = this.normalizeConversationId(conversationId)
    const operationByKey = this.operationByConversationId[conversationIdNormalized] || {}
    const operationRunning = Object.values(operationByKey).find((operation) => operation.statusText === 'running')
    return operationRunning?.messageText || ''
  }

  getOperationConversation(conversationId: string, operationKey: string) {
    const conversationIdNormalized = this.normalizeConversationId(conversationId)
    return this.operationByConversationId[conversationIdNormalized]?.[operationKey] || createOperationState('idle')
  }

  upsertConversation(conversation: Partial<ConversationItem> & { conversationId: string }) {
    const conversationNormalized = this.normalizeConversationItem(conversation)
    if (!conversationNormalized.conversationId) return
    const previous = this.conversationById[conversationNormalized.conversationId]
    this.conversationById[conversationNormalized.conversationId] = {
      ...previous,
      ...conversationNormalized,
      metadata: {
        ...(previous?.metadata || {}),
        ...(conversationNormalized.metadata || {}),
      },
    }
    if (!this.conversationIdList.includes(conversationNormalized.conversationId)) {
      this.conversationIdList.unshift(conversationNormalized.conversationId)
    }
  }

  get templateSelected() {
    return this.templateList.find((item) => item.key === this.templateSelectedKey) || null
  }

  get conversationSelected() {
    return this.conversationById[this.conversationSelectedId] || null
  }

  get conversationList() {
    return this.conversationIdList
      .map((conversationId) => this.conversationById[conversationId])
      .filter(Boolean)
  }

  get eventListCurrent() {
    if (!this.conversationSelectedId) return []
    return this.eventListByConversationId[this.conversationSelectedId] || []
  }

  get messagePendingCurrent(): MessagePendingData {
    const conversation = this.conversationSelected
    if (!conversation) {
      return {
        isVisible: false,
        roleText: '',
        typeText: '',
        subtypeText: '',
      }
    }
    const statusText = String(conversation.metadata?.statusText || 'active')
    const templateKey = String(conversation.metadata?.templateKey || 'free-talk')
    const operationTemplateStart = this.operationByConversationId[conversation.conversationId]?.['template-start']
    const isTemplateStarting = statusText === 'starting' || operationTemplateStart?.statusText === 'running'
    const isWaitingForReply = (
      this.getOperationConversation(conversation.conversationId, OPERATION_KEY.messageSend).statusText === 'running'
      || (statusText === 'active' && conversation.metadata?.isUserTurn === false && templateKey !== 'mcp-tool-all')
    )
    if (!isTemplateStarting && !isWaitingForReply) {
      return {
        isVisible: false,
        roleText: '',
        typeText: '',
        subtypeText: '',
      }
    }
    if (statusText === 'failed' || statusText === 'archived' || conversation.isInTrashbin === true) {
      return {
        isVisible: false,
        roleText: '',
        typeText: '',
        subtypeText: '',
      }
    }
    return {
      isVisible: true,
      roleText: isTemplateStarting ? 'Agent' : 'Agent',
      typeText: isTemplateStarting ? 'agentMessage' : 'agentMessage',
      subtypeText: 'pending',
    }
  }

  get conversationListActive() {
    return this.conversationList.filter((item) => (
      item.isInTrashbin !== true
      && String(item.metadata?.statusText || 'active') !== 'archived'
    ))
  }

  get conversationListHistory() {
    return this.conversationList.filter((item) => (
      item.isInTrashbin !== true
      && String(item.metadata?.statusText || '') === 'archived'
    ))
  }

  get conversationListTrashbin() {
    return this.conversationList.filter((item) => item.isInTrashbin === true)
  }

  get isUserTurn() {
    if (!this.conversationSelected) return false
    return this.conversationSelected.metadata?.isUserTurn !== false
  }

  get isConversationInputEnabled() {
    const conversation = this.conversationSelected
    if (!conversation) return false
    const statusText = String(conversation.metadata?.statusText || 'active')
    const templateKey = String(conversation.metadata?.templateKey || 'free-talk')
    if (conversation.isInTrashbin === true) return false
    if (templateKey === 'mcp-tool-all') return false
    if (this.getOperationConversation(conversation.conversationId, OPERATION_KEY.messageSend).statusText === 'running') return false
    return this.isUserTurn && statusText === 'active'
  }

  get isConversationSending() {
    const conversation = this.conversationSelected
    if (!conversation) return false
    return this.getOperationConversation(conversation.conversationId, OPERATION_KEY.messageSend).statusText === 'running'
  }

  get isSending() {
    return Object.values(this.operationByConversationId)
      .some((operationByKey) => operationByKey[OPERATION_KEY.messageSend]?.statusText === 'running')
  }

  get treeSelectedItemId() {
    if (this.pageCurrentKey === PAGE_KEY.template && this.templateSelectedKey) {
      return `template:${this.templateSelectedKey}`
    }
    if (this.pageCurrentKey === PAGE_KEY.conversation && this.conversationSelectedId) {
      return `conversation:${this.conversationSelectedId}`
    }
    return 'conversation:new'
  }

  async bootstrap() {
    await Promise.all([this.requestTemplateList(), this.requestConversationList()])
    runInAction(() => {
      this.isBootstrapped = true
    })
    this.connectUpdateSocket()
    this.startRefreshLoop()
  }

  connectUpdateSocket() {
    if (this.socketUpdate) return
    const token = localStorage.getItem('react-agent-flow-auth-token') || ''
    const socketUrl = resolveWebSocketUrl(`/api/ws/conversation-updates?authToken=${encodeURIComponent(token)}`)
    const socket = new WebSocket(socketUrl)
    this.socketUpdate = socket
    this.socketStatusText = 'connecting'
    socket.onopen = () => {
      runInAction(() => {
        this.socketStatusText = 'connected'
      })
    }
    socket.onmessage = (event) => {
      this.acceptSocketMessage(String(event.data || ''))
    }
    socket.onerror = () => {
      runInAction(() => {
        this.socketStatusText = 'connection error'
      })
    }
    socket.onclose = () => {
      runInAction(() => {
        this.socketUpdate = null
        this.socketStatusText = 'closed'
      })
    }
  }

  disconnectUpdateSocket() {
    if (!this.socketUpdate) return
    this.socketUpdate.close()
    this.socketUpdate = null
  }

  startRefreshLoop() {
    if (this.refreshTimer !== null) return
    this.refreshTimer = window.setInterval(() => {
      this.requestRefreshCurrentConversation(true)
    }, 3000)
  }

  stopRefreshLoop() {
    if (this.refreshTimer === null) return
    window.clearInterval(this.refreshTimer)
    this.refreshTimer = null
  }

  acceptSocketMessage(messageText: string) {
    let data: any = null
    try {
      data = JSON.parse(messageText)
    } catch {
      return
    }
    if (data.typeText === 'connected') {
      runInAction(() => {
        this.socketStatusText = 'connected'
      })
      return
    }
    if (data.typeText === 'heartbeat') return
    if (data.typeText === 'error') {
      runInAction(() => {
        this.socketStatusText = 'error'
        this.errorText = String(data.message || 'websocket error')
      })
      return
    }
    if (data.typeText !== 'conversationUpdate') return
    this.acceptConversationUpdate(String(data.conversationId || ''))
  }

  async acceptConversationUpdate(conversationId: string) {
    const conversationIdNormalized = this.normalizeConversationId(conversationId)
    await this.requestConversationList(true)
    if (conversationIdNormalized && conversationIdNormalized === this.conversationSelectedId) {
      await this.requestEventList(conversationIdNormalized, true)
    }
  }

  async requestTemplateList() {
    runInAction(() => {
      this.isTemplateListLoading = true
      this.errorText = ''
    })
    try {
      const data = await requestAuthenticatedJson<{ items: TemplateItem[] }>('/api/template/list', {
        method: 'POST',
      })
      runInAction(() => {
        this.templateList = data.items || []
      })
    } catch (error: unknown) {
      runInAction(() => {
        this.errorText = String(error)
      })
    } finally {
      runInAction(() => {
        this.isTemplateListLoading = false
      })
    }
  }

  async requestConversationList(isQuiet = false) {
    if (!isQuiet) {
      runInAction(() => {
        this.isConversationListLoading = true
        this.errorText = ''
      })
    }
    try {
      const data = await requestAuthenticatedJson<{ items: ConversationItem[] }>('/api/conversation/list', {
        method: 'POST',
        body: JSON.stringify({ pageSize: 200 }),
      })
      runInAction(() => {
        const itemList = (data.items || []).map((item) => this.normalizeConversationItem(item))
        const conversationByIdNext: Record<string, ConversationItem> = { ...this.conversationById }
        itemList.forEach((item) => {
          const previous = this.conversationById[item.conversationId]
          if (previous && JSON.stringify(previous) === JSON.stringify(item)) {
            conversationByIdNext[item.conversationId] = previous
          } else {
            conversationByIdNext[item.conversationId] = item
          }
          this.syncConversationOperationState(item)
        })
        Object.keys(conversationByIdNext).forEach((conversationId) => {
          if (!itemList.some((item) => item.conversationId === conversationId)) {
            delete conversationByIdNext[conversationId]
            delete this.eventListByConversationId[conversationId]
          }
        })
        this.conversationById = conversationByIdNext
        this.conversationIdList = itemList.map((item) => item.conversationId)
        if (
          this.conversationSelectedId
          && !this.conversationById[this.conversationSelectedId]
        ) {
          this.conversationSelectedId = ''
          this.pageCurrentKey = PAGE_KEY.conversationNew
        }
      })
    } catch (error: unknown) {
      runInAction(() => {
        this.errorText = String(error)
      })
    } finally {
      if (!isQuiet) {
        runInAction(() => {
          this.isConversationListLoading = false
        })
      }
    }
  }

  async requestEventList(conversationId: string, isQuiet = false) {
    const conversationIdNormalized = this.normalizeConversationId(conversationId)
    if (!conversationIdNormalized) {
      if (!isQuiet) {
        runInAction(() => {
          this.isEventListLoading = false
        })
      }
      return
    }
    if (!isQuiet) {
      runInAction(() => {
        this.isEventListLoading = true
        this.errorText = ''
      })
    }
    try {
      const data = await requestAuthenticatedJson<{ items: EventItem[] }>(
        '/api/event/list',
        {
          method: 'POST',
          body: JSON.stringify({
            conversationId: conversationIdNormalized,
            pageSize: 500,
          }),
        },
      )
      runInAction(() => {
        this.eventListByConversationId[conversationIdNormalized] = data.items || []
      })
    } catch (error: unknown) {
      runInAction(() => {
        this.errorText = String(error)
      })
    } finally {
      if (!isQuiet) {
        runInAction(() => {
          this.isEventListLoading = false
        })
      }
    }
  }

  async requestRefreshCurrentConversation(isQuiet = true) {
    const conversationIdNormalized = this.normalizeConversationId(this.conversationSelectedId)
    if (!conversationIdNormalized || !this.conversationSelected) return
    await Promise.all([
      this.requestConversationList(isQuiet),
      this.requestEventList(conversationIdNormalized, isQuiet),
    ])
  }

  applyConversationUpdate(conversation: ConversationItem, eventList: EventItem[]) {
    this.upsertConversation(conversation)
    this.eventListByConversationId[conversation.conversationId] = eventList
  }

  selectTemplate(templateKey: string) {
    this.templateSelectedKey = templateKey
    this.pageCurrentKey = PAGE_KEY.template
  }

  selectNewConversation() {
    this.pageCurrentKey = PAGE_KEY.conversationNew
    this.conversationSelectedId = ''
  }

  async selectConversation(conversationId: string) {
    const conversationIdNormalized = this.normalizeConversationId(conversationId)
    if (!conversationIdNormalized) {
      this.selectNewConversation()
      return
    }
    this.conversationSelectedId = conversationIdNormalized
    this.pageCurrentKey = PAGE_KEY.conversation
    await this.requestEventList(conversationIdNormalized)
  }

  async createConversationFromTemplate(templateKey: string) {
    runInAction(() => {
      this.errorText = ''
      this.noticeText = 'Creating conversation'
      this.setOperationByKey(OPERATION_KEY.conversationCreate, createOperationState('running', 'Creating conversation'))
    })
    try {
      const data = await requestAuthenticatedJson<ConversationItem>('/api/conversation/create/from-template', {
        method: 'POST',
        body: JSON.stringify({
          templateKey,
          timezone: new Date().getTimezoneOffset() * -1,
          metadata: {},
        }),
      })
      runInAction(() => {
        this.upsertConversation(data)
        this.conversationSelectedId = data.conversationId
        this.pageCurrentKey = PAGE_KEY.conversation
        this.noticeText = ''
        this.setOperationByKey(OPERATION_KEY.conversationCreate, createOperationState('success'))
        if (data.metadata?.statusText === 'starting') {
          this.setOperationByConversationId(data.conversationId, 'template-start', createOperationState('running', 'Starting conversation'))
        }
      })
      await Promise.all([
        this.requestConversationList(true),
        this.requestEventList(data.conversationId, true),
      ])
    } catch (error: unknown) {
      const data = error instanceof ApiRequestError ? error.data as ConversationItem | undefined : undefined
      if (data?.conversationId) {
        await this.requestConversationList(true)
        await this.selectConversation(data.conversationId)
      }
      runInAction(() => {
        this.errorText = String(error)
        this.noticeText = ''
        this.setOperationByKey(OPERATION_KEY.conversationCreate, createOperationState('error', String(error)))
      })
    }
  }

  async createEmptyConversation() {
    await this.createConversationFromTemplate('free-talk')
  }

  setMessageDraftText(value: string) {
    this.messageDraftText = value
  }

  async sendCurrentMessage() {
    const messageText = this.messageDraftText.trim()
    if (!messageText || !this.isConversationInputEnabled) return
    const conversationId = this.normalizeConversationId(this.conversationSelectedId)
    if (!conversationId) return
    runInAction(() => {
      this.errorText = ''
      this.messageDraftText = ''
      this.setOperationByConversationId(conversationId, OPERATION_KEY.messageSend, createOperationState('running', 'Waiting for agent response'))
    })
    try {
      const data = await requestAuthenticatedJson<{ conversationId: string, eventUser?: EventItem }>('/api/orchestrator/turn/create', {
        method: 'POST',
        body: JSON.stringify({
          conversationId,
          messageText,
          timezone: new Date().getTimezoneOffset() * -1,
        }),
      })
      if (!this.conversationSelectedId && data.conversationId) {
        runInAction(() => {
          this.conversationSelectedId = data.conversationId
          this.pageCurrentKey = PAGE_KEY.conversation
        })
      }
      if (data.eventUser) {
        runInAction(() => {
          this.appendEventIfMissing(data.eventUser as EventItem)
        })
      }
      await Promise.all([
        this.requestConversationList(false),
        this.requestEventList(conversationId, false),
      ])
    } catch (error: unknown) {
      await Promise.all([
        this.requestConversationList(true),
        this.requestEventList(conversationId, true),
      ])
      runInAction(() => {
        this.errorText = String(error)
        this.messageDraftText = messageText
        this.setOperationByConversationId(conversationId, OPERATION_KEY.messageSend, createOperationState('error', String(error)))
      })
    }
  }

  async archiveConversation(conversationId: string) {
    const conversation = this.conversationById[conversationId]
    if (!conversation) return
    await requestAuthenticatedJson('/api/conversation/metadata/update', {
      method: 'POST',
      body: JSON.stringify({
        conversationId,
        timezone: new Date().getTimezoneOffset() * -1,
        metadata: {
          ...conversation.metadata,
          statusText: 'archived',
        },
      }),
    })
    await this.requestConversationList()
  }

  startRenameConversation(conversationId: string, surfaceText = 'title') {
    const conversationIdNormalized = this.normalizeConversationId(conversationId)
    const conversation = this.conversationById[conversationIdNormalized]
    if (!conversation) return
    this.conversationRenameEditId = conversationIdNormalized
    this.conversationRenameSurfaceText = surfaceText
    this.conversationRenameDraftText = String(conversation.metadata?.title || conversation.metadata?.templateName || 'Conversation')
  }

  cancelRenameConversation() {
    this.conversationRenameEditId = ''
    this.conversationRenameSurfaceText = ''
    this.conversationRenameDraftText = ''
  }

  async submitRenameConversation(conversationId: string, titleTextRaw?: string) {
    const conversationIdNormalized = this.normalizeConversationId(conversationId)
    if (!conversationIdNormalized || this.isConversationRenameSaving) return
    const conversation = this.conversationById[conversationIdNormalized]
    const titleText = String(titleTextRaw ?? this.conversationRenameDraftText).trim()
    const titlePrevious = String(conversation?.metadata?.title || conversation?.metadata?.templateName || 'Conversation')
    if (!titleText || titleText === titlePrevious) {
      this.cancelRenameConversation()
      return
    }
    runInAction(() => {
      this.isConversationRenameSaving = true
      this.errorText = ''
    })
    try {
      const data = await requestAuthenticatedJson<ConversationItem>('/api/conversation/rename', {
        method: 'POST',
        body: JSON.stringify({
          conversationId: conversationIdNormalized,
          titleText,
          timezone: new Date().getTimezoneOffset() * -1,
        }),
      })
      runInAction(() => {
        this.upsertConversation(data)
        this.conversationRenameEditId = ''
        this.conversationRenameSurfaceText = ''
        this.conversationRenameDraftText = ''
      })
    } catch (error: unknown) {
      runInAction(() => {
        this.errorText = String(error)
      })
    } finally {
      runInAction(() => {
        this.isConversationRenameSaving = false
      })
    }
  }

  async moveConversationToTrashbin(conversationId: string) {
    const conversationIdNormalized = this.normalizeConversationId(conversationId)
    if (!conversationIdNormalized) return
    runInAction(() => {
      this.errorText = ''
      this.noticeText = 'Deleting to trashbin'
    })
    try {
      const data = await requestAuthenticatedJson<ConversationItem>('/api/conversation/trashbin/update', {
        method: 'POST',
        body: JSON.stringify({
          conversationId: conversationIdNormalized,
          isInTrashbin: true,
          timezone: new Date().getTimezoneOffset() * -1,
        }),
      })
      runInAction(() => {
        this.upsertConversation(data)
        this.noticeText = ''
      })
      await this.requestConversationList(true)
    } catch (error: unknown) {
      runInAction(() => {
        this.errorText = String(error)
        this.noticeText = ''
      })
    }
  }

  async deleteConversation(conversationId: string) {
    const conversationIdNormalized = this.normalizeConversationId(conversationId)
    if (!conversationIdNormalized) return
    runInAction(() => {
      this.errorText = ''
      this.noticeText = 'Deleting conversation'
    })
    try {
      await requestAuthenticatedJson('/api/conversation/delete', {
        method: 'POST',
        body: JSON.stringify({
          conversationId: conversationIdNormalized,
        }),
      })
      runInAction(() => {
        delete this.conversationById[conversationIdNormalized]
        delete this.eventListByConversationId[conversationIdNormalized]
        this.conversationIdList = this.conversationIdList.filter((item) => item !== conversationIdNormalized)
        if (this.conversationSelectedId === conversationIdNormalized) {
          this.conversationSelectedId = ''
          this.pageCurrentKey = PAGE_KEY.conversationNew
        }
        this.noticeText = ''
      })
    } catch (error: unknown) {
      runInAction(() => {
        this.errorText = String(error)
        this.noticeText = ''
      })
    }
  }
}

export const appStore = new AppStore()
