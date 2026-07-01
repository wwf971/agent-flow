const APP_BASE_ASSET_PLACEHOLDER = '/__APP_BASE__/'
const APP_BASE_PATH_CANDIDATES = ['/agent-flow']

function getRuntimeBasePath() {
  if (typeof window === 'undefined') {
    return ''
  }
  const { pathname } = window.location
  return APP_BASE_PATH_CANDIDATES.find((basePath) => (
    pathname === basePath || pathname.startsWith(`${basePath}/`)
  )) || ''
}

function getBasePath() {
  const basePath = String(import.meta.env.BASE_URL || '/')
  if (!basePath || basePath === '/' || basePath === APP_BASE_ASSET_PLACEHOLDER) {
    return getRuntimeBasePath()
  }
  return basePath.endsWith('/') ? basePath.slice(0, -1) : basePath
}

export function resolveApiUrl(pathValue: string) {
  const value = String(pathValue || '')
  if (value.startsWith('http://') || value.startsWith('https://')) {
    return value
  }
  const basePath = getBasePath()
  if (!value.startsWith('/')) {
    return `${basePath}/${value}`
  }
  return `${basePath}${value}`
}

export function resolveWebSocketUrl(pathValue: string) {
  const value = resolveApiUrl(pathValue)
  const protocolText = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  if (value.startsWith('http://')) return `ws://${value.slice('http://'.length)}`
  if (value.startsWith('https://')) return `wss://${value.slice('https://'.length)}`
  return `${protocolText}//${window.location.host}${value}`
}

export function isUpdateWebSocketEnabled() {
  const value = String(import.meta.env.VITE_ENABLE_UPDATE_WS ?? '1').trim().toLowerCase()
  return !['0', 'false', 'no', 'off'].includes(value)
}
