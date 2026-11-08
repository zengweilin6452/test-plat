/**
 * 弹窗 / 抽屉（原型用原生 <dialog> + showModal，见 L15、L25 的 dialog 样式）。
 *
 * 为什么仍然用 <dialog>：它自带焦点圈闭、Esc 关闭、backdrop 层级，比手写遮罩更可靠；
 * 页面只需要给 open / onClose。
 */
import { useEffect, useRef, type ReactNode } from 'react'
import { Button } from './Button'

interface DialogProps {
  open: boolean
  onClose: () => void
  title: ReactNode
  /** 标题下的补充说明 */
  description?: ReactNode
  /** 底部按钮区；不传则不渲染 footer */
  footer?: ReactNode
  /** 底部左侧灰色提示 */
  footHint?: ReactNode
  children?: ReactNode
  /** 右侧滑出的抽屉样式 / 宽幅查看器（内嵌 iframe 渲染报告） */
  variant?: 'dialog' | 'drawer' | 'viewer'
  /** 关闭按钮的无障碍标签 */
  closeLabel?: string
}

export function Dialog({
  open,
  onClose,
  title,
  description,
  footer,
  footHint,
  children,
  variant = 'dialog',
  closeLabel = '关闭',
}: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) el.showModal()
    if (!open && el.open) el.close()
  }, [open])

  // Esc 与浏览器关闭都回到 React 状态。
  // Esc 先触发 cancel：preventDefault 拦下原生关闭，交给 onClose 决定，
  // 避免「DOM 已关、React open 仍为 true」的失真（提交中按 Esc 后向导会打不开）。
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const handleCancel = (event: Event) => {
      event.preventDefault()
      onClose()
    }
    const handleClose = () => onClose()
    el.addEventListener('cancel', handleCancel)
    el.addEventListener('close', handleClose)
    return () => {
      el.removeEventListener('cancel', handleCancel)
      el.removeEventListener('close', handleClose)
    }
  }, [onClose])

  // 点击 backdrop 关闭
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const handleClick = (event: MouseEvent) => {
      if (event.target === el) onClose()
    }
    el.addEventListener('click', handleClick)
    return () => el.removeEventListener('click', handleClick)
  }, [onClose])

  return (
    <dialog ref={ref} className={variant === 'dialog' ? undefined : variant} aria-label={typeof title === 'string' ? title : closeLabel}>
      <div className="dialog-head">
        <div>
          <h2>{title}</h2>
          {description ? <p>{description}</p> : null}
        </div>
        <Button iconOnly icon="close" aria-label={closeLabel} onClick={onClose} />
      </div>
      <div className="dialog-body">{children}</div>
      {footer || footHint ? (
        <div className="dialog-foot">
          {footHint ? <span className="foot-hint">{footHint}</span> : null}
          {footer}
        </div>
      ) : null}
    </dialog>
  )
}

/** 抽屉：Dialog 的右滑变体，语义化包装 */
type DrawerProps = Omit<DialogProps, 'variant'>

export function Drawer(props: DrawerProps) {
  return <Dialog {...props} variant="drawer" />
}

/** 宽幅查看器：Dialog 的 viewer 变体（body 不再限高，交给 iframe 填满） */
type ViewerProps = Omit<DialogProps, 'variant'>

export function Viewer(props: ViewerProps) {
  return <Dialog {...props} variant="viewer" />
}

/** 关闭图标按钮，供页面自定义头部时复用 */
export function CloseIcon({ onClick }: { onClick: () => void }) {
  return <Button iconOnly icon="close" aria-label="关闭" onClick={onClick} />
}
