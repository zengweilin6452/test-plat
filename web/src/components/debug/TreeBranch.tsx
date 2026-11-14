/**
 * 层级树递归渲染（自 DebugDrawer.tsx 迁入，P2-03 分层）。
 * 行样式照原型 .tree-row：当前选中节点高亮，整行可点（真实场景允许选任意节点）。
 */
import { useState } from 'react'
import type { SnapshotTreeNode } from '../../api/types'
import { hasNodeIdentity, nodeBounds, nodeLabel } from './debugModel'

/** 递归渲染层级树（children 存下标，超过 200 层视为脏数据直接停）。
 *  行样式照原型 .tree-row：当前选中节点高亮，整行可点（真实场景允许选任意节点）。 */
export function TreeBranch({
  node,
  depth,
  byIndex,
  onPick,
  selectedIndex,
  frozen,
}: {
  node: SnapshotTreeNode
  depth: number
  byIndex: Map<number, SnapshotTreeNode>
  onPick: (node: SnapshotTreeNode) => void
  selectedIndex: number | null
  frozen: boolean
}) {
  const [open, setOpen] = useState(depth < 2)
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
            selectedIndex={selectedIndex}
            frozen={frozen}
          />
        ))}
      </>
    )
  }
  const bounds = nodeBounds(node)
  const selected = frozen && selectedIndex === node.index
  return (
    <div>
      <div
        className={'tree-row' + (selected ? ' selected' : '')}
        style={{ paddingLeft: 8 + depth * 16 }}
        role="treeitem"
        aria-selected={selected}
        tabIndex={0}
        onClick={() => onPick(node)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            onPick(node)
          }
        }}
      >
        {kids.length > 0 && depth < 200 ? (
          <button
            type="button"
            className="link-btn"
            style={{ minWidth: 14 }}
            aria-label={open ? '收起' : '展开'}
            onClick={(event) => {
              event.stopPropagation()
              setOpen(!open)
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
          <span className="muted" style={{ marginLeft: 'auto', fontSize: 9 }}>{bounds}</span>
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
              selectedIndex={selectedIndex}
              frozen={frozen}
            />
          ))
        : null}
    </div>
  )
}
