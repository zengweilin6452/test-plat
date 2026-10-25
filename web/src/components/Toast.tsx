/**
 * 轻提示（原型 toast()，L117）。
 *
 * 提供 ToastProvider + useToast()：页面调用 toast.show('...') 即可，
 * 组件自己负责 2.6s 后自动隐藏，并且用 key 重置计时。
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

interface ToastApi {
  show: (message: string) => void
}

const ToastContext = createContext<ToastApi | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<string | null>(null)
  const timer = useRef<number | undefined>(undefined)

  const show = useCallback((next: string) => {
    setMessage(next)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setMessage(null), 2600)
  }, [])

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const api = useMemo<ToastApi>(() => ({ show }), [show])

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className={'toast' + (message ? ' show' : '')} role="status" aria-live="polite">
        {message}
      </div>
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
