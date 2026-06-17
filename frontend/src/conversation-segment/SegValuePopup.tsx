import { useMemo } from 'react'
import { JsonCompMobx } from '@wwf971/react-comp-misc'
import './SegValuePopup.css'

type SegValuePopupProps = {
  titleText: string
  value: unknown
  onClose: () => void
}

function createJsonViewData(value: unknown) {
  if (value === null || typeof value !== 'object') return null
  return JSON.parse(JSON.stringify(value))
}

const SegValuePopup = ({ titleText, value, onClose }: SegValuePopupProps) => {
  const jsonViewData = useMemo(() => createJsonViewData(value), [value])
  return (
    <div className="conversation-value-popup-backdrop">
      <div className="conversation-value-popup">
        <div className="conversation-value-popup-header">
          <div className="conversation-value-popup-title">{titleText}</div>
          <button type="button" className="conversation-value-popup-close-btn" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="conversation-value-popup-body">
          {jsonViewData ? (
            <JsonCompMobx
              data={jsonViewData}
              isEditable={false}
              isKeyEditable={false}
              isValueEditable={false}
            />
          ) : (
            <pre className="conversation-value-popup-text">{String(value ?? '')}</pre>
          )}
        </div>
      </div>
    </div>
  )
}

export default SegValuePopup
