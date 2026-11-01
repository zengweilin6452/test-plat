/**
 * 浏览器直解 vendor H.264 预览（Phase 2）。
 *
 * 线格式与 vendor viewer/videostream.py 对齐：27 字节网络字节序包头 + 载荷；
 * kind 1=config(Annex B SPS/PPS)、2=session(空载荷，尺寸在包头)、3=frame。
 * 纯解析函数可单测；播放器用 WebCodecs VideoDecoder 画到现有 canvas。
 * WebCodecs 缺失、vendor 报错、8s 无画面或解码异常时如实回调 onError，
 * 由调用方回退 JPEG（本模块不自行重连）。
 */

export const HEADER_BYTES = 27
export const PROTOCOL_VERSION = 1
export const MAX_PAYLOAD = 2 * 1024 * 1024
export const BACKPRESSURE_QUEUE = 8

export const KIND = { CONFIG: 1, SESSION: 2, FRAME: 3 } as const

export interface RelayHeader {
  version: number
  kind: number
  generation: number
  sequence: number
  ptsUs: bigint
  key: boolean
  width: number
  height: number
  payloadLength: number
}

export function parseRelayHeader(buffer: ArrayBuffer): RelayHeader {
  if (buffer.byteLength < HEADER_BYTES) throw new Error('包头不完整')
  const view = new DataView(buffer)
  const version = view.getUint8(0)
  if (version !== PROTOCOL_VERSION) throw new Error(`协议版本不符:${version}`)
  const kind = view.getUint8(1)
  if (kind !== KIND.CONFIG && kind !== KIND.SESSION && kind !== KIND.FRAME) {
    throw new Error(`未知 kind:${kind}`)
  }
  const header: RelayHeader = {
    version,
    kind,
    generation: view.getUint32(2),
    sequence: view.getUint32(6),
    ptsUs: view.getBigUint64(10),
    key: (view.getUint8(18) & 0x01) !== 0,
    width: view.getUint16(19),
    height: view.getUint16(21),
    payloadLength: view.getUint32(23),
  }
  if (header.payloadLength > MAX_PAYLOAD) throw new Error('载荷超限')
  if (buffer.byteLength < HEADER_BYTES + header.payloadLength) {
    throw new Error('载荷不完整')
  }
  return header
}

export function relayPayload(buffer: ArrayBuffer, header: RelayHeader): Uint8Array {
  return new Uint8Array(buffer, HEADER_BYTES, header.payloadLength)
}

/** Annex B 里 SPS 的三字节 profile/constraint/level → avc1.PPCCLL。 */
export function codecFromAnnexB(payload: Uint8Array): string | null {
  for (let i = 0; i + 6 < payload.length; i++) {
    if (payload[i] === 0 && payload[i + 1] === 0 && payload[i + 2] === 1) {
      if ((payload[i + 3] & 0x1f) === 7) {
        const hex = (value: number) => value.toString(16).padStart(2, '0')
        return `avc1.${hex(payload[i + 4])}${hex(payload[i + 5])}${hex(payload[i + 6])}`
      }
    }
  }
  return null
}

/** 解码积压时丢 delta，关键帧永不丢。 */
export function shouldDropDelta(
  queueSize: number,
  key: boolean,
  limit = BACKPRESSURE_QUEUE,
): boolean {
  return !key && queueSize > limit
}

/** 浏览器能力决定初始传输；不可用时给出可展示的 JPEG 回退原因。 */
export function choosePreviewTransport(hasVideoDecoder: boolean): {
  mode: 'h264' | 'jpeg'
  reason: string | null
} {
  return hasVideoDecoder
    ? { mode: 'h264', reason: null }
    : { mode: 'jpeg', reason: '浏览器不支持 WebCodecs，已回退 JPEG' }
}

export interface H264PreviewOptions {
  canvas: HTMLCanvasElement | null
  wsUrl: string
  /** 冻结快照时暂停绘制；解码继续，恢复后下一帧自动接上。 */
  isPaused: () => boolean
  onState?: (state: 'connecting' | 'open' | 'closed') => void
  onSession?: (size: { w: number; h: number }) => void
  onFrame?: (size: { w: number; h: number }) => void
  onError: (code: string, message: string) => void
}

export interface H264PreviewHandle {
  open: () => void
  close: () => void
  readonly active: boolean
}

const READY_TIMEOUT_MS = 8000

