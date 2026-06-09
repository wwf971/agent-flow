import { observer } from 'mobx-react-lite'
import { EndpointCard } from '@wwf971/react-comp-misc'
import { appStore } from '../store/appStore'

const TemplatePanel = observer(() => {
  const template = appStore.templateSelected
  if (!template) {
    return <div className="panel-empty-text">No template selected</div>
  }
  return (
    <div className="panel-root">
      <div className="panel-title">Template</div>
      {appStore.getMessageGlobalErrorText() ? <div className="message-error">{appStore.getMessageGlobalErrorText()}</div> : null}
      {appStore.getMessageGlobalNoticeText() ? <div className="message-info">{appStore.getMessageGlobalNoticeText()}</div> : null}
      <EndpointCard
        data={{
          id: template.key,
          titleText: template.name,
          descriptionText: template.description,
          keyValues: [
            { key: 'key', value: template.key },
          ],
        }}
        config={{
          actionItems: [
            { id: 'create', labelText: 'New Conversation based on this Template' },
          ],
        }}
        onEvent={(eventType, eventData) => {
          if (eventType === 'action' && eventData.actionId === 'create') {
            appStore.createConversationFromTemplate(template.key)
          }
        }}
      />
    </div>
  )
})

export default TemplatePanel
