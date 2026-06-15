import { useState } from 'react'
import SegValuePopup from './SegValuePopup'

type AbbreviatedValueProps = {
  pathText: string
  value: unknown
  charLimit?: number
}

function buildPreviewText(value: unknown, charLimit: number) {
  const valueText = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  if (valueText.length <= charLimit) return valueText
  return `${valueText.slice(0, charLimit)}...`
}

const AbbreviatedValue = ({ pathText, value, charLimit = 180 }: AbbreviatedValueProps) => {
  const [isPopupOpen, setIsPopupOpen] = useState(false)
  const previewText = buildPreviewText(value, charLimit)
  return (
    <div className="conversation-abbreviated-value">
      <pre className="conversation-abbreviated-value-preview">{previewText}</pre>
      <button
        type="button"
        className="conversation-abbreviated-value-btn"
        onClick={() => setIsPopupOpen(true)}
      >
        View full
      </button>
      {isPopupOpen ? (
        <SegValuePopup
          titleText={pathText}
          value={value}
          onClose={() => setIsPopupOpen(false)}
        />
      ) : null}
    </div>
  )
}

export default AbbreviatedValue
