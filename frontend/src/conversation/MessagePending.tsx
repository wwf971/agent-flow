import { observer } from 'mobx-react-lite'
import { SpinningCircle } from '@wwf971/react-comp-misc'
import { MessagePendingData } from '../store/appStore'
import RoleCard from './RoleCard'
import './Message.css'

type MessagePendingProps = {
  data: MessagePendingData
}

const MessagePending = observer(({ data }: MessagePendingProps) => {
  if (!data.isVisible) return null
  return (
    <div className="conversation-message-row">
      <RoleCard roleText={data.roleText} roleToneText="pending" />
      <div className="conversation-message-box conversation-message-box-pending">
        <div className="conversation-message-header">
          <div className="conversation-message-event-type-inline">
            {data.typeText}
            {data.subtypeText ? ` / ${data.subtypeText}` : ''}
          </div>
        </div>
        <div className="conversation-message-pending-body">
          <SpinningCircle width={14} height={14} />
          {data.detailLineList?.length ? (
            <div className="conversation-message-pending-detail-list">
              {data.detailLineList.map((lineText) => (
                <div className="conversation-message-pending-detail" key={lineText}>
                  {lineText}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
})

export default MessagePending
