/**
 * 表格（原型 .task-table）。
 *
 * 通用列定义：column.render 返回 ReactNode；空数据处理交给 Empty，
 * 组件本身不编造行数据。
 */
import type { ReactNode } from 'react'
import { Empty } from './Empty'

export interface Column<T> {
  key: string
  header: ReactNode
  /** 单元格渲染 */
  render: (row: T, index: number) => ReactNode
  /** 列宽（如 '120px' / '18%'） */
  width?: string
  align?: 'left' | 'right' | 'center'
  /** 是否允许换行（默认 nowrap） */
  wrap?: boolean
}

interface TableProps<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T, index: number) => string
  /** 无数据时的空态 */
  empty?: ReactNode
  /** 表格底部说明（如"共 N 条"） */
  footer?: ReactNode
  /** 行点击 */
  onRowClick?: (row: T) => void
  ariaLabel?: string
}

export function Table<T>({
  columns,
  rows,
  rowKey,
  empty,
  footer,
  onRowClick,
  ariaLabel,
}: TableProps<T>) {
  if (rows.length === 0) {
    return (
      <>
        {empty ?? <Empty title="暂无数据" description="当前筛选条件下没有记录" />}
        {footer ? <div className="table-footer">{footer}</div> : null}
      </>
    )
  }

  return (
    <>
      <div className="table-wrap">
        <table className="task-table" aria-label={ariaLabel}>
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col.key} style={{ width: col.width, textAlign: col.align }}>
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr
                key={rowKey(row, index)}
                onClick={
                  onRowClick
                    ? (event) => {
                        // 行内按钮/链接等交互元素自行处理点击，不冒泡触发行点击，
                        // 否则一次点击会同时打开行详情与按钮目标（两层抽屉叠在一起，
                        // 用户要点多次关闭按钮才能全部关掉）
                        const target = event.target as HTMLElement | null
                        if (target && target.closest('button, a, input, select, textarea, label, [role="button"]')) return
                        onRowClick(row)
                      }
                    : undefined
                }
                style={onRowClick ? { cursor: 'pointer' } : undefined}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    style={{
                      textAlign: col.align,
                      whiteSpace: col.wrap ? 'normal' : undefined,
                      verticalAlign: col.wrap ? 'top' : undefined,
                    }}
                  >
                    {col.render(row, index)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {footer ? <div className="table-footer">{footer}</div> : null}
    </>
  )
}
