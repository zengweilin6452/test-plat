/**
 * 404：路径不匹配任何导航项时给出返回入口。
 */
import { Link } from 'react-router-dom'
import { Empty } from '../components/Empty'

export function NotFoundPage() {
  return (
    <Empty
      icon="alert"
      title="页面不存在"
      description="地址可能已变更，请从左侧导航进入。"
      actions={<Link className="btn" to="/overview">返回工作台</Link>}
    />
  )
}
