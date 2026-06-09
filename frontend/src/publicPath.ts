function getBasePath() {
  const basePath = String(import.meta.env.BASE_URL || '/')
  if (!basePath || basePath === '/') return ''
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
