import { observer } from 'mobx-react-lite'
import { EndpointCard } from '@wwf971/react-comp-misc'
import { appStore } from '../store/appStore'
import './Panel.css'

const NewConversationPanel = observer(() => {
  return (
    <div className="panel-root">
      <div className="panel-title">New Conversation</div>
      {appStore.getMessageGlobalErrorText() ? <div className="message-error">{appStore.getMessageGlobalErrorText()}</div> : null}
      {appStore.getMessageGlobalNoticeText() ? <div className="message-info">{appStore.getMessageGlobalNoticeText()}</div> : null}
      <div className="card-list">
        <EndpointCard
          data={{
            id: 'empty',
            titleText: 'Empty Conversation',
            descriptionText: 'Start a free talk conversation without a special template.',
          }}
          config={{
            actionItems: [{ id: 'create', labelText: 'Create' }],
          }}
          onEvent={(eventType, eventData) => {
            if (eventType === 'action' && eventData.actionId === 'create') {
              appStore.createEmptyConversation()
            }
          }}
        />
        {appStore.templateList.map((template) => (
          <EndpointCard
            key={template.key}
            data={{
              id: template.key,
              titleText: template.name,
              descriptionText: template.description,
              keyValues: [{ key: 'templateKey', value: template.key }],
            }}
            config={{
              actionItems: [{ id: 'create', labelText: 'Create from Template' }],
            }}
            onEvent={(eventType, eventData) => {
              if (eventType === 'action' && eventData.actionId === 'create') {
                appStore.createConversationFromTemplate(template.key)
              }
            }}
          />
        ))}
      </div>
    </div>
  )
})

export default NewConversationPanel
