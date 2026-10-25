/**
 * 后端 API 客户端。
 *
 * 约定（docs/plan/api-design.md）：
 * - base path /api/v1，Vite dev 已把 /api 代理到 127.0.0.1:8000。
 * - 所有错误返回统一信封 { code, message, request_id }，本模块把它转成 ApiError 抛出，
 *   调用方拿到的永远是结构化错误，不需要再判断 HTTP 状态码。
 * - 不吞异常、不返回假数据：网络失败原样抛出，UI 用 Empty / Notice 展示，
 *   绝不用种子数据兜底（frontend-spec.md §8 第 4 条）。
 */

import type { ApiErrorEnvelope } from '../types'

export const API_BASE = '/api/v1'

export class ApiError extends Error {
  /** 后端错误码，如 TASK_NOT_FOUND / GATE_NOT_EVALUATED */
  readonly code: string
  /** 请求 ID，报障时用于对齐后端日志 */
  readonly requestId: string | null
  readonly status: number
  /**
   * 错误信封里的 details 原样保留（api-design.md §1.2）。
   * 例如 422 readiness_incomplete 的缺失项清单就在 details 里；
   * 前端只展示后端给的内容，不自行推导缺失项。
   */
  readonly details: unknown

  constructor(
    code: string,
    message: string,
    status: number,
    requestId: string | null = null,
    details: unknown = null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.requestId = requestId
    this.details = details
  }
}

/** 写操作统一携带的客户端标识（api-design.md §1.1：浏览器写操作要求带 X-TestDock-Client） */
export const CLIENT_HEADER = 'X-TestDock-Client'
export const CLIENT_ID = 'web'

/** 网络层失败（后端未启动、DNS、离线）——与后端业务错误区分展示 */
export class NetworkError extends Error {
  constructor(message: string, readonly cause?: unknown) {
    super(message)
    this.name = 'NetworkError'
  }
}

function isEnvelope(value: unknown): value is ApiErrorEnvelope {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as ApiErrorEnvelope).code === 'string' &&
    typeof (value as ApiErrorEnvelope).message === 'string'
  )
}

/** 把任意错误转成可读文案 + 错误码，供 Notice 展示 */
export function describeError(error: unknown): {
  code: string
  message: string
  requestId: string | null
  details: unknown
} {
  if (error instanceof ApiError) {
    return { code: error.code, message: error.message, requestId: error.requestId, details: error.details }
  }
  if (error instanceof NetworkError) {
    return { code: 'NETWORK_ERROR', message: error.message, requestId: null, details: null }
  }
  if (error instanceof Error) {
    return { code: 'UNKNOWN_ERROR', message: error.message, requestId: null, details: null }
  }
  return { code: 'UNKNOWN_ERROR', message: String(error), requestId: null, details: null }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  /** query 参数，undefined / null / '' 会被跳过 */
  query?: Record<string, string | number | boolean | null | undefined>
  /** JSON 请求体，自动序列化并带 Content-Type */
  body?: unknown
  signal?: AbortSignal
  headers?: Record<string, string>
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(API_BASE + path, window.location.origin)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === '') continue
      url.searchParams.set(key, String(value))
    }
  }
  return url.pathname + url.search
}

/**
 * 发起一次请求并解析 JSON。
 * 统一进入点：所有页面都通过这里取数据，禁止在页面里直接 fetch。
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', query, body, signal, headers } = options
  // 写操作必须带 X-TestDock-Client: web（api-design.md §1.1）；GET 也带上，后端可据此区分来源。
  const init: RequestInit = {
    method,
    signal,
    headers: { Accept: 'application/json', [CLIENT_HEADER]: CLIENT_ID, ...headers },
  }

  if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { ...init.headers, 'Content-Type': 'application/json' }
  }

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), init)
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw new NetworkError('无法连接后端服务，请确认 API 已启动', cause)
  }

  // 204 无响应体
  if (response.status === 204) return undefined as T

  const text = await response.text()
  let parsed: unknown = null
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = null
    }
  }

  if (!response.ok) {
    if (isEnvelope(parsed)) {
      throw new ApiError(
        parsed.code,
        parsed.message,
        response.status,
        parsed.request_id ?? null,
        (parsed as { details?: unknown }).details ?? null,
      )
    }
    throw new ApiError(
      'HTTP_' + response.status,
      text ? text.slice(0, 200) : '服务返回了无法解析的错误响应',
      response.status,
    )
  }

  return parsed as T
}

export const api = {
  get: <T>(path: string, query?: RequestOptions['query'], signal?: AbortSignal) =>
    request<T>(path, { query, signal }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
