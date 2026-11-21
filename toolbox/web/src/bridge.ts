// 前端 ↔ Python 的桥。真运行时用 pywebview 注入的 window.pywebview.api；在浏览器里（开发、截图）自动换成模拟实现。
type Handler = (d: any) => void
const handlers = new Map<string, Set<Handler>>()

export function on(type: string, h: Handler) {
  if (!handlers.has(type)) handlers.set(type, new Set())
  handlers.get(type)!.add(h)
  return () => { handlers.get(type)?.delete(h) }
}
export function emitLocal(type: string, data?: any) { handlers.get(type)?.forEach((h) => h(data)) }
;(window as any).__emit = emitLocal

const realReady = new Promise<void>((resolve) => {
  if ((window as any).pywebview?.api) resolve()
  else window.addEventListener('pywebviewready', () => resolve())
  setTimeout(() => { if (!(window as any).pywebview) resolve() }, 1500)    // 不在 pywebview 里：1.5 秒后走模拟
})

export const isReal = () => !!(window as any).pywebview?.api

import { mock } from './mock'

export const api: any = new Proxy({}, {
  get: (_t, name: string) => async (...args: any[]) => {
    await realReady
    const real = (window as any).pywebview?.api
    if (real) return real[name](...args)
    return (mock as any)[name]?.(...args)
  },
})
