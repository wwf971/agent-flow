import { observer } from 'mobx-react-lite'
import { PAGE_KEY, appStore } from './store/appStore'
import ConversationPanel from './conversation/ConversationPanel'
import NewConversationPanel from './panel/NewConversationPanel'
import TemplatePanel from './panel/TemplatePanel'

const ResourcePanel = observer(() => {
  if (appStore.pageCurrentKey === PAGE_KEY.template) {
    return <TemplatePanel />
  }
  if (appStore.pageCurrentKey === PAGE_KEY.conversation) {
    return <ConversationPanel />
  }
  return <NewConversationPanel />
})

export default ResourcePanel
