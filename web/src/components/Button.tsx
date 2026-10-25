/**
 * 按钮（原型 .btn / .btn.primary / .btn.soft / .btn.danger / .btn.small / .btn.icon-only）。
 * 只做样式与 HTML 语义，不含业务逻辑。
 */
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Icon, type IconName } from './Icon'

export type ButtonKind = 'default' | 'primary' | 'soft' | 'danger'

interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  kind?: ButtonKind
  size?: 'default' | 'small'
  icon?: IconName
  /** 纯图标按钮（需要传 aria-label 或 title） */
  iconOnly?: boolean
  children?: ReactNode
}

export function Button({
  kind = 'default',
  size = 'default',
  icon,
  iconOnly = false,
  children,
  className,
  type = 'button',
  ...rest
}: ButtonProps) {
  const classes = ['btn']
  if (kind !== 'default') classes.push(kind)
  if (size === 'small') classes.push('small')
  if (iconOnly) classes.push('icon-only')
  if (className) classes.push(className)
  return (
    <button type={type} className={classes.join(' ')} {...rest}>
      {icon ? <Icon name={icon} size={size === 'small' ? 13 : 15} /> : null}
      {children}
    </button>
  )
}

/** 行内文字按钮（原型 .link-btn），用于表格操作列 */
interface LinkButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode
}

export function LinkButton({ children, className, type = 'button', ...rest }: LinkButtonProps) {
  return (
    <button type={type} className={'link-btn' + (className ? ' ' + className : '')} {...rest}>
      {children}
    </button>
  )
}
