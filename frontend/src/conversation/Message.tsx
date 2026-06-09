import { observer } from 'mobx-react-lite'
import { EventItem } from '../store/appStore'
import RoleCard from './RoleCard'

type MessageProps = {
  data: EventItem
}

const Message = observer(({ data }: MessageProps) => {
  const roleData = resolveRoleData(data.typeText)
  const displayData = resolveDisplayData(data)
  return (
    <div className="conversation-message-row">
      <RoleCard roleText={roleData.roleText} roleToneText={roleData.roleToneText} />
      <div className={`conversation-message-box conversation-message-box-${roleData.roleToneText}`}>
        <div className="conversation-message-event-type">
          {data.typeText}
          {data.subtypeText ? ` / ${data.subtypeText}` : ''}
        </div>
        {displayData.text ? (
          <div className="conversation-message-text">{displayData.text}</div>
        ) : null}
        {displayData.jsonText ? (
          <pre className="conversation-message-json">{displayData.jsonText}</pre>
        ) : null}
      </div>
    </div>
  )
})

function resolveRoleData(typeText: string) {
  if (typeText === 'userMessage') {
    return {
      roleText: 'You',
      roleToneText: 'user',
    }
  }
  if (typeText === 'orchestratorMessage') {
    return {
      roleText: 'Orchestrator',
      roleToneText: 'orchestrator',
    }
  }
  if (typeText === 'EndAbnormal') {
    return {
      roleText: 'System',
      roleToneText: 'error',
    }
  }
  return {
    roleText: 'Agent',
    roleToneText: 'agent',
  }
}

function resolveDisplayData(data: EventItem) {
  const textRaw = String(data.contentText || '')
  if (data.typeText === 'orchestratorMessage' && data.subtypeText === 'toolResult') {
    return {
      text: textRaw,
      jsonText: '',
    }
  }
  const jsonTextFromText = tryFormatJsonText(textRaw)
  if (jsonTextFromText) {
    return {
      text: '',
      jsonText: jsonTextFromText,
    }
  }
  if (data.contentJson !== undefined && data.contentJson !== null) {
    return {
      text: textRaw,
      jsonText: JSON.stringify(data.contentJson, null, 2),
    }
  }
  return {
    text: textRaw,
    jsonText: '',
  }
}

function tryFormatJsonText(textRaw: string) {
  const textTrimmed = textRaw.trim()
  if (!textTrimmed) return ''
  if (!textTrimmed.startsWith('{') && !textTrimmed.startsWith('[')) return ''
  try {
    return JSON.stringify(JSON.parse(textTrimmed), null, 2)
  } catch {
    return ''
  }
}

export default Message
