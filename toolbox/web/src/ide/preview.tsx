// 编辑器里的文件预览：图片、PDF、Excel 表格、Markdown。
// 图片/PDF/表格没有 Monaco 模型，按字节从服务器读回来（api.ssh_read_bytes，base64），在这里渲染；Markdown 仍是文本文件，预览只是把源码渲染一遍。
import ZoomInRounded from '@mui/icons-material/ZoomInRounded'
import ZoomOutRounded from '@mui/icons-material/ZoomOutRounded'
import { Box, IconButton, Typography } from '@mui/material'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../bridge'

export type PKind = 'image' | 'pdf' | 'sheet'

const IMG_MIME: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', jfif: 'image/jpeg', gif: 'image/gif', webp: 'image/webp', bmp: 'image/bmp',
  svg: 'image/svg+xml', ico: 'image/x-icon', avif: 'image/avif',
}
const SHEET_EXT = new Set(['xlsx', 'xlsm', 'xlsb', 'xls', 'ods'])
const MD_EXT = new Set(['md', 'markdown', 'mdown', 'mkd'])
const MB = 1048576
const LIMIT: Record<PKind, number> = { image: 60 * MB, pdf: 150 * MB, sheet: 40 * MB }

const extOf = (p: string) => (p.split('/').pop() || '').toLowerCase().split('.').slice(1).pop() || ''
export const previewKind = (p: string): PKind | null => {
  const e = extOf(p)
  if (IMG_MIME[e]) return 'image'
  if (e === 'pdf') return 'pdf'
  if (SHEET_EXT.has(e)) return 'sheet'
  return null
}
export const isMarkdown = (p: string) => MD_EXT.has(extOf(p))

const toBytes = (b64: string) => {
  const s = atob(b64), u = new Uint8Array(s.length)
  for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i)
  return u
}

export type Loaded = { url?: string; bytes?: Uint8Array; doc?: any; wb?: any; X?: any; sheets?: string[]; size: number; w?: number; h?: number }

// 从服务器读回文件并做好渲染要用的东西（对象地址 / 解析好的工作簿）。表格库只在真打开表格时才加载。
export async function loadPreview(alias: string, path: string, kind: PKind): Promise<{ ok: true; pv: Loaded } | { ok: false; error: string }> {
  let r: any
  try { r = await api.ssh_read_bytes(alias, path, LIMIT[kind]) } catch (e) { return { ok: false, error: String(e) } }
  if (!r?.ok) return { ok: false, error: r?.error || '打不开' }
  const bytes = toBytes(r.b64)
  if (kind === 'sheet') {
    try {
      const XLSX = await import('xlsx')
      const wb = XLSX.read(bytes, { type: 'array', cellDates: true })
      return { ok: true, pv: { wb, X: XLSX, sheets: wb.SheetNames, size: bytes.length } }
    } catch (e) { return { ok: false, error: '表格解析失败：' + String(e) } }
  }
  if (kind === 'pdf') return { ok: true, pv: { bytes, size: bytes.length } }          // PDF 交给 pdf.js 自己画（不用 WebView2 自带查看器，它的工具栏/侧栏嵌在界面里不好看）
  const mime = IMG_MIME[extOf(path)] || 'application/octet-stream'
  return { ok: true, pv: { url: URL.createObjectURL(new Blob([bytes], { type: mime })), size: bytes.length } }
}
export const freePreview = (pv?: Loaded) => { if (pv?.url) URL.revokeObjectURL(pv.url); try { pv?.doc?.destroy() } catch { /* 已经销毁 */ } }

