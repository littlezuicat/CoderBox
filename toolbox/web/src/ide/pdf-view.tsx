// PDF 查看：pdf.js 官方的 PDFViewer（文字可选、可搜索、链接可点）+ 自己的工具栏和缩略图。
// 不用 WebView2 自带的 PDF 查看器（嵌在界面里不好看），也不用老版本的整页 viewer（老版 pdf.js 有已知的字体漏洞，PDF 来自服务器，不能冒这个险）。
import KeyboardArrowDownRounded from '@mui/icons-material/KeyboardArrowDownRounded'
import KeyboardArrowUpRounded from '@mui/icons-material/KeyboardArrowUpRounded'
import SearchRounded from '@mui/icons-material/SearchRounded'
import ViewSidebarRounded from '@mui/icons-material/ViewSidebarRounded'
import ZoomInRounded from '@mui/icons-material/ZoomInRounded'
import ZoomOutRounded from '@mui/icons-material/ZoomOutRounded'
import { Box, IconButton, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { useCtrlWheel } from './preview'

let pdfjsP: Promise<any> | null = null
export const pdfjs = () => (pdfjsP ??= (async () => {
  const lib = await import('pdfjs-dist')
  const W = (await import('pdfjs-dist/build/pdf.worker.min.mjs?worker')).default      // 用 ?worker 让 vite 打成 .js（本地小服务器对 .mjs 的类型不一定对）
  lib.GlobalWorkerOptions.workerPort = new W()
  ;(globalThis as any).pdfjsLib = lib                                                   // pdf_viewer 组件要从全局取 pdfjsLib
  const v = await import('pdfjs-dist/web/pdf_viewer.mjs')
  await import('pdfjs-dist/web/pdf_viewer.css')
  return { lib, v }
})())

const sizeText = (n: number) => (n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB')

function Thumb({ doc, n, active, onClick, root }: { doc: any; n: number; active: boolean; onClick: () => void; root: React.RefObject<HTMLDivElement | null> }) {
  const holder = useRef<HTMLDivElement>(null)
  const [on, setOn] = useState(false)
  const [h, setH] = useState(160)
  const W = 112
  useEffect(() => {
    const io = new IntersectionObserver(([e]) => setOn(e.isIntersecting), { root: root.current, rootMargin: '600px 0px' })
    io.observe(holder.current!)
    return () => io.disconnect()
  }, [])
  useEffect(() => {
    if (!on) { const c = holder.current?.querySelector('canvas'); if (c) { c.width = 0; c.height = 0 } return }       // 滚远了释放画布
    let task: any, dead = false
    ;(async () => {
      const page = await doc.getPage(n)
      if (dead) return
      const v1 = page.getViewport({ scale: 1 }), dpr = window.devicePixelRatio || 1
      const vp = page.getViewport({ scale: (W / v1.width) * dpr })
      setH(W * (v1.height / v1.width))
      let c = holder.current!.querySelector('canvas') as HTMLCanvasElement
      if (!c) { c = document.createElement('canvas'); holder.current!.appendChild(c) }
      c.width = Math.floor(vp.width); c.height = Math.floor(vp.height)
      c.style.cssText = `width:${W}px;height:${W * (v1.height / v1.width)}px;display:block`
      task = page.render({ canvas: c, viewport: vp })
      try { await task.promise } catch { /* 被取消 */ }
    })()
    return () => { dead = true; try { task?.cancel() } catch { /* 无事 */ } }
  }, [on, doc])
  return (
    <Box onClick={onClick} sx={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0.4, py: 0.8 }}>
      <div ref={holder} style={{ width: W, height: h, background: '#fff', outline: active ? '3px solid #3b82f6' : '1px solid rgba(128,128,128,.4)' }} />
      <Typography sx={{ fontSize: 11.5, color: active ? 'primary.main' : 'text.secondary' }}>{n}</Typography>
    </Box>
  )
}

const ZOOMS = ['page-width', 'page-fit', '0.5', '0.75', '1', '1.25', '1.5', '2', '3', '4']
const zoomLabel = (z: string) => (z === 'page-width' ? '适应宽度' : z === 'page-fit' ? '适应页面' : Math.round(parseFloat(z) * 100) + '%')

const Btn = ({ tip, onClick, children, on, disabled }: { tip: string; onClick: () => void; children: React.ReactNode; on?: boolean; disabled?: boolean }) => (
  <IconButton size="small" title={tip} onClick={onClick} disabled={disabled} sx={{ borderRadius: 1, bgcolor: on ? 'action.selected' : 'transparent' }}>{children}</IconButton>
)
const inputSx = { height: 24, fontSize: 13, border: 1, borderColor: 'divider', borderRadius: 0.8, bgcolor: 'background.default', color: 'text.primary', outline: 'none', '&:focus': { borderColor: 'primary.main' } }

export default function PdfView({ pv, dark, onMeta }: { pv: { bytes?: Uint8Array; doc?: any; size: number }; dark: boolean; onMeta: (s: string) => void }) {
  const wrap = useRef<HTMLDivElement>(null)
  const viewerEl = useRef<HTMLDivElement>(null)
  const thumbs = useRef<HTMLDivElement>(null)
  const app = useRef<{ viewer: any; bus: any } | null>(null)
  const [doc, setDoc] = useState<any>(null)
  const [err, setErr] = useState('')
  const [page, setPage] = useState(1)
  const [pageText, setPageText] = useState('1')
  const [zoom, setZoom] = useState('page-width')
  const [pct, setPct] = useState(100)
  const [side, setSide] = useState(false)
  const [q, setQ] = useState('')
  const [found, setFound] = useState('')

  useEffect(() => {
    let dead = false
    ;(async () => {
      try {
        const { lib, v } = await pdfjs()
        let d = pv.doc
        if (!d) {
          d = await lib.getDocument({ data: pv.bytes!.slice(), cMapUrl: import.meta.env.BASE_URL + 'pdfjs/cmaps/', cMapPacked: true, useWasm: false }).promise
          pv.doc = d
        }
        if (dead) return
        const bus = new v.EventBus()
        const link = new v.PDFLinkService({ eventBus: bus, externalLinkTarget: 2 })
        const find = new v.PDFFindController({ linkService: link, eventBus: bus })
        const viewer = new v.PDFViewer({ container: wrap.current, viewer: viewerEl.current, eventBus: bus, linkService: link, findController: find, textLayerMode: 1 })
        link.setViewer(viewer)
        bus.on('pagesinit', () => { viewer.currentScaleValue = 'page-width' })
        bus.on('pagechanging', (e: any) => { setPage(e.pageNumber); setPageText(String(e.pageNumber)) })
        bus.on('scalechanging', (e: any) => setPct(Math.round(e.scale * 100)))
        const cnt = (c: any) => setFound(c && c.total ? `${c.current}/${c.total}` : '')
        bus.on('updatefindmatchescount', (e: any) => cnt(e.matchesCount))
        bus.on('updatefindcontrolstate', (e: any) => { if (e.matchesCount) cnt(e.matchesCount); if (e.state === 1) setFound('没找到') })      // 1 = 没找到
        viewer.setDocument(d); link.setDocument(d, null)
        app.current = { viewer, bus }
        setDoc(d)
      } catch (e) { if (!dead) setErr('PDF 打不开：' + String((e as any)?.message || e)) }
    })()
    return () => { dead = true; try { app.current?.viewer.cleanup() } catch { /* 无事 */ } app.current = null }
  }, [])
  useEffect(() => { if (doc) onMeta(`${doc.numPages} 页 · ${sizeText(pv.size)}`) }, [doc])

  useCtrlWheel(wrap, (k) => zoomBy(k))
  const setScale = (z: string) => { setZoom(z); if (app.current) app.current.viewer.currentScaleValue = z }
  const zoomBy = (k: number) => {
    const v = app.current?.viewer; if (!v) return
    const s = Math.min(5, Math.max(0.25, v.currentScale * k)); setZoom(String(s)); v.currentScaleValue = String(s)
  }
  const total = doc?.numPages || 0
  const goto = (n: number) => { const v = app.current?.viewer; if (v && doc) v.currentPageNumber = Math.min(total, Math.max(1, n)) }
  const search = (again: boolean, back = false) => {
    if (!app.current) return
    if (!q) { setFound(''); app.current.bus.dispatch('findbarclose', { source: null }); return }
    app.current.bus.dispatch('find', { source: null, type: again ? 'again' : '', query: q, caseSensitive: false, entireWord: false, highlightAll: true, findPrevious: back, matchDiacritics: false })
  }
  return (
    <Box sx={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', bgcolor: dark ? '#1e1f29' : '#e4e4e8' }}>
      <Box sx={{ flex: '0 0 38px', display: 'flex', alignItems: 'center', gap: 0.6, px: 1, bgcolor: 'background.paper', borderBottom: 1, borderColor: 'divider', overflow: 'hidden' }}>
        <Btn tip="缩略图" on={side} onClick={() => setSide((s) => !s)}><ViewSidebarRounded fontSize="small" /></Btn>
        <Box sx={{ width: '1px', flex: '0 0 1px', height: 18, bgcolor: 'divider', mx: 0.4 }} />
        <Btn tip="上一页" onClick={() => goto(page - 1)} disabled={page <= 1}><KeyboardArrowUpRounded fontSize="small" /></Btn>
        <Btn tip="下一页" onClick={() => goto(page + 1)} disabled={page >= total}><KeyboardArrowDownRounded fontSize="small" /></Btn>
        <Box component="input" value={pageText} onChange={(e: any) => setPageText(e.target.value.replace(/\D/g, ''))}
          onKeyDown={(e: any) => { if (e.key === 'Enter') { const n = parseInt(pageText); if (n) goto(n); else setPageText(String(page)) } }}
          onBlur={() => setPageText(String(page))} sx={{ ...inputSx, width: 40, textAlign: 'center' }} />
        <Typography sx={{ fontSize: 13, color: 'text.secondary', whiteSpace: 'nowrap' }}>/ {total}</Typography>
        <Box sx={{ width: '1px', flex: '0 0 1px', height: 18, bgcolor: 'divider', mx: 0.4 }} />
        <Btn tip="缩小" onClick={() => zoomBy(1 / 1.2)}><ZoomOutRounded fontSize="small" /></Btn>
        <Box component="select" value={ZOOMS.includes(zoom) ? zoom : 'custom'} onChange={(e: any) => setScale(e.target.value)} sx={{ ...inputSx, height: 26, px: 0.4 }}>
          {!ZOOMS.includes(zoom) && <option value="custom">{pct}%</option>}
          {ZOOMS.map((z) => <option key={z} value={z}>{zoomLabel(z)}</option>)}
        </Box>
        <Btn tip="放大" onClick={() => zoomBy(1.2)}><ZoomInRounded fontSize="small" /></Btn>
        <Box sx={{ flex: 1 }} />
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.4 }}>
          <SearchRounded sx={{ fontSize: 17, color: 'text.secondary' }} />
          <Box component="input" value={q} placeholder="搜索" onChange={(e: any) => setQ(e.target.value)}
            onKeyDown={(e: any) => { if (e.key === 'Enter') search(true, e.shiftKey) }}
            onBlur={() => { if (q) search(false) }} sx={{ ...inputSx, width: 150, px: 1 }} />
          <Typography sx={{ fontSize: 12, color: 'text.secondary', minWidth: 40, whiteSpace: 'nowrap' }}>{found}</Typography>
          <Btn tip="上一个（Shift+Enter）" onClick={() => search(true, true)}><KeyboardArrowUpRounded fontSize="small" /></Btn>
          <Btn tip="下一个（Enter）" onClick={() => search(true, false)}><KeyboardArrowDownRounded fontSize="small" /></Btn>
        </Box>
      </Box>
      <Box sx={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {side && doc && (
          <Box ref={thumbs} sx={{ flex: '0 0 148px', overflowY: 'auto', bgcolor: 'background.paper', borderRight: 1, borderColor: 'divider', pt: 0.5 }}>
            {Array.from({ length: doc.numPages }, (_, i) => <Thumb key={i} doc={doc} n={i + 1} active={page === i + 1} root={thumbs} onClick={() => goto(i + 1)} />)}
          </Box>
        )}
        <Box sx={{ flex: 1, minWidth: 0, position: 'relative' }}>
          <Box ref={wrap}
            sx={{ position: 'absolute', inset: 0, overflow: 'auto', '& .pdfViewer .page': { margin: '8px auto', border: 'none', filter: 'drop-shadow(0 1px 4px rgba(0,0,0,.3))' } }}>
            <div ref={viewerEl} className="pdfViewer" />
          </Box>
          {err && <Typography sx={{ position: 'absolute', left: 0, top: 0, p: 3, color: 'error.main', fontSize: 14 }}>{err}</Typography>}
          {!doc && !err && <Typography sx={{ position: 'absolute', left: 0, top: 0, p: 3, color: 'text.disabled', fontSize: 14 }}>正在加载…</Typography>}
        </Box>
      </Box>
    </Box>
  )
}
