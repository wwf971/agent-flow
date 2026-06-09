import { KeyboardEvent } from 'react'
import { observer } from 'mobx-react-lite'
import { SpinningCircle } from '@wwf971/react-comp-misc'
import { appStore } from '../store/appStore'

type UserInputProps = {
  isInputEnabled: boolean
  placeholderText: string
}

const UserInput = observer(({ isInputEnabled, placeholderText }: UserInputProps) => {
  return (
    <div className="composer-root">
      <textarea
        className="composer-textarea"
        value={appStore.messageDraftText}
        disabled={!isInputEnabled}
        placeholder={isInputEnabled ? 'Type user message' : placeholderText}
        onChange={(event) => appStore.setMessageDraftText(event.target.value)}
        onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
          if (event.key !== 'Enter') return
          if (event.altKey) return
          event.preventDefault()
          appStore.sendCurrentMessage()
        }}
      />
      <button
        type="button"
        className="send-btn"
        disabled={!isInputEnabled || !appStore.messageDraftText.trim()}
        onClick={() => appStore.sendCurrentMessage()}
      >
        {appStore.isConversationSending ? <SpinningCircle width={14} height={14} /> : 'Send'}
      </button>
    </div>
  )
})

export default UserInput