const sizeText = (n: number) => (n >= MB ? (n / MB).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB')

// 滚轮/捏合缩放的系数：跟滚动量成比例。鼠标滚轮一格 deltaY≈±100（约 1.2 倍）；触控板双指捏合会连发很多个很小的 deltaY（带 ctrlKey），按同样的倍率会放大几十倍，所以小量走更灵敏但平滑的系数
export const wheelFactor = (e: { deltaY: number; deltaMode?: number }) => {
  const dy = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY
  const k = Math.abs(dy) < 40 ? 0.008 : 0.002
  return Math.exp(Math.max(-60, Math.min(60, -dy)) * k)
}
// 在元素上挂“按住 Ctrl 的滚轮/触控板捏合”缩放；必须用原生监听（React 的 onWheel 是被动的，拦不住浏览器自己的页面缩放）。不按 Ctrl 的滚轮照常滚动内容
export const useCtrlWheel = (ref: React.RefObject<HTMLElement | null>, on: (factor: number) => void) => {
  const cb = useRef(on); cb.current = on
  useEffect(() => {
    const el = ref.current; if (!el) return
    const h = (e: WheelEvent) => { if (!e.ctrlKey) return; e.preventDefault(); cb.current(wheelFactor(e)) }
    el.addEventListener('wheel', h, { passive: false })
    return () => el.removeEventListener('wheel', h)
  }, [])
}

// ---------------- 图片：适应窗口，滚轮缩放，双击在“适应/原始大小”之间切换 ----------------
function ImageView({ pv, dark, onMeta }: { pv: Loaded; dark: boolean; onMeta: (s: string) => void }) {
  const [z, setZ] = useState(0)                           // 0 = 适应窗口；其它是缩放倍数
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null)
  const box = useRef<HTMLDivElement>(null)
  useCtrlWheel(box, (k) => zoomBy(k))
  const zoomBy = (k: number) => setZ((v) => Math.min(16, Math.max(0.05, (v || fitScale()) * k)))
  const fitScale = () => {
    if (!nat || !box.current) return 1
    return Math.min(1, (box.current.clientWidth - 24) / nat.w, (box.current.clientHeight - 24) / nat.h)
  }
  useEffect(() => { onMeta(nat ? `${nat.w} × ${nat.h} · ${sizeText(pv.size)}` : sizeText(pv.size)) }, [nat])
  const scale = z || fitScale()
  const checker = dark ? 'linear-gradient(45deg,#33364a 25%,transparent 25%,transparent 75%,#33364a 75%),linear-gradient(45deg,#33364a 25%,#2a2c3a 25%,#2a2c3a 75%,#33364a 75%)'
    : 'linear-gradient(45deg,#e9e9ee 25%,transparent 25%,transparent 75%,#e9e9ee 75%),linear-gradient(45deg,#e9e9ee 25%,#fff 25%,#fff 75%,#e9e9ee 75%)'
  return (
    <Box sx={{ position: 'absolute', inset: 0 }}>
      <Box ref={box}
        sx={{ position: 'absolute', inset: 0, overflow: 'auto', display: 'flex', backgroundImage: checker, backgroundSize: '20px 20px', backgroundPosition: '0 0, 10px 10px' }}>
        <img src={pv.url} alt="" draggable={false} onDoubleClick={() => setZ(z ? 0 : 1)}
          onLoad={(e) => setNat({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
          style={{ margin: 'auto', flexShrink: 0, width: nat ? nat.w * scale : undefined, height: nat ? nat.h * scale : undefined, imageRendering: scale > 3 ? 'pixelated' : 'auto' }} />
      </Box>
      <Box sx={{ position: 'absolute', right: 14, bottom: 12, display: 'flex', alignItems: 'center', gap: 0.2, px: 0.6, borderRadius: 2, bgcolor: 'background.paper', border: 1, borderColor: 'divider', filter: 'drop-shadow(0 2px 6px rgba(0,0,0,.25))' }}>
        <IconButton size="small" onClick={() => zoomBy(1 / 1.25)}><ZoomOutRounded fontSize="small" /></IconButton>
        <Typography onClick={() => setZ(z ? 0 : 1)} title="点一下在“适应窗口 / 原始大小”之间切换" sx={{ fontSize: 12, width: 44, textAlign: 'center', cursor: 'pointer', userSelect: 'none' }}>{Math.round(scale * 100)}%</Typography>
        <IconButton size="small" onClick={() => zoomBy(1.25)}><ZoomInRounded fontSize="small" /></IconButton>
      </Box>
    </Box>
  )
}

// ---------------- PDF 在 pdf-view.tsx（用到时才加载 pdf.js）
const PdfView = lazy(() => import('./pdf-view'))

// ---------------- Excel：每个工作表一个标签，只渲染前面一部分行列，免得卡住 ----------------
const MAX_ROWS = 2000, MAX_COLS = 80
const colName = (i: number) => { let s = ''; for (i++; i > 0; i = Math.floor((i - 1) / 26)) s = String.fromCharCode(65 + ((i - 1) % 26)) + s; return s }
const cellText = (c: any): string => {
  if (c === undefined || c === null) return ''
  const v = c.v
  if (v === undefined || v === null) return ''
  if (c.w !== undefined) return String(c.w)                 // 表格里显示的格式化文本（日期、百分比、千分位…）
  if (v instanceof Date) return v.toISOString().slice(0, 10)
  return String(v)
}
function SheetView({ pv, onMeta }: { pv: Loaded; onMeta: (s: string) => void }) {
  const [idx, setIdx] = useState(0)
  const name = pv.sheets![idx]
  const grid = useMemo(() => {
    const ws = pv.wb.Sheets[name]
    const ref = ws?.['!ref']
    if (!ref) return { rows: [] as string[][], nr: 0, nc: 0, r0: 0, c0: 0 }
    const X = pv.X
    const rg = X.utils.decode_range(ref)
    const r0 = rg.s.r, c0 = rg.s.c, r1 = rg.e.r, c1 = rg.e.c
    const nr = Math.min(r1 + 1, MAX_ROWS + r0), nc = Math.min(c1 + 1, MAX_COLS + c0)
    const rows: string[][] = []
    for (let r = r0; r < nr; r++) {
      const line: string[] = []
      for (let c = c0; c < nc; c++) line.push(cellText(ws[X.utils.encode_cell({ r, c })]))
      rows.push(line)
    }
    return { rows, nr: r1 - r0 + 1, nc: c1 - c0 + 1, r0, c0 }
  }, [pv, name])
  useEffect(() => {
    const cut = grid.nr > MAX_ROWS || grid.nc > MAX_COLS
    onMeta(`${sizeText(pv.size)} · ${grid.nr} 行 × ${grid.nc} 列${cut ? `（只显示前 ${Math.min(grid.nr, MAX_ROWS)} 行 ${Math.min(grid.nc, MAX_COLS)} 列）` : ''}`)
  }, [grid])
  const cols = grid.rows.length ? grid.rows[0].length : 0
  return (
    <Box sx={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column' }}>
      <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto', bgcolor: 'background.paper' }}>
        {grid.rows.length === 0 ? (
          <Typography sx={{ p: 3, color: 'text.disabled', fontSize: 14 }}>这个工作表是空的</Typography>
        ) : (
          <Box component="table" sx={{ borderCollapse: 'separate', borderSpacing: 0, fontSize: 12.5, fontFamily: 'Consolas, "Microsoft YaHei UI", monospace',
            '& td, & th': { border: 0, borderRight: 1, borderBottom: 1, borderColor: 'divider', px: 1, py: '3px', whiteSpace: 'pre', maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', height: 24 },
            '& th': { position: 'sticky', top: 0, zIndex: 2, bgcolor: 'background.default', color: 'text.secondary', fontWeight: 500, textAlign: 'center' },
            '& th.rn': { position: 'sticky', left: 0, zIndex: 1, top: 'auto', minWidth: 42 }, '& th.corner': { left: 0, zIndex: 3 } }}>
            <thead>
              <tr><th className="corner" />{Array.from({ length: cols }, (_, i) => <th key={i}>{colName(grid.c0 + i)}</th>)}</tr>
            </thead>
            <tbody>
              {grid.rows.map((row, r) => (
                <tr key={r}>
                  <th className="rn">{grid.r0 + r + 1}</th>
                  {row.map((t, c) => <td key={c} title={t.length > 40 ? t : undefined}>{t}</td>)}
                </tr>
              ))}
            </tbody>
          </Box>
        )}
      </Box>
      {pv.sheets!.length > 1 && (
        <Box sx={{ flex: '0 0 30px', display: 'flex', overflowX: 'auto', borderTop: 1, borderColor: 'divider', bgcolor: 'background.default' }}>
          {pv.sheets!.map((s, i) => (
            <Box key={s + i} onClick={() => setIdx(i)}
              sx={{ px: 1.6, display: 'flex', alignItems: 'center', fontSize: 12.5, cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0, color: i === idx ? 'primary.main' : 'text.secondary', fontWeight: i === idx ? 600 : 400,
                bgcolor: i === idx ? 'background.paper' : 'transparent', borderTop: 2, borderTopColor: i === idx ? 'primary.main' : 'transparent', '&:hover': { color: 'text.primary' } }}>{s}</Box>
          ))}
        </Box>
      )}
    </Box>
  )
}

export function PreviewView({ kind, pv, dark, onMeta }: { kind: PKind; pv: Loaded; dark: boolean; onMeta: (s: string) => void }) {
  if (kind === 'image') return <ImageView pv={pv} dark={dark} onMeta={onMeta} />
  if (kind === 'pdf') return <Suspense fallback={<Typography sx={{ p: 3, color: 'text.disabled', fontSize: 14 }}>正在加载…</Typography>}><PdfView pv={pv} dark={dark} onMeta={onMeta} /></Suspense>
  return <SheetView pv={pv} onMeta={onMeta} />
}

// ---------------- Markdown ----------------
marked.setOptions({ gfm: true, breaks: false })
export function MdView({ text, dark }: { text: string; dark: boolean }) {
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(text, { async: false }) as string, { USE_PROFILES: { html: true } }), [text])
  const link = (e: React.MouseEvent) => {
    const a = (e.target as HTMLElement).closest('a')
    if (!a) return
    e.preventDefault()
    const href = a.getAttribute('href') || ''
    if (/^https?:\/\//i.test(href)) api.open_url(href)         // 只放行网页链接；相对路径、锚点不处理
  }
  const code = dark ? '#33364a' : '#eceef2'
  return (
    <Box onClick={link} className="md"
      sx={{ position: 'absolute', inset: 0, overflow: 'auto', px: { xs: 3, md: 6 }, py: 3, bgcolor: 'background.paper', color: 'text.primary', fontSize: 15, lineHeight: 1.75, wordBreak: 'break-word', userSelect: 'text',
        '& > *': { maxWidth: 860, mx: 'auto' },
        '& h1,& h2,& h3,& h4,& h5,& h6': { fontWeight: 600, lineHeight: 1.3, mt: 3, mb: 1.4 },
        '& h1': { fontSize: '2em', pb: 0.6, borderBottom: 1, borderColor: 'divider' }, '& h2': { fontSize: '1.5em', pb: 0.5, borderBottom: 1, borderColor: 'divider' }, '& h3': { fontSize: '1.2em' },
        '& p, & ul, & ol, & blockquote, & pre, & table': { my: 1.4 }, '& ul, & ol': { pl: 3.2 }, '& li': { my: 0.3 },
        '& a': { color: 'primary.main', textDecoration: 'none', '&:hover': { textDecoration: 'underline' } },
        '& code': { fontFamily: 'Consolas, "Cascadia Mono", monospace', fontSize: '0.88em', bgcolor: code, px: 0.7, py: 0.15, borderRadius: 0.8 },
        '& pre': { bgcolor: code, p: 1.6, borderRadius: 1.2, overflow: 'auto', '& code': { bgcolor: 'transparent', p: 0, fontSize: '0.86em' } },
        '& blockquote': { m: 0, my: 1.4, pl: 2, borderLeft: 4, borderColor: 'divider', color: 'text.secondary' },
        '& table': { borderCollapse: 'collapse', display: 'block', overflow: 'auto', '& th, & td': { border: 1, borderColor: 'divider', px: 1.4, py: 0.6 }, '& th': { bgcolor: code } },
        '& hr': { border: 0, borderTop: 1, borderColor: 'divider', my: 3 }, '& img': { maxWidth: '100%' } }}
      dangerouslySetInnerHTML={{ __html: html }} />
  )
}
