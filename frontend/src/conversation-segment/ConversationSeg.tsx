import JsonSegmentView from './JsonSegmentView'

export type ConversationSegment = {
  type: string
  data: unknown
  outputSchema?: Record<string, unknown>
  displayRules?: Record<string, string>
}

type ConversationSegProps = {
  segment: ConversationSegment
}

const ConversationSeg = ({ segment }: ConversationSegProps) => {
  if (segment.type === 'json') {
    return <JsonSegmentView data={segment.data} displayRules={segment.displayRules || {}} />
  }
  return (
    <div className="conversation-message-text">
      {String(segment.data ?? '')}
    </div>
  )
}

export default ConversationSeg
