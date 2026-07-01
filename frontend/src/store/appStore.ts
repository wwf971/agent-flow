import { makeAutoObservable, runInAction } from 'mobx'
import { createAuthStore } from '@wwf971/react-comp-misc'
import { ApiRequestError, requestAuthenticatedJson } from '../apiRequest'
import { isUpdateWebSocketEnabled, resolveApiUrl, resolveWebSocketUrl } from '../publicPath'
import { sortByGlobalRank } from './lexoRank'

type ApiResponse<T = Record<string, any>> = {
  code: number
  data?: T
  message?: string
}

async function requestJsonData(url: string, options: RequestInit = {}) {
  const response = await fetch(resolveApiUrl(url), {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  })
  const body = (await response.json()) as ApiResponse
  if (response.status < 200 || response.status >= 300 || body.code < 0) {
    throw new Error(body.message || `request failed: ${response.status}`)
  }
  return body.data || {}
}

export const authStore = createAuthStore({
  storageKey: 'react-agent-flow-auth-token',
  autoLoginStorageKey: 'react-agent-flow-auto-login-enabled',
  requestJsonData,
  loginSuccessMessage: 'Login completed',
  logoutSuccessMessage: 'Logged out',
})

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
  rankGlobal: string
  parentId: string
  version?: number
  stateCode?: number
  execStatusCode?: number
  leaseId?: string
  leaseWorkerId?: string
  leaseExpireAt?: string
  leaseRetryCount?: number
  leaseRetryAfterAt?: string
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

type ConversationCreateFromTemplateResult = ConversationItem & {
  eventGeneratedList?: EventItem[]
}

export type MessagePendingData = {
  isVisible: boolean
  roleText: string
  typeText: string
  subtypeText: string
  detailLineList?: string[]
}

export type OperationState = {
  statusText: 'idle' | 'running' | 'success' | 'error'
  messageText: string
}

const OPERATION_KEY = {
  conversationCreate: 'conversation-create',
  messageSend: 'message-send',
} as const

const STATE_WAIT_SUBAGENT = 400

