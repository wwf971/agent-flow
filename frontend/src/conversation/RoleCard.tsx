import { observer } from 'mobx-react-lite'
import './RoleCard.css'

type RoleCardProps = {
  roleText: string
  roleToneText: string
}

const RoleCard = observer(({ roleText, roleToneText }: RoleCardProps) => {
  return (
    <div className={`conversation-role-card conversation-role-card-${roleToneText}`}>
      {roleText}
    </div>
  )
})

export default RoleCard
