import { useMemo } from 'react'
import { JsonCompMobx } from '@wwf971/react-comp-misc'
import AbbreviatedValue from './AbbreviatedValue'
import './SegJson.css'

type DisplayRules = Record<string, string>

type SegJsonProps = {
  data: unknown
  displayRules?: DisplayRules
}

function createJsonViewData(value: unknown) {
  if (value === null || typeof value !== 'object') return value
  return JSON.parse(JSON.stringify(value))
}

function normalizeJsonPath(pathText: string) {
  return pathText
    .replace(/\.\./g, '.')
    .replace(/^\./, '')
}

const SegJson = ({ data, displayRules = {} }: SegJsonProps) => {
  const jsonViewData = useMemo(() => createJsonViewData(data), [data])
  return (
    <div className="conversation-json-segment">
      <JsonCompMobx
        data={jsonViewData}
        isEditable={false}
        isKeyEditable={false}
        isValueEditable={false}
        getValueComp={({ path, value }: { path: string, value: unknown }) => {
          const pathText = normalizeJsonPath(path)
          if (displayRules[pathText] !== 'popup') return null
          return <AbbreviatedValue pathText={pathText} value={value} />
        }}
      />
    </div>
  )
}

export default SegJson