const EXEC_STATUS_PENDING = 10
const EXEC_STATUS_RUNNING = 20
const EXEC_STATUS_RETRY_WAIT = 30

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
  childConversationIdListByParentId: Record<string, string[]> = {}
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
  isConversationReorderSaving = false
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
      rankGlobal: String(item.rankGlobal || ''),
      parentId: this.normalizeConversationId((item as ConversationItem).parentId),
      version: Number(item.version || 0),
      stateCode: Number(item.stateCode || 100),
      execStatusCode: Number(item.execStatusCode || 0),
      leaseId: String(item.leaseId || ''),
      leaseWorkerId: String(item.leaseWorkerId || ''),
      leaseExpireAt: String(item.leaseExpireAt || ''),
      leaseRetryCount: Number(item.leaseRetryCount || 0),
      leaseRetryAfterAt: String(item.leaseRetryAfterAt || ''),
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
      || Number(item.stateCode || 100) === STATE_WAIT_SUBAGENT
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

  get conversationListAll() {
    return Object.values(this.conversationById)
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
        detailLineList: [],
      }
    }
    const statusText = String(conversation.metadata?.statusText || 'active')
    const templateKey = String(conversation.metadata?.templateKey || 'free-talk')
    const stateCode = Number(conversation.stateCode || 100)
    const execStatusCode = Number(conversation.execStatusCode || 0)
    const operationTemplateStart = this.operationByConversationId[conversation.conversationId]?.['template-start']
    const isTemplateStarting = statusText === 'starting' || operationTemplateStart?.statusText === 'running'
    const isConversationWorkActive = (
      stateCode < 0
      || execStatusCode === EXEC_STATUS_PENDING
      || execStatusCode === EXEC_STATUS_RUNNING
      || execStatusCode === EXEC_STATUS_RETRY_WAIT
    )
    const isMessageOperationWaiting = (
      this.getOperationConversation(conversation.conversationId, OPERATION_KEY.messageSend).statusText === 'running'
      && stateCode !== STATE_WAIT_SUBAGENT
    )
    const isWaitingForReply = (
      isMessageOperationWaiting
      || (
        statusText === 'active'
        && templateKey !== 'mcp-tool-all'
        && isConversationWorkActive
      )
    )
    if (!isTemplateStarting && !isWaitingForReply) {
      return {
        isVisible: false,
        roleText: '',
        typeText: '',
        subtypeText: '',
        detailLineList: [],
      }
    }
    if (statusText === 'failed' || statusText === 'archived' || conversation.isInTrashbin === true) {
      return {
        isVisible: false,
        roleText: '',
        typeText: '',
        subtypeText: '',
        detailLineList: [],
      }
    }
    return {
      isVisible: true,
      roleText: isTemplateStarting ? 'Agent' : 'Agent',
      typeText: isTemplateStarting ? 'agentMessage' : 'agentMessage',
      subtypeText: 'pending',
      detailLineList: this.buildPendingDetailLineList(conversation),
    }
  }

  buildPendingDetailLineList(conversation: ConversationItem) {
    const lineList: string[] = []
    const execStatusCode = Number(conversation.execStatusCode || 0)
    const retryCount = Number(conversation.leaseRetryCount || 0)
    if (execStatusCode === EXEC_STATUS_PENDING) {
      lineList.push('Status: Pending')
    } else if (execStatusCode === EXEC_STATUS_RUNNING) {
      lineList.push('Status: Running')
    } else if (execStatusCode === EXEC_STATUS_RETRY_WAIT) {
      lineList.push('Status: Retry Wait')
    }
    lineList.push(`Retry Num: ${retryCount}`)
    if (conversation.leaseWorkerId) {
      lineList.push(`Worker: ${conversation.leaseWorkerId}`)
    }
    if (conversation.leaseExpireAt) {
      lineList.push(`Lease Expire: ${conversation.leaseExpireAt}`)
    }
    if (conversation.leaseRetryAfterAt) {
      lineList.push(`Retry After: ${conversation.leaseRetryAfterAt}`)
    }
    const errorText = String(conversation.metadata?.iterationErrorText || '')
    if (errorText) {
      lineList.push(`Last Error: ${errorText}`)
    }
    return lineList
  }

  get conversationListActive() {
    return sortByGlobalRank(this.conversationListAll.filter((item) => (
      item.isInTrashbin !== true
      && !item.parentId
      && String(item.metadata?.statusText || 'active') !== 'archived'
    )))
  }

  get conversationListHistory() {
    return sortByGlobalRank(this.conversationListAll.filter((item) => (
      item.isInTrashbin !== true
      && !item.parentId
      && String(item.metadata?.statusText || '') === 'archived'
    )))
  }

  get conversationListPresent() {
    return sortByGlobalRank(this.conversationListAll.filter((item) => (
      item.isInTrashbin !== true
      && !item.parentId
    )))
  }

  get conversationListTrashbin() {
    return this.conversationListAll.filter((item) => item.isInTrashbin === true && !item.parentId)
  }

  getChildConversationIdList(parentConversationId: string) {
    const parentId = this.normalizeConversationId(parentConversationId)
    const childIdListLoaded = this.childConversationIdListByParentId[parentId]
    if (childIdListLoaded) return childIdListLoaded
    const metadata = this.conversationById[parentId]?.metadata || {}
    const childIdList = Array.isArray(metadata.childConversationIdList) ? metadata.childConversationIdList : []
    return childIdList.map((item) => this.normalizeConversationId(item)).filter(Boolean)
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

  async connectUpdateSocket() {
    if (!isUpdateWebSocketEnabled()) {
      this.socketStatusText = 'disabled'
      return
    }
    if (this.socketUpdate) return
    const token = await authStore.getServiceToken()
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
    await this.requestConversationListAll(true)
    if (conversationIdNormalized && conversationIdNormalized === this.conversationSelectedId) {
      await this.requestEventList(conversationIdNormalized, true)
    }
    const conversationChanged = this.conversationById[conversationIdNormalized]
    const parentId = this.normalizeConversationId(conversationChanged?.parentId)
    if (parentId && parentId === this.conversationSelectedId) {
      await this.requestChildConversationList(parentId, true)
    }
    if (this.conversationSelectedId) {
      await this.requestSubagentChildrenForSelected(true)
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
          if (
            !itemList.some((item) => item.conversationId === conversationId)
            && !conversationByIdNext[conversationId]?.parentId
          ) {
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

  async requestConversationListAll(isQuiet = true) {
    try {
      const data = await requestAuthenticatedJson<{ items: ConversationItem[] }>('/api/conversation/list', {
        method: 'POST',
        body: JSON.stringify({ pageSize: 200, parentId: '*' }),
      })
      runInAction(() => {
        const itemList = (data.items || []).map((item) => this.normalizeConversationItem(item))
        const conversationByIdNext: Record<string, ConversationItem> = { ...this.conversationById }
        const childByParentNext: Record<string, string[]> = { ...this.childConversationIdListByParentId }
        itemList.forEach((item) => {
          conversationByIdNext[item.conversationId] = item
          this.syncConversationOperationState(item)
        })
        const rootIdList = itemList
          .filter((item) => !item.parentId)
          .map((item) => item.conversationId)
        this.conversationIdList = rootIdList
        itemList
          .filter((item) => item.parentId)
          .forEach((item) => {
            const childIdList = childByParentNext[item.parentId] || []
            if (!childIdList.includes(item.conversationId)) {
              childByParentNext[item.parentId] = [...childIdList, item.conversationId]
            }
          })
        Object.keys(childByParentNext).forEach((parentId) => {
          const childItemList = childByParentNext[parentId]
            .map((conversationId) => conversationByIdNext[conversationId])
            .filter(Boolean)
          childByParentNext[parentId] = this.buildChildConversationIdList(parentId, childItemList, conversationByIdNext)
        })
        this.conversationById = conversationByIdNext
        this.childConversationIdListByParentId = childByParentNext
      })
    } catch (error: unknown) {
      if (!isQuiet) {
        runInAction(() => {
          this.errorText = String(error)
        })
      }
    }
  }

  async requestChildConversationList(parentConversationId: string, isQuiet = true) {
    const parentId = this.normalizeConversationId(parentConversationId)
    if (!parentId) return
    try {
      const data = await requestAuthenticatedJson<{ items: ConversationItem[] }>('/api/conversation/list', {
        method: 'POST',
        body: JSON.stringify({ pageSize: 100, parentId }),
      })
      runInAction(() => {
        const itemList = (data.items || []).map((item) => this.normalizeConversationItem(item))
        const conversationByIdNext: Record<string, ConversationItem> = { ...this.conversationById }
        itemList.forEach((item) => {
          conversationByIdNext[item.conversationId] = item
          this.syncConversationOperationState(item)
        })
        this.conversationById = conversationByIdNext
        this.childConversationIdListByParentId[parentId] = this.buildChildConversationIdList(parentId, itemList, conversationByIdNext)
      })
    } catch (error: unknown) {
      if (!isQuiet) {
        runInAction(() => {
          this.errorText = String(error)
        })
      }
    }
  }

  buildChildConversationIdList(
    parentId: string,
    itemList: ConversationItem[],
    conversationByIdSource: Record<string, ConversationItem> = this.conversationById,
  ) {
    const metadata = conversationByIdSource[parentId]?.metadata || {}
    const childIdListFromParent = Array.isArray(metadata.childConversationIdList)
      ? metadata.childConversationIdList.map((item) => this.normalizeConversationId(item)).filter(Boolean)
      : []
    const itemIdSet = new Set(itemList.map((item) => item.conversationId))
    const orderedIdList = childIdListFromParent.filter((conversationId) => itemIdSet.has(conversationId))
    const orderedIdSet = new Set(orderedIdList)
    const extraIdList = itemList
      .filter((item) => !orderedIdSet.has(item.conversationId))
      .sort((itemA, itemB) => {
        const timeCompare = String(itemA.createAt || '').localeCompare(String(itemB.createAt || ''))
        if (timeCompare !== 0) return timeCompare
        return itemA.conversationId.localeCompare(itemB.conversationId)
      })
      .map((item) => item.conversationId)
    return [...orderedIdList, ...extraIdList]
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
      this.requestConversationListAll(isQuiet),
      this.requestEventList(conversationIdNormalized, isQuiet),
    ])
    await this.requestSubagentChildrenForSelected(isQuiet)
  }

  async requestSubagentChildrenForSelected(isQuiet = true) {
    const conversationId = this.normalizeConversationId(this.conversationSelectedId)
    if (!conversationId) return
    await this.requestChildConversationList(conversationId, isQuiet)
    const childIdList = this.getChildConversationIdList(conversationId)
    await Promise.all(childIdList.map((childId) => this.requestEventList(childId, true)))
  }

  async requestSubagentChildrenForEvent(event: EventItem, isQuiet = true) {
    const parentId = this.normalizeConversationId(event.conversationId)
    if (!parentId) return
    await this.requestChildConversationList(parentId, isQuiet)
    const childIdList = this.getSubagentChildIdListFromEvent(event)
    await Promise.all(childIdList.map((childId) => this.requestEventList(childId, true)))
  }

  getSubagentChildIdListFromEvent(event: EventItem) {
    const metadata = event.metadata || {}
    const contentData = event.contentJson?.data?.[0]?.data || {}
    const childIdListRaw = (
      Array.isArray(metadata.childConversationIdList)
        ? metadata.childConversationIdList
        : contentData.childConversationIdList
    )
    const childIdList = Array.isArray(childIdListRaw) ? childIdListRaw : []
    if (childIdList.length) {
      return childIdList.map((item) => this.normalizeConversationId(item)).filter(Boolean)
    }
    return this.getChildConversationIdList(event.conversationId)
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
      const data = await requestAuthenticatedJson<ConversationCreateFromTemplateResult>('/api/conversation/create/from-template', {
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
        const eventGeneratedList = data.eventGeneratedList || []
        eventGeneratedList.forEach((event) => {
          this.appendEventIfMissing(event)
        })
        if (data.metadata?.statusText === 'starting') {
          this.setOperationByConversationId(data.conversationId, 'template-start', createOperationState('running', 'Starting conversation'))
        }
      })
      await Promise.all([
        this.requestConversationList(true),
        this.requestEventList(data.conversationId, true),
      ])
      return data
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
      return null
    }
  }

  async createEmptyConversation() {
    await this.createConversationFromTemplate('free-talk')
  }

  async createConversationFromTemplateDefault(templateKey: string) {
    await this.createConversationFromTemplate(templateKey)
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
    if (conversation.parentId) return
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
    if (conversation?.parentId) {
      this.cancelRenameConversation()
      return
    }
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
    if (this.conversationById[conversationIdNormalized]?.parentId) return
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

  async reorderConversation(conversationId: string, conversationIdBefore: string, conversationIdAfter: string) {
    const conversationIdNormalized = this.normalizeConversationId(conversationId)
    if (!conversationIdNormalized || this.isConversationReorderSaving) return
    if (this.conversationById[conversationIdNormalized]?.parentId) return
    runInAction(() => {
      this.errorText = ''
      this.noticeText = 'Reordering conversation'
      this.isConversationReorderSaving = true
    })
    try {
      const data = await requestAuthenticatedJson<ConversationItem>('/api/conversation/reorder', {
        method: 'POST',
        body: JSON.stringify({
          conversationId: conversationIdNormalized,
          conversationIdBefore: this.normalizeConversationId(conversationIdBefore),
          conversationIdAfter: this.normalizeConversationId(conversationIdAfter),
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
    } finally {
      runInAction(() => {
        this.isConversationReorderSaving = false
      })
    }
  }

  async deleteConversation(conversationId: string) {
    const conversationIdNormalized = this.normalizeConversationId(conversationId)
    if (!conversationIdNormalized) return
    if (this.conversationById[conversationIdNormalized]?.parentId) return
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
