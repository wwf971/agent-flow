declare module '@wwf971/react-comp-misc' {
  import type { ComponentType, SVGProps } from 'react'

  export const AddIcon: ComponentType<SVGProps<SVGSVGElement> & { size?: number }>
  export const EditIcon: ComponentType<SVGProps<SVGSVGElement> & { width?: number; height?: number }>
  export const FileIcon: ComponentType<SVGProps<SVGSVGElement> & { size?: number }>
  export const RefreshIcon: ComponentType<SVGProps<SVGSVGElement> & { width?: number; height?: number; className?: string; style?: Record<string, unknown> }>
  export const SpinningCircle: ComponentType<{ width?: number; height?: number; color?: string }>
  export const ButtonWithDropDown: ComponentType<{
    data?: {
      label?: string
      items?: Array<Record<string, unknown>>
      emptyText?: string
    }
    config?: {
      isDisabled?: boolean
      className?: string
      menuClassName?: string
      minWidth?: number
    }
    onEvent?: (eventType: string, eventData: Record<string, unknown>) => Promise<void> | void
  }>

  export const Login: ComponentType<{
    title?: string
    data?: unknown
    onDataChangeRequest?: (type: string, params?: Record<string, unknown>) => Promise<{ code: number }> | { code: number }
    useAuthToken?: boolean
    showTokenAtLogin?: boolean
  }>

  export const TreeView: ComponentType<{
    rootItemIds?: string[]
    getItemDataById?: (itemId: string) => unknown
    onDataChangeRequest?: (type: string, params?: Record<string, unknown>) => Promise<{ code: number }> | { code: number }
    selectedItemId?: string
    onItemClick?: (itemId: string, itemData?: unknown) => Promise<void> | void
    onItemContextMenu?: (itemId: string, itemData: unknown, event: MouseEvent) => Promise<void> | void
    getItemComp?: (itemData: unknown) => ComponentType<any> | null
    className?: string
    isToggleExpandOnItemClick?: boolean
  }>

  export const MenuComp: ComponentType<{
    data?: {
      items?: Array<Record<string, unknown>>
      position?: { x: number; y: number }
      emptyText?: string
    }
    config?: {
      minWidth?: number
      className?: string
    }
    onEvent?: (eventType: string, eventData: Record<string, unknown>) => Promise<void> | void
  }>

  export const KeyValues: ComponentType<{
    data?: Array<{ key: string; value?: unknown; rowClassName?: string }>
    isEditable?: boolean
    keyColWidth?: string
    alignColumn?: boolean
    isWrap?: boolean
    onChangeAttempt?: (index: number, field: string, nextValue: string) => Promise<void> | void
    getComp?: (componentName: string, context: unknown) => unknown
  }>

  export const EndpointCard: ComponentType<{
    data?: {
      id?: string
      titleText?: string
      descriptionText?: string
      keyValues?: Array<{ key: string; value: string }>
      statusTagText?: string
      errorMessage?: string
    }
    config?: {
      isSelected?: boolean
      isLocked?: boolean
      isUnavailable?: boolean
      isSelectable?: boolean
      actionItems?: Array<{ id: string; labelText?: string; isVisible?: boolean; isDisabled?: boolean }>
    }
    onEvent?: (eventType: string, eventData: Record<string, unknown>) => Promise<void> | void
  }>
}
