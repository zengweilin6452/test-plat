/**
 * 轻提示（原型 toast()，L117）。
 *
 * 提供 ToastProvider + useToast()：页面调用 toast.show('...') 即可。
 *
 * 为什么渲染成非模态原生 <dialog>：showModal 打开的对话框处于浏览器 top layer，
 * 普通 fixed 元素再高的 z-index 也盖不过去（抽屉里保存绑定/发起运行的提示会被整块遮挡）；
 * 手动 popover 通过 showPopover() 进入 top layer，不阻断页面交互。
 *
 * 支持 tone（info/success/error）与多槽位：连续操作（先失败后成功）不再互相覆盖，
 * 最新一条在最下方，各自计时 2.6s 后消失。
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

export type ToastTone = 'info' | 'success' | 'error'

interface ToastItem {
  id: number
  message: string
  tone: ToastTone
}

interface ToastApi {
  show: (message: string, tone?: ToastTone) => void
}

const TOAST_DURATION = 2600
const MAX_SLOTS = 3

const ToastContext = createContext<ToastApi | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const nextId = useRef(0)
  const timers = useRef(new Map<number, number>())

  const dismiss = useCallback((id: number) => {
    window.clearTimeout(timers.current.get(id))
    timers.current.delete(id)
    setItems((current) => current.filter((item) => item.id !== id))
  }, [])

  const show = useCallback(
    (message: string, tone: ToastTone = 'info') => {
      const id = nextId.current++
      setItems((current) => {
        // 超出槽位时淘汰最旧的一条，避免弹层堆积
        const trimmed = [...current, { id, message, tone }].slice(-MAX_SLOTS)
        for (const item of current.slice(0, Math.max(0, current.length - MAX_SLOTS + 1))) {
          window.clearTimeout(timers.current.get(item.id))
          timers.current.delete(item.id)
        }
        return trimmed
      })
      timers.current.set(id, window.setTimeout(() => dismiss(id), TOAST_DURATION))
    },
    [dismiss],
  )

  useEffect(() => {
    const pending = timers.current
    return () => {
      for (const id of pending.values()) window.clearTimeout(id)
      pending.clear()
    }
  }, [])

  const api = useMemo<ToastApi>(() => ({ show }), [show])

  return (
    <ToastContext.Provider value={api}>
      {children}
      {items.map((item, index) => (
        // 手动 popover 进入 top layer，盖过当前模态弹层。
        <dialog
          key={item.id}
          ref={(el) => {
            if (el) {
              el.popover = 'manual'
              if (!el.matches(':popover-open')) el.showPopover()
            }
          }}
          className={'toast ' + item.tone}
          style={{ bottom: 28 + (items.length - 1 - index) * 52 }}
          role="status"
          aria-live="polite"
        >
          {item.message}
        </dialog>
      ))}
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext)
  if (!context) {
    // 便于单独使用组件时降级，不抛错打断渲染
    return { show: () => undefined }
  }
  return context
}
