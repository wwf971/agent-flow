import { observer } from 'mobx-react-lite'
import { AuthStatusButton } from '@wwf971/react-comp-misc'
import { PAGE_KEY, appStore, authStore } from './store/appStore'
import './Header.css'

const Header = observer(() => {
  return (
    <div className="app-header-root">
      <div className="app-header-title">react agent flow</div>
      <div className="app-header-spacer" />
      <button
        type="button"
        className={`app-header-link ${appStore.pageCurrentKey === PAGE_KEY.conversationNew ? 'is-active' : ''}`}
        onClick={() => {
          appStore.selectNewConversation()
        }}
      >
        new conversation
      </button>
      <button
        type="button"
        className={`app-header-link ${appStore.pageCurrentKey === PAGE_KEY.template ? 'is-active' : ''}`}
        onClick={() => {
          const templateKey = appStore.templateSelectedKey || appStore.templateList[0]?.key || ''
          if (templateKey) {
            appStore.selectTemplate(templateKey)
          }
        }}
      >
        templates
      </button>
      <AuthStatusButton
        data={{
          isLoggedIn: authStore.isLoggedIn,
          username: authStore.username,
        }}
        config={{
          buttonClassName: 'app-header-link',
          menuAlign: 'right',
          minWidth: 170,
        }}
        onEvent={(eventType) => {
          if (eventType === 'go-login') {
            authStore.goToLoginPage()
          }
          if (eventType === 'sign-out') {
            void authStore.logout()
          }
        }}
      />
    </div>
  )
})

export default Header
