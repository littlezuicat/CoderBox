// 划词翻译的弹窗：后端开的第二个无边框置顶窗口（地址带 ?lit=popup），不抢焦点；后端用 window.__lit(type, data) 推数据进来。
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'

type St = { id: number; text: string; out: string; busy: boolean; err: string; stay: number }

export default function LitPopup() {
  const [theme, setTheme] = useState<string>('light')
  const [sysDark, setSysDark] = useState(window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false)
  const [st, setSt] = useState<St>({ id: 0, text: '', out: '', busy: true, err: '', stay: 10 })
  const [copied, setCopied] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const idRef = useRef(0)
  const hover = useRef(false)
  const timer = useRef<any>(0)
  const dark = theme === 'dark' || (theme === 'system' && sysDark)

  useEffect(() => {
    document.getElementById('splash')?.remove()
    api.lit_popup_info().then((i: any) => setTheme(i.theme || 'light'))
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)'); const f = () => setSysDark(!!mq?.matches); mq?.addEventListener('change', f)
    ;(window as any).__lit = (type: string, d: any) => {
      if (type === 'start') { idRef.current = d.id; clearTimeout(timer.current); setCopied(false); setSt({ id: d.id, text: d.text || '', out: '', busy: true, err: '', stay: d.stay || 0 }); return }
      if (d.id !== idRef.current) return
      if (type === 'delta') setSt((s) => ({ ...s, out: s.out + d.text }))
      else if (type === 'done') { setSt((s) => ({ ...s, busy: false, out: d.full || s.out })); arm() }
      else if (type === 'error') setSt((s) => ({ ...s, busy: false, err: d.message }))
    }
    return () => { mq?.removeEventListener('change', f) }
  }, [])
  useEffect(() => { document.documentElement.style.background = document.body.style.background = dark ? '#282a36' : '#ffffff'; document.body.style.margin = '0'; document.body.style.overflow = 'hidden' }, [dark])
  // 内容变高/变矮，让后端跟着改窗口高度
  useEffect(() => {
    const el = root.current; if (!el) return
    const ro = new ResizeObserver(() => api.lit_popup_resize(el.offsetHeight))
    ro.observe(el); return () => ro.disconnect()
  }, [])
  const stayRef = useRef(10); stayRef.current = st.stay
  const arm = () => {                       // 译完停一会儿自动收起；鼠标在窗口上就不收，移开后重新计时
    clearTimeout(timer.current)
    if (!stayRef.current) return
    timer.current = setTimeout(() => { if (hover.current) arm(); else api.lit_popup_hide() }, stayRef.current * 1000)
  }
  const copy = async () => { await api.lit_copy(st.out); setCopied(true); setTimeout(() => setCopied(false), 1200) }

  const fg = dark ? '#e8eaf2' : '#1f2430', sub = dark ? '#9aa0b4' : '#6b7280', line = dark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.1)'
  const btn: React.CSSProperties = { border: 'none', background: 'transparent', color: sub, cursor: 'pointer', fontSize: 12, padding: '2px 6px', borderRadius: 6 }
  return (
    <div ref={root} onMouseEnter={() => { hover.current = true }} onMouseLeave={() => { hover.current = false }}
      style={{ boxSizing: 'border-box', width: '100%', padding: '10px 14px 12px', color: fg, background: dark ? '#282a36' : '#ffffff', fontFamily: '-apple-system, BlinkMacSystemFont, "Microsoft YaHei UI", "Microsoft YaHei", sans-serif', borderRadius: 12, border: `1px solid ${line}`, userSelect: 'text' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <span style={{ fontSize: 12, color: sub, flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{st.busy ? '正在翻译…' : '译文'}{st.text.trim() ? '　' + st.text.trim().replace(/\s+/g, ' ').slice(0, 60) : ''}</span>
        <button style={btn} disabled={!st.out} onClick={copy}>{copied ? '已复制' : '复制'}</button>
        <button style={{ ...btn, fontSize: 15, lineHeight: 1 }} aria-label="关闭" onClick={() => api.lit_popup_hide()}>×</button>
      </div>
      {st.err
        ? <div style={{ fontSize: 13, color: '#e5484d', lineHeight: 1.6 }}>{st.err}</div>
        : <div style={{ fontSize: 14.5, lineHeight: 1.75, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 440, overflowY: 'auto', minHeight: 22 }}>{st.out}{st.busy && !st.out && <span style={{ color: sub }}> </span>}</div>}
    </div>
  )
}
