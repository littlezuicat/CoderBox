import { useEffect, useRef, useState } from 'react'
import { api, on } from './bridge'

/** 订阅后端推送的事件；handler 总是用最新的，不用关心依赖。 */
export function useEvent(type: string, handler: (d: any) => void) {
  const ref = useRef(handler)
  ref.current = handler
  useEffect(() => on(type, (d) => ref.current(d)), [type])
}

export const human = (n: number) => {
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0, x = n
  while (x >= 1024 && i < u.length - 1) { x /= 1024; i++ }
  return i === 0 ? `${Math.round(x)} B` : `${x.toFixed(1)} ${u[i]}`
}

let store: Record<string, any> = {}
export const initSettings = (s: Record<string, any>) => { store = s || {} }
export const getSetting = (k: string, d: any) => (k in store ? store[k] : d)

/** 会写回后端设置文件的 state。 */
export function useSetting<T>(key: string, def: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(getSetting(key, def))
  return [v, (x: T) => { setV(x); store[key] = x; api.settings_set(key, x) }]
}

/** 直接写一项设置（不用 state）。 */
export const putSetting = (k: string, v: any) => { store[k] = v; api.settings_set(k, v) }
