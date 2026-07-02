import { MessageBar, RefreshIcon } from '@wwf971/react-comp-misc'
import { appStore } from '../store/appStore'
import './Panel.css'

type AppMessageBarProps = {
  statusText: 'error' | 'info' | 'loading' | 'success'
  messageText: string
  isRefreshVisible?: boolean
}

const AppMessageBar = ({ statusText, messageText, isRefreshVisible = false }: AppMessageBarProps) => {
  if (!messageText) return null
  return (
    <MessageBar
      data={{
        messageState: {
          status: statusText,
          messageText,
        },
        contentItems: [
          {
            id: 'message',
            type: 'text',
            text: messageText,
          },
          ...(isRefreshVisible ? [{
            id: 'refresh',
            type: 'custom',
            compKey: 'refresh',
            data: {
              isDisabled: appStore.isRefreshRetryRunning,
            },
          }] : []),
        ],
      }}
      config={{
        isOneLine: true,
        isPersistent: false,
        className: 'app-message-bar',
        getComp: (item: any) => {
          if (item.compKey === 'refresh') return RefreshButton
          return null
        },
      }}
      onEvent={(eventType) => {
        if (eventType === 'refreshRequest') {
          appStore.restartRefreshLoop()
        }
      }}
    />
  )
}

const RefreshButton = ({ data = {}, onEvent }: { data?: { isDisabled?: boolean }, onEvent?: (eventType: string) => void }) => (
  <button
    type="button"
    className="app-message-bar-refresh-btn"
    disabled={data.isDisabled === true}
    title="Retry refresh"
    onClick={() => onEvent?.('refreshRequest')}
  >
    <RefreshIcon width={14} height={14} />
  </button>
)

export default AppMessageBar
