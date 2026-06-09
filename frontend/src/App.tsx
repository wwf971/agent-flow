import { useEffect } from 'react'
import { observer } from 'mobx-react-lite'
import { reaction } from 'mobx'
import { Login } from '@wwf971/react-comp-misc'
import ResourceTree from './ResourceTree'
import ResourcePanel from './ResourcePanel'
import { appStore } from './store/appStore'
import { authStore } from './store/authStore'
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
      <div className="app-layout">
        <div className="app-sidebar">
          <ResourceTree />
        </div>
        <div className="app-main">
          <ResourcePanel />
        </div>
      </div>
    </div>
  )
})

export default App
