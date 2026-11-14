/**
 * 层级树递归渲染（自 DebugDrawer.tsx 迁入，P2-03 分层）。
 * 行样式照原型 .tree-row：当前选中节点高亮，整行可点（真实场景允许选任意节点）。
 *
 * 展开状态与键盘焦点由 DebugDrawer 集中持有（受控组件）：
 * 方向键/Enter 的导航语义在 debugModel.treeNavAction（纯函数，可单测），
 * 这里只负责渲染行、aria 属性（treeitem / aria-expanded / aria-level）与
 * roving tabindex（焦点行 tabIndex=0，其余 -1）。
 */
import type { KeyboardEvent } from 'react'
import type { SnapshotTreeNode } from '../../api/types'
import { hasNodeIdentity, nodeBounds, nodeLabel } from './debugModel'

export function TreeBranch({
  node,
  depth,
  byIndex,
  onPick,
  onKeyDown,
  selectedIndex,
  focusIndex,
  onFocusRow,
  openSet,
  onToggle,
}: {
  node: SnapshotTreeNode
  depth: number
  byIndex: Map<number, SnapshotTreeNode>
  onPick: (node: SnapshotTreeNode) => void
  /** 方向键/Enter 交给父级统一处理（需要全树可见行列表） */
  onKeyDown: (event: KeyboardEvent<HTMLDivElement>, node: SnapshotTreeNode) => void
  /** 当前选中节点（树行高亮 + aria-selected） */
  selectedIndex: number | null
  /** roving tabindex 当前焦点行 */
  focusIndex: number | null
  onFocusRow: (index: number) => void
  /** 受控展开集合（缺 index = 收起） */
  openSet: Set<number>
  onToggle: (index: number) => void
}) {
  const kids = (node.children ?? [])
    .map((index) => byIndex.get(index))
    .filter((kid): kid is SnapshotTreeNode => Boolean(kid))
  if (!hasNodeIdentity(node)) {
    return (
      <>
        {kids.map((kid) => (
          <TreeBranch
            key={kid.index}
            node={kid}
            depth={depth}
            byIndex={byIndex}
            onPick={onPick}
            onKeyDown={onKeyDown}
            selectedIndex={selectedIndex}
            focusIndex={focusIndex}
            onFocusRow={onFocusRow}
            openSet={openSet}
            onToggle={onToggle}
          />
        ))}
      </>
    )
  }
  const bounds = nodeBounds(node)
  const selected = selectedIndex === node.index
  const open = openSet.has(node.index)
  const expandable = kids.length > 0 && depth < 200
  // 无标识纯容器的子树原位上移，深度不增；层级信息照实输出给读屏
  return (
    <div>
      <div
        className={'tree-row' + (selected ? ' selected' : '')}
        style={{ paddingLeft: 8 + depth * 16 }}
        role="treeitem"
        aria-selected={selected}
        aria-level={depth + 1}
        aria-expanded={expandable ? open : undefined}
        tabIndex={focusIndex === node.index ? 0 : -1}
        data-tree-index={node.index}
        onFocus={() => onFocusRow(node.index)}
        onClick={() => onPick(node)}
        onKeyDown={(event) => onKeyDown(event, node)}
      >
        {expandable ? (
          <button
            type="button"
            className="link-btn"
            style={{ minWidth: 14 }}
            aria-label={open ? '收起' : '展开'}
            onClick={(event) => {
              event.stopPropagation()
              onToggle(node.index)
            }}
          >
            {open ? '▾' : '▸'}
          </button>
        ) : (
          <span style={{ minWidth: 14 }} />
        )}
        <span className="mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }} title={nodeLabel(node)}>
          {nodeLabel(node)}
        </span>
        {bounds ? (
          <span className="muted" style={{ marginLeft: 'auto' }}>{bounds}</span>
        ) : null}
      </div>
      {open && depth < 200
        ? kids.map((kid) => (
            <TreeBranch
              key={kid.index}
              node={kid}
              depth={depth + 1}
              byIndex={byIndex}
              onPick={onPick}
              onKeyDown={onKeyDown}
              selectedIndex={selectedIndex}
              focusIndex={focusIndex}
              onFocusRow={onFocusRow}
              openSet={openSet}
              onToggle={onToggle}
            />
          ))
        : null}
    </div>
  )
}