export function createH264Preview(options: H264PreviewOptions): H264PreviewHandle {
  let ws: WebSocket | null = null
  let decoder: VideoDecoder | null = null
  let configured = false
  let pendingConfig: Uint8Array | null = null
  let closed = false
  let failed = false
  let readyTimer: number | null = null

  function clearTimer() {
    if (readyTimer !== null) {
      window.clearTimeout(readyTimer)
      readyTimer = null
    }
  }

  function stop() {
    closed = true
    clearTimer()
    if (ws) {
      const socket = ws
      ws = null
      socket.onopen = null
      socket.onmessage = null
      socket.onerror = null
      socket.onclose = null
      try {
        socket.close(1000)
      } catch {
        // 已关闭
      }
    }
    if (decoder) {
      try {
        decoder.close()
      } catch {
        // 已关闭
      }
      decoder = null
    }
    configured = false
    pendingConfig = null
  }

  function fail(code: string, message: string) {
    if (failed) return
    failed = true
    stop()
    options.onState?.('closed')
    options.onError(code, message)
  }

  function draw(frame: VideoFrame) {
    const paused = options.isPaused()
    const width = frame.displayWidth
    const height = frame.displayHeight
    const canvas = options.canvas
    // 冻结时必须完全不动 canvas：改尺寸本身就会清空已绘制的快照
    if (canvas && !paused) {
      if (canvas.width !== width) canvas.width = width
      if (canvas.height !== height) canvas.height = height
      canvas.getContext('2d')?.drawImage(frame, 0, 0)
    }
    frame.close()
    if (!paused) options.onFrame?.({ w: width, h: height })
  }

  function ensureDecoder(codec: string) {
    if (typeof VideoDecoder === 'undefined') {
      throw new Error('浏览器不支持 WebCodecs')
    }
    if (decoder) return
    decoder = new VideoDecoder({
      output: draw,
      error: (error) => fail('decode_error', `解码器错误:${error.message}`),
    })
    decoder.configure({ codec })
    configured = true
  }

  function handleBinary(buffer: ArrayBuffer) {
    const header = parseRelayHeader(buffer)
    const payload = relayPayload(buffer, header)
    if (header.kind === KIND.SESSION) {
      options.onSession?.({ w: header.width, h: header.height })
      return
    }
    if (header.kind === KIND.CONFIG) {
      pendingConfig = Uint8Array.from(payload)
      return
    }
    if (shouldDropDelta(decoder?.decodeQueueSize ?? 0, header.key)) return
    if (!header.key && !configured) return

    let data: Uint8Array = payload
    if (header.key) {
      ensureDecoder(codecFromAnnexB(payload) ?? 'avc1.42E01E')
      if (pendingConfig) {
        const merged = new Uint8Array(pendingConfig.length + payload.length)
        merged.set(pendingConfig, 0)
        merged.set(payload, pendingConfig.length)
        data = merged
        pendingConfig = null
      }
    }
    clearTimer()
    decoder!.decode(
      new EncodedVideoChunk({
        type: header.key ? 'key' : 'delta',
        timestamp: Number(header.ptsUs),
        data,
      }),
    )
  }

  function open() {
    if (ws) return
    closed = false
    failed = false
    options.onState?.('connecting')
    if (!options.canvas) {
      fail('canvas_missing', '预览画布未就绪')
      return
    }
    const socket = new WebSocket(options.wsUrl)
    socket.binaryType = 'arraybuffer'
    ws = socket
    readyTimer = window.setTimeout(() => {
      fail('timeout', 'H.264 视频 8s 内未收到画面')
    }, READY_TIMEOUT_MS)
    socket.onopen = () => {
      try {
        socket.send(JSON.stringify({ proto: 1 }))
      } catch {
        fail('send_failed', 'H.264 握手发送失败')
      }
    }
    socket.onmessage = (event) => {
      if (typeof event.data === 'string') {
        let message: { kind?: string; code?: string; message?: string } | null = null
        try {
          message = JSON.parse(event.data)
        } catch {
          return
        }
        if (message?.kind === 'ready') options.onState?.('open')
        else if (message?.kind === 'error') {
          fail(message.code ?? 'viewer_error', message.message ?? '视频信道错误')
        }
        return
      }
      try {
        handleBinary(event.data as ArrayBuffer)
      } catch (error) {
        fail('stream_error', `码流处理失败:${(error as Error).message}`)
      }
    }
    socket.onerror = () => {
      // close 一定会跟随；回退决策放在 onclose/fail。
    }
    socket.onclose = () => {
      if (closed) return
      fail('closed', 'H.264 视频信道关闭')
    }
  }

  return {
    open,
    close() {
      failed = true
      stop()
    },
    get active() {
      return ws !== null
    },
  }
}
