/**
 * 图标：内联 SVG，路径数据照抄原型 L68 的 icons 表，避免引入图标库。
 */
export type IconName =
  | 'grid'
  | 'layers'
  | 'phone'
  | 'pulse'
  | 'devices'
  | 'tasks'
  | 'report'
  | 'plug'
  | 'plus'
  | 'arrow'
  | 'search'
  | 'play'
  | 'check'
  | 'alert'
  | 'close'
  | 'clock'
  | 'box'
  | 'chevron'
  | 'download'
  | 'code'
  | 'image'
  | 'freeze'
  | 'menu'
  | 'back'
  | 'copy'
  | 'flag'

const PATHS: Record<IconName, string> = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  layers: '<path d="M12 3 3 7.5l9 4.5 9-4.5Z"/><path d="m3 12.5 9 4.5 9-4.5"/><path d="m3 17 9 4.5 9-4.5"/>',
  phone: '<rect x="6.5" y="2.5" width="11" height="19" rx="2.4"/><path d="M10 5.2h4"/><path d="M11 18.6h2"/>',
  pulse: '<path d="M2.5 12h4.2l2.3-5.8L13 18l2.2-6H21.5"/>',
  devices: '<rect x="2.5" y="4" width="13" height="10" rx="1.6"/><path d="M6 17.5h6.4"/><path d="M9.2 14v3.5"/><rect x="16.5" y="9" width="5" height="10" rx="1.4"/>',
  tasks: '<path d="M4 6.2l1.8 1.8L9 4.8"/><path d="M4 12.9l1.8 1.8L9 11.5"/><path d="M4 19.3l1.8 1.8L9 17.9"/><path d="M12 7h8"/><path d="M12 13h8"/><path d="M12 19h8"/>',
  report: '<path d="M6 2.8h8.5L19 7.3V21.2H6Z"/><path d="M14 2.8v5h5"/><path d="M9 12h7"/><path d="M9 16h5"/>',
  plug: '<path d="M9 2.5v5"/><path d="M15 2.5v5"/><path d="M6.5 7.5h11v3a5.5 5.5 0 0 1-11 0Z"/><path d="M12 16v5.5"/>',
  plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
  arrow: '<path d="M4 12h15"/><path d="m13 6 6 6-6 6"/>',
  search: '<circle cx="10.6" cy="10.6" r="6.4"/><path d="m15.4 15.4 5 5"/>',
  play: '<path d="M8 4.6 19 12 8 19.4Z"/>',
  check: '<path d="m4.5 12.5 5 5L19.5 7"/>',
  alert: '<path d="M12 3.5 21 20H3Z"/><path d="M12 9.5v5"/><path d="M12 17.3v.2"/>',
  close: '<path d="m6 6 12 12"/><path d="M18 6 6 18"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.3l3.3 2"/>',
  box: '<path d="m12 2.8 8.4 4.4v9.6L12 21.2 3.6 16.8V7.2Z"/><path d="m3.6 7.2 8.4 4.4 8.4-4.4"/><path d="M12 11.6v9.6"/>',
  chevron: '<path d="m9 5.5 6.5 6.5L9 18.5"/>',
  download: '<path d="M12 3.5v11.6"/><path d="m7.5 10.6 4.5 4.5 4.5-4.5"/><path d="M4.5 20.5h15"/>',
  code: '<path d="m8.5 8.2-4 3.8 4 3.8"/><path d="m15.5 8.2 4 3.8-4 3.8"/><path d="m13.4 4.3-2.8 15.4"/>',
  image: '<rect x="3" y="4.5" width="18" height="15" rx="2"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="m4.5 17 5-4.6 3.4 3 3-2.5 4.6 4.1"/>',
  freeze: '<path d="M12 2.5v19"/><path d="m3.8 7.2 16.4 9.6"/><path d="m20.2 7.2-16.4 9.6"/><path d="M12 6.4 9.6 4.2"/><path d="M12 6.4 14.4 4.2"/>',
  menu: '<path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h16"/>',
  back: '<path d="M20 12H5"/><path d="m11 6-6 6 6 6"/>',
  copy: '<rect x="9" y="9" width="11.5" height="11.5" rx="1.7"/><path d="M15 5.5V4.8A1.3 1.3 0 0 0 13.7 3.5H4.8A1.3 1.3 0 0 0 3.5 4.8v8.9A1.3 1.3 0 0 0 4.8 15h.7"/>',
  flag: '<path d="M5 21V3.6"/><path d="M5 4.2h11.4l-2.2 4.4 2.2 4.4H5"/>',
}

interface IconProps {
  name: IconName
  size?: number
  className?: string
  /** 图标语义标签；省略视为装饰性图标（aria-hidden） */
  title?: string
}

export function Icon({ name, size = 19, className, title }: IconProps) {
  return (
    <svg
      className={'icon' + (className ? ' ' + className : '')}
      viewBox="0 0 24 24"
      style={{ width: size, height: size }}
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
      focusable="false"
    >
      {title ? <title>{title}</title> : null}
      {/* PATHS 是本模块静态常量表，不含任何外部输入 */}
      <g dangerouslySetInnerHTML={{ __html: PATHS[name] }} />
    </svg>
  )
}
