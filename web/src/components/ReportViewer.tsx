/**
 * 报告在线查看器：iframe 内嵌渲染后端给出的 view_url（GET /runs/{id}/report/view
 * 或单个 report_html 产物的 view_url）。
 *
 * 硬约束（与报告抽屉同一套纪律）：
 * - URL 一律来自后端 view_url 字段，前端不自己拼路径；
 * - iframe 带 sandbox 属性，与响应头 CSP sandbox 双保险：报告内容可能是
 *   导入通道带进来的任意 HTML，在线展示时脚本一律不执行；
 * - view_url 缺失（运行未完成）时如实说明，不渲染空白框冒充报告。
 */
import { useEffect, useState } from 'react'
import { LinkButton } from './Button'
import { Viewer } from './Dialog'
import { Notice } from './Notice'

export interface ReportViewerProps {
  open: boolean
  /** 后端拼好的在线查看地址；null 表示该运行没有可直接查看的报告 */
  viewUrl: string | null
  title: string
  description?: string
  onClose: () => void
}

export function ReportViewer({ open, viewUrl, title, description, onClose }: ReportViewerProps) {
  // 换 run / 重开时强制 iframe 重建，避免展示上一个运行的内容
  const [frameKey, setFrameKey] = useState(0)
  useEffect(() => {
    if (open) setFrameKey((key) => key + 1)
  }, [open, viewUrl])

  return (
    <Viewer
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      footHint="报告在沙箱中只读渲染：脚本不执行；文件下载请在报告抽屉操作"
      footer={
        <>
          <LinkButton onClick={() => setFrameKey((key) => key + 1)}>重新加载</LinkButton>
          {viewUrl ? (
            <a className="link-btn" href={viewUrl} target="_blank" rel="noreferrer">
              在新窗口打开 <span aria-hidden="true">›</span>
            </a>
          ) : null}
        </>
      }
    >
      {viewUrl ? (
        <iframe key={frameKey} className="report-frame" src={viewUrl} title="测试报告" sandbox="" />
      ) : (
        <div className="viewer-fallback">
          <Notice tone="amber" title="该运行没有在线查看地址">
            只有完成的运行才有报告；请等运行结束后再试，或先在报告抽屉里查看结论摘要。
          </Notice>
        </div>
      )}
    </Viewer>
  )
}
