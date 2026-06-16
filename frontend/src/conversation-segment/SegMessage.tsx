import SegJson from './SegJson'

export type SegMessageData = {
  type: string
  data: unknown
  outputSchema?: Record<string, unknown>
  displayRules?: Record<string, string>
}

type SegMessageProps = {
  segment: SegMessageData
}

const SegMessage = ({ segment }: SegMessageProps) => {
  if (segment.type === 'json') {
    return <SegJson data={segment.data} displayRules={segment.displayRules || {}} />
  }
  return (
    <div className="conversation-message-text">
      {String(segment.data ?? '')}
    </div>
  )
}

export default SegMessage
