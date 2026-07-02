import { observer } from 'mobx-react-lite'
import { EndpointCard } from '@wwf971/react-comp-misc'
import { appStore } from '../store/appStore'
import AppMessageBar from './AppMessageBar'
import './Panel.css'

const NewConversationPanel = observer(() => {
  return (
    <div className="panel-root">
      <div className="panel-title">New Conversation</div>
      <AppMessageBar
        statusText="error"
        messageText={appStore.getMessageGlobalErrorText()}
        isRefreshVisible={appStore.isRefreshLoopPaused}
      />
      <AppMessageBar statusText="info" messageText={appStore.getMessageGlobalNoticeText()} />
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
              actionItems: [{
                id: 'create',
                labelText: template.key === 'subagent-test' ? 'Create and Run' : 'Create from Template',
              }],
            }}
            onEvent={(eventType, eventData) => {
              if (eventType === 'action' && eventData.actionId === 'create') {
                appStore.createConversationFromTemplateDefault(template.key)
              }
            }}
          />
        ))}
      </div>
    </div>
  )
})

export default NewConversationPanel
