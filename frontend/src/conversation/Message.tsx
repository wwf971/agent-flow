import { useState } from 'react'
import { observer } from 'mobx-react-lite'
import * as ReactCompMisc from '@wwf971/react-comp-misc'
import { EventItem } from '../store/appStore'
import SegMessage, { SegMessageData } from '../conversation-segment/SegMessage'
import RoleCard from './RoleCard'
import MessageSubagent from './MessageSubagent'
import './Message.css'

const SegmentedControl = (ReactCompMisc as any).SegmentedControl

type MessageProps = {
  data: EventItem
}

const Message = observer(({ data }: MessageProps) => {
  if (data.typeText === 'orchestratorMessage' && data.subtypeText === 'subAgentStart') {
    return <MessageSubagent data={data} />
  }
  const roleData = resolveRoleData(data.typeText)
  const displayData = resolveDisplayData(data)
  const [viewMode, setViewMode] = useState(displayData.segmentList.length > 0 ? 'structured' : 'text')
  const modeCurrent = displayData.segmentList.length > 0 ? viewMode : 'text'
  return (
    <div className="conversation-message-row">
      <RoleCard roleText={roleData.roleText} roleToneText={roleData.roleToneText} />
      <div className={`conversation-message-box conversation-message-box-${roleData.roleToneText}`}>
        <div className="conversation-message-header">
          {displayData.segmentList.length > 0 ? (
            <div className="conversation-message-view-mode">
              <SegmentedControl
                data={modeCurrent}
                options={[
                  { value: 'structured', label: 'Structured' },
                  { value: 'text', label: 'Text' },
                ]}
                onChange={(value: string) => setViewMode(value)}
                widthMode="auto"
              />
            </div>
          ) : null}
          <div className="conversation-message-event-type-inline">
            {data.typeText}
            {data.subtypeText ? ` / ${data.subtypeText}` : ''}
          </div>
        </div>
        {modeCurrent === 'text' && displayData.text ? (
          <div className="conversation-message-text">{displayData.text}</div>
        ) : null}
        {modeCurrent === 'text' && displayData.jsonText ? (
          <pre className="conversation-message-json">{displayData.jsonText}</pre>
        ) : null}
        {modeCurrent === 'structured' ? (
          <div className="conversation-segment-list">
            {displayData.segmentList.map((segment, index) => (
              <SegMessage key={index} segment={segment} />
            ))}
          </div>
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
  const segmentList = getStructuredSegmentList(data.contentJson)
  if (segmentList.length > 0) {
    return {
      text: textRaw,
      jsonText: '',
      segmentList,
    }
  }
  const jsonTextFromText = tryFormatJsonText(textRaw)
  if (jsonTextFromText) {
    return {
      text: '',
      jsonText: jsonTextFromText,
      segmentList: [],
    }
  }
  if (data.contentJson !== undefined && data.contentJson !== null) {
    return {
      text: textRaw,
      jsonText: JSON.stringify(data.contentJson, null, 2),
      segmentList: [],
    }
  }
  return {
    text: textRaw,
    jsonText: '',
    segmentList: [],
  }
}

function getStructuredSegmentList(contentJson: unknown): SegMessageData[] {
  if (!contentJson || typeof contentJson !== 'object') return []
  const contentData = contentJson as { data?: unknown }
  if (!Array.isArray(contentData.data)) return []
  return contentData.data
    .filter((item): item is SegMessageData => (
      !!item
      && typeof item === 'object'
      && typeof (item as SegMessageData).type === 'string'
    ))
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
