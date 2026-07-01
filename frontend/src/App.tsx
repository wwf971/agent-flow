import { useEffect } from 'react'
import { observer } from 'mobx-react-lite'
import { reaction } from 'mobx'
import { Login, PanelDual } from '@wwf971/react-comp-misc'
import Header from './Header'
import ResourceTree from './ResourceTree'
import ResourcePanel from './ResourcePanel'
import { appStore, authStore } from './store/appStore'
import './App.css'

const App = observer(() => {
  useEffect(() => {
    authStore.initialize()
    const disposeLoginReaction = reaction(
      () => authStore.isLoggedIn,
      (isLoggedIn) => {
        if (isLoggedIn && !appStore.isBootstrapped) {
          appStore.bootstrap()
        }
      },
      { fireImmediately: true },
    )
    return () => {
      disposeLoginReaction()
      appStore.disconnectUpdateSocket()
      appStore.stopRefreshLoop()
    }
  }, [])

  if (authStore.isInitializing) {
    return (
      <div className="app-root app-login-root">
        <div className="app-init-text">loading</div>
      </div>
    )
  }

  if (!authStore.isLoggedIn) {
    return (
      <div className="app-root app-login-root">
        <Login
          title="react-agent-flow login"
          data={authStore.loginData}
          onDataChangeRequest={authStore.onDataChangeRequest}
          useAuthToken={true}
          showTokenAtLogin={true}
        />
      </div>
    )
  }

  return (
    <div className="app-root">
      <Header />
      <div className="app-body">
        <PanelDual orientation="vertical" initialWidth={300}>
          <div className="app-sidebar">
            <ResourceTree />
          </div>
          <div className="app-main">
            <ResourcePanel />
          </div>
        </PanelDual>
      </div>
    </div>
  )
})

export default App
