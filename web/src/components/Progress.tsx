/**
 * 进度条（原型 .progress）。
 *
 * progress 来自后端 run_events 的进度事件；为 undefined / null 时不渲染，
 * 不做前端假进度（frontend-spec.md §8 第 4 条）。
 */
export function Progress({ value, label }: { value: number | null | undefined; label?: string }) {
  if (value === null || value === undefined) return null
  const clamped = Math.max(0, Math.min(100, value))
  return (
    <div className="progress" role="progressbar" aria-valuenow={clamped} aria-valuemin={0} aria-valuemax={100} aria-label={label ?? '执行进度'}>
      <span style={{ width: clamped + '%' }} />
    </div>
  )
}
