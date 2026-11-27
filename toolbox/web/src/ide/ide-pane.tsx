// 一台主机的“VS Code 式”工作区：左边资源管理器，右上编辑器（标签页），下面是终端，中间的分隔线都能拖。
import KeyboardArrowDownRounded from '@mui/icons-material/KeyboardArrowDownRounded'
import KeyboardArrowUpRounded from '@mui/icons-material/KeyboardArrowUpRounded'
import { Box, CircularProgress, IconButton, Tooltip } from '@mui/material'
import { lazy, Suspense, useRef, useState } from 'react'

import type { SysInfo } from '../components/sysinfo-bar'
import Explorer from './explorer'
import type { OpenReq } from './editor-panel'

const EditorPanel = lazy(() => import('./editor-panel'))           // Monaco 比较大，用到时才加载

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

function Splitter({ dir, onDrag }: { dir: 'v' | 'h'; onDrag: (d: number) => void }) {
  const down = (e: React.MouseEvent) => {
    e.preventDefault()
    let last = dir === 'v' ? e.clientX : e.clientY
    const move = (m: MouseEvent) => { const p = dir === 'v' ? m.clientX : m.clientY; onDrag(p - last); last = p }
    const up = () => { window.removeEventListener('mousemove', move); document.body.style.cursor = '' }
    document.body.style.cursor = dir === 'v' ? 'col-resize' : 'row-resize'
    window.addEventListener('mousemove', move); window.addEventListener('mouseup', up, { once: true })
  }
  return <Box onMouseDown={down} sx={{ flex: dir === 'v' ? '0 0 4px' : '0 0 4px', cursor: dir === 'v' ? 'col-resize' : 'row-resize', bgcolor: 'divider', opacity: 0.5, '&:hover': { bgcolor: 'primary.main', opacity: 1 }, transition: 'background-color .15s' }} />
}

export default function IdePane({ alias, active, dark, info, renderTerm, onResult }: {
  alias: string; active: boolean; dark: boolean; info?: SysInfo | null
  renderTerm: (visible: boolean, collapse: () => void, tabsSlot: HTMLElement | null) => React.ReactNode; onResult?: (alias: string, ok: boolean, conn: boolean, err?: string) => void
}) {
  const [exW, setExW] = useState(250)
  const [dockH, setDockH] = useState(280)
  const [dockOpen, setDockOpen] = useState(true)
  const [req, setReq] = useState<OpenReq>(null)
  const n = useRef(0)
  const wrap = useRef<HTMLDivElement>(null)
  const [tabsEl, setTabsEl] = useState<HTMLElement | null>(null)       // 终端会话标签放在面板标题行的右侧

  const termVisible = active && dockOpen

  return (
    <Box ref={wrap} sx={{ position: 'absolute', inset: 0, display: active ? 'flex' : 'none', minHeight: 0 }}>
      <Box sx={{ flex: `0 0 ${exW}px`, minWidth: 0, borderRight: 0, bgcolor: 'background.paper' }}>
        <Explorer alias={alias} cloudPath={info?.cloudPath} active={active} onOpen={(p) => setReq({ path: p, n: ++n.current })} onResult={(ok, conn, err) => onResult?.(alias, ok, conn, err)} />
      </Box>
      <Splitter dir="v" onDrag={(d) => setExW((w) => clamp(w + d, 160, 520))} />
      <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <Box sx={{ flex: 1, minHeight: 80, bgcolor: (th) => (th.palette.mode === 'light' ? '#ffffff' : 'transparent') }}>
          <Suspense fallback={<Box sx={{ p: 3, display: 'flex', gap: 1, alignItems: 'center', color: 'text.secondary' }}><CircularProgress size={16} />正在加载编辑器…</Box>}>
            <EditorPanel alias={alias} req={req} visible={active} dark={dark} info={info} />
          </Suspense>
        </Box>
        {dockOpen && <Splitter dir="h" onDrag={(d) => setDockH((h) => clamp(h - d, 90, (wrap.current?.clientHeight || 700) - 140))} />}
        <Box sx={{ flex: dockOpen ? `0 0 ${dockH}px` : '0 0 30px', minHeight: 0, display: 'flex', flexDirection: 'column', borderTop: dockOpen ? 0 : 1, borderColor: 'divider' }}>
          <Box sx={{ flex: '0 0 30px', display: 'flex', alignItems: 'center', px: 0.5 }}>
            <Box onClick={() => setDockOpen(true)} sx={{ px: 1.4, height: '100%', display: 'flex', alignItems: 'center', cursor: 'pointer', fontSize: 12.5, fontWeight: 700, borderBottom: 2, borderColor: 'primary.main' }}>终端</Box>
            <Box sx={{ flex: 1 }} />
            <Box ref={setTabsEl} sx={{ display: 'flex', alignItems: 'center', minWidth: 0, maxWidth: '70%' }} />
            <Tooltip title={dockOpen ? '收起面板' : '展开面板'}><IconButton size="small" onClick={() => setDockOpen((o) => !o)}>{dockOpen ? <KeyboardArrowDownRounded fontSize="small" /> : <KeyboardArrowUpRounded fontSize="small" />}</IconButton></Tooltip>
          </Box>
          <Box sx={{ flex: 1, minHeight: 0, position: 'relative', display: dockOpen ? 'block' : 'none' }}>
            <Box sx={{ position: 'absolute', inset: 0 }}>{renderTerm(termVisible, () => setDockOpen(false), tabsEl)}</Box>
          </Box>
        </Box>
      </Box>
    </Box>
  )
}
