import { authStore } from './store/authStore'
import { resolveApiUrl } from './publicPath'

export type ApiResponse<T = any> = {
  code: number
  data?: T
  message?: string
}

export class ApiRequestError<T = any> extends Error {
  status: number
  code: number
  data?: T

  constructor(message: string, status: number, code: number, data?: T) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.code = code
    this.data = data
  }
}

export async function requestAuthenticatedJson<T = any>(url: string, options: RequestInit = {}) {
  const token = authStore.token
  const optionsNext: RequestInit = { ...options }
  if (token && optionsNext.body && typeof optionsNext.body === 'string') {
    try {
      const bodyData = JSON.parse(optionsNext.body)
      if (bodyData && typeof bodyData === 'object' && !Array.isArray(bodyData)) {
        optionsNext.body = JSON.stringify({
          ...bodyData,
          authToken: token,
        })
      }
    } catch {
      // keep original body
    }
  } else if (token && String(optionsNext.method || 'GET').toUpperCase() === 'POST') {
    optionsNext.body = JSON.stringify({ authToken: token })
  }
  const response = await fetch(resolveApiUrl(url), {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...authStore.getAuthHeaders(),
      ...(optionsNext.headers || {}),
    },
    ...optionsNext,
  })
  const body = (await response.json()) as ApiResponse<T>
  if (response.status < 200 || response.status >= 300 || body.code < 0) {
    throw new ApiRequestError(body.message || `request failed: ${response.status}`, response.status, body.code, body.data)
  }
  return body.data as T
}
