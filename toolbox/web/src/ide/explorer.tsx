// 资源管理器：VS Code 那样的可展开文件树，点文件夹才去服务器读它。
// 支持多选（Ctrl/Shift+点击）、右键菜单和快捷键：剪切/复制/粘贴、下载、复制路径、重命名、删除、压缩（多选才有）、解压。
// “复制”会把文件下载到本机临时目录并放上 Windows 的文件剪贴板，之后在资源管理器/桌面里直接 Ctrl+V 就是粘贴出来；也可以在树里 Ctrl+V 粘贴到服务器的另一个文件夹。
import ChevronRightRounded from '@mui/icons-material/ChevronRightRounded'
import CreateNewFolderOutlined from '@mui/icons-material/CreateNewFolderOutlined'
import ExpandMoreRounded from '@mui/icons-material/ExpandMoreRounded'
import FolderRounded from '@mui/icons-material/FolderRounded'
import DriveFolderUploadOutlined from '@mui/icons-material/DriveFolderUploadOutlined'
import NoteAddOutlined from '@mui/icons-material/NoteAddOutlined'
import UploadFileOutlined from '@mui/icons-material/UploadFileOutlined'
import RefreshRounded from '@mui/icons-material/RefreshRounded'
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Divider, IconButton, LinearProgress, ListItemText, Menu, MenuItem, TextField, Tooltip, Typography, useTheme } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'
import { rounded } from '../components/common'
import { useEvent } from '../hooks'
import FileIcon from './file-icon'

type Ent = { name: string; dir: boolean; size: number; mtime: number }
type Item = { path: string; name: string; dir: boolean }
const join = (a: string, b: string) => (a.endsWith('/') ? a + b : a + '/' + b)
const parentOf = (p: string) => { const s = p.replace(/\/+$/, ''); const i = s.lastIndexOf('/'); return i <= 0 ? '/' : s.slice(0, i) }
const baseOf = (p: string) => p.replace(/\/+$/, '').split('/').pop() || '/'
const ARC = /\.(zip|jar|tar|tgz|tbz2|txz|tar\.(gz|bz2|xz|zst|lz)|7z|rar|gz|bz2|xz)$/i
const groupByDir = (items: Item[]) => { const m = new Map<string, string[]>(); items.forEach((i) => { const d = parentOf(i.path); m.set(d, [...(m.get(d) || []), i.name]) }); return m }

type Prompt = null | { kind: 'file' | 'dir' | 'rename'; dir: string; old?: string; text: string }
let CLIP: null | { alias: string; items: Item[]; cut: boolean } = null      // 树里的剪切/复制板（跨主机不通用）

export default function Explorer({ alias, active, onOpen, onResult }: { alias: string; active?: boolean; onOpen: (path: string) => void; onResult?: (ok: boolean, conn: boolean, err?: string) => void }) {
  const dark = useTheme().palette.mode === 'dark'
  const [root, setRoot] = useState('')
  const [dirs, setDirs] = useState<Record<string, Ent[]>>({})
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState<Set<string>>(new Set())
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [err, setErr] = useState('')
  const [info, setInfo] = useState('')
  const [work, setWork] = useState(false)
  const [prog, setProg] = useState<null | { sent: number; total: number; file: string }>(null)
  const [, setClipVer] = useState(0)
  const [menu, setMenu] = useState<null | { x: number; y: number }>(null)
  const [prompt, setPrompt] = useState<Prompt>(null)
  const dirsRef = useRef(dirs); dirsRef.current = dirs
  const anchor = useRef('')
  const box = useRef<HTMLDivElement>(null)
  const chord = useRef(0)
  const upDir = useRef('')                    // 正在上传到哪个文件夹（传完刷新它）
  const mine = useRef(false)                  // 这个面板自己发起的传输（别的主机面板收到同样的事件要忽略）

  const load = async (p: string) => {
    const t = setTimeout(() => setBusy((b) => new Set(b).add(p)), 500)           // 很快就读完的不显示转圈；等了半秒还没好才出现
    const r = await api.ssh_ls(alias, p)
    clearTimeout(t)
    setBusy((b) => { if (!b.has(p)) return b; const n = new Set(b); n.delete(p); return n })
    onResult?.(!!r.ok, !!r.conn, r.error)
    if (!r.ok) { setErr(r.error || '读取失败'); return null }
    setErr(''); setDirs((d) => ({ ...d, [r.path]: r.entries })); return r.path as string
  }
  useEffect(() => { load('').then((p) => { if (p) { setRoot(p); setOpen(new Set([p])) } }) }, [alias])

  const toggle = async (p: string) => {
    if (open.has(p)) { setOpen((o) => { const n = new Set(o); n.delete(p); return n }); return }
    if (!dirsRef.current[p]) await load(p)
    setOpen((o) => new Set(o).add(p))
  }
  const refresh = (p: string) => load(p)

  // ---- 传输事件（复制到 Windows 剪贴板 / 下载）
  useEvent('ssh:progress', (d: any) => { if (mine.current) setProg({ sent: d.sent || 0, total: d.total || 0, file: d.file || '' }) })
  useEvent('ssh:done', (d: any) => {
    if (!mine.current || d.alias !== alias) return
    mine.current = false; setProg(null)
    if (!d.ok) return setInfo(d.cancelled ? '已取消。' : d.error || '传输失败。')
    if (d.kind === 'up') { setInfo(`已上传 ${d.count} 个文件到 ${baseOf(upDir.current)}。`); if (upDir.current) refresh(upDir.current); return }
    if (d.kind === 'clip') setInfo(`已复制 ${d.count} 个文件，到 Windows 里按 Ctrl+V 就能粘贴出来。`)
    else setInfo(`已下载 ${d.count} 个文件到 ${d.dest || '下载文件夹'}。`)
  })

  // ---- 行 / 选择
  const rows: { path: string; ent: Ent; depth: number }[] = []
  const walk = (p: string, depth: number) => { for (const e of dirsRef.current[p] || []) { const q = join(p, e.name); rows.push({ path: q, ent: e, depth }); if (e.dir && open.has(q)) walk(q, depth + 1) } }
  if (root && open.has(root)) walk(root, 0)
  const selItems = (): Item[] => rows.filter((r) => sel.has(r.path)).map((r) => ({ path: r.path, name: r.ent.name, dir: r.ent.dir }))
  const items = selItems()
  const single = items.length === 1 ? items[0] : null
  const sameParent = items.length > 1 && items.every((i) => parentOf(i.path) === parentOf(items[0].path))
  const pasteDir = () => (single ? (single.dir ? single.path : parentOf(single.path)) : root)

  // ---- 上传：按钮，或把文件/文件夹拖进窗口（传到选中的文件夹；没选就传到根目录）
  const upload = async (paths: string[]) => {
    if (!paths?.length || mine.current || !root) return
    const dir = pasteDir() || root
    upDir.current = dir; mine.current = true; setProg({ sent: 0, total: 0, file: '' }); setInfo(`上传到 ${baseOf(dir)}…`)
    const r = await api.ssh_upload(alias, paths, dir)
    if (!r.ok) { mine.current = false; setProg(null); setInfo(r.error || '上传失败') }
  }
  useEvent('files:ssh', (paths: string[]) => { if (active) upload(paths) })

  // 按住文件/文件夹拖动：松在某个文件夹上 = 移动到那里；拖出窗口外（资源管理器、桌面）= 下载
  // （虚拟文件：拖的时候不下载，放下那一刻才从服务器读）。拖动中悬停的文件夹高亮，悬停久了会自动展开。
  const [dropOn, setDropOn] = useState('')
  const dragging = useRef(false)
  const moveTo = async (picked: Item[], dest: string) => {
    const groups = groupByDir(picked)
    for (const it of picked) if (it.dir && (dest === it.path || dest.startsWith(it.path + '/'))) return setInfo('不能把文件夹移动到它自己里面。')
    setWork(true); setInfo('')
    let n = 0, e = ''
    for (const [dir, names] of groups) {
      if (dir === dest) continue
      const r = await api.ssh_mv(alias, dir, names, dest)
      if (!r.ok) { e = r.error || '移动失败'; break }
      n += r.count ?? names.length
    }
    setWork(false)
    if (e) return setInfo(e)
    if (!n) return
    setInfo(`已移动 ${n} 项到 ${baseOf(dest)}`)
    for (const d of new Set([dest, ...groups.keys()])) if (d === dest || dirsRef.current[d]) await refresh(d)
    setOpen((o) => new Set(o).add(dest)); setSel(new Set())
  }
  const startDrag = (e: React.MouseEvent, path: string, ent: Ent) => {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || dragging.current) return
    const x0 = e.clientX, y0 = e.clientY
    let started = false, hover = '', hoverT = 0
    const picked: Item[] = sel.has(path) ? selItems() : [{ path, name: ent.name, dir: ent.dir }]
    const finish = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); clearTimeout(hoverT); setDropOn(''); dragging.current = false; document.body.style.cursor = '' }
    const dirAt = (x: number, y: number) => {
      const el = document.elementFromPoint(x, y)?.closest('[data-exrow]') as HTMLElement | null
      if (!el || !box.current?.contains(el)) return ''
      const p = el.getAttribute('data-exrow') || ''
      return el.getAttribute('data-dir') === '1' ? p : parentOf(p)       // 悬停在文件上 = 它所在的文件夹
    }
    const move = (m: MouseEvent) => {
      if (!started) {
        if (Math.hypot(m.clientX - x0, m.clientY - y0) < 6) return
        started = true; dragging.current = true
        if (!sel.has(path)) { setSel(new Set([path])); anchor.current = path }
        document.body.style.cursor = 'grabbing'
      }
      if (m.clientX < 0 || m.clientY < 0 || m.clientX >= window.innerWidth || m.clientY >= window.innerHeight) {
        // 拖出窗口：交给系统拖放（此时左键还按着）
        window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); clearTimeout(hoverT); setDropOn(''); document.body.style.cursor = ''
        setInfo(`正在拖出 ${picked.length} 项，放到资源管理器或桌面里就开始复制…`)
        api.ssh_drag(alias, picked).then((r: any) => { if (!r?.ok) setInfo(r?.error || '拖出失败') }).finally(() => { dragging.current = false })
        return
      }
      const d = dirAt(m.clientX, m.clientY)
      if (d !== hover) {
        hover = d; setDropOn(d); clearTimeout(hoverT)
        if (d && d !== root && !open.has(d)) hoverT = window.setTimeout(() => toggle(d), 700)
      }
    }
    const up = () => {
      const wasStarted = started, dest = hover
      finish()
      if (wasStarted) {
        suppressClick.current = true; setTimeout(() => { suppressClick.current = false }, 0)
        if (dest) moveTo(picked, dest)
      }
    }
    window.addEventListener('mousemove', move); window.addEventListener('mouseup', up)
  }
  const suppressClick = useRef(false)

  const clickRow = (e: React.MouseEvent, path: string, ent: Ent) => {
    if (suppressClick.current) return
    box.current?.focus()
    if (e.ctrlKey || e.metaKey) { setSel((s) => { const n = new Set(s); n.has(path) ? n.delete(path) : n.add(path); return n }); anchor.current = path; return }
    if (e.shiftKey && anchor.current) {
      const a = rows.findIndex((r) => r.path === anchor.current), b = rows.findIndex((r) => r.path === path)
      if (a >= 0 && b >= 0) { setSel(new Set(rows.slice(Math.min(a, b), Math.max(a, b) + 1).map((r) => r.path))); return }
    }
    setSel(new Set([path])); anchor.current = path
    ent.dir ? toggle(path) : onOpen(path)
  }

  // ---- 操作
  const run = async (fn: () => Promise<any>, ok: string, reload: string) => {
    setWork(true); setInfo('')
    const r = await fn()
    setWork(false)
    if (!r.ok) { setInfo(r.error || '操作失败'); return false }
    setInfo(ok); await refresh(reload); return true
  }
  const submitPrompt = async () => {
    const pr = prompt; setPrompt(null)
    const name = pr?.text.trim()
    if (!pr || !name) return
    if (/[\\/]/.test(name)) return setInfo('名字里不能有 / 或 \\')
    const names = (dirsRef.current[pr.dir] || []).map((e) => e.name)
    if (names.includes(name) && name !== pr.old) return setInfo('已经有同名的文件或文件夹了')
    if (pr.kind === 'file') { if (await run(() => api.ssh_write_file(alias, join(pr.dir, name), ''), `已新建 ${name}`, pr.dir)) onOpen(join(pr.dir, name)) }
    else if (pr.kind === 'dir') await run(() => api.ssh_mkdir(alias, pr.dir, name), `已新建文件夹 ${name}`, pr.dir)
    else if (pr.old && name !== pr.old) await run(() => api.ssh_rename(alias, pr.dir, pr.old!, name), '已重命名', pr.dir)
  }
  const startRename = () => { if (single) setPrompt({ kind: 'rename', dir: parentOf(single.path), old: single.name, text: single.name }) }

  const doCut = () => {
    if (!items.length) return
    CLIP = { alias, items, cut: true }; setClipVer((v) => v + 1)
    setInfo(`已剪切 ${items.length} 项，选中目标文件夹后按 Ctrl+V 粘贴。`)
  }
  const doCopy = async () => {
    if (!items.length) return
    CLIP = { alias, items, cut: false }; setClipVer((v) => v + 1)
    mine.current = true; setProg({ sent: 0, total: 0, file: '' }); setInfo('正在复制到剪贴板…')
    const r = await api.ssh_clip_copy(alias, items)
    if (!r.ok) { mine.current = false; setProg(null); setInfo(r.error || '复制失败') }
  }
  const doDownload = async () => {
    if (!items.length) return
    mine.current = true; setProg({ sent: 0, total: 0, file: '' }); setInfo('')
    const r = await api.ssh_download(alias, items)
    if (!r.ok) { mine.current = false; setProg(null); setInfo(r.error || '下载失败') }
  }
  const doPaste = async () => {
    const c = CLIP; if (!c || !root) return
    if (c.alias !== alias) return setInfo('暂不支持跨主机粘贴：请先“下载”，再把文件拖进这台主机。')
    const dest = pasteDir(), groups = groupByDir(c.items)
    setWork(true); setInfo('')
    let n = 0, e = ''
    for (const [dir, names] of groups) {
      if (c.cut && dir === dest) continue
      const r = await (c.cut ? api.ssh_mv(alias, dir, names, dest) : api.ssh_cp(alias, dir, names, dest))
      if (!r.ok) { e = r.error || '操作失败'; break }
      n += r.count ?? names.length
    }
    setWork(false)
    if (e) return setInfo(e)
    if (c.cut) { CLIP = null; setClipVer((v) => v + 1) }
    setInfo(`已${c.cut ? '移动' : '复制'} ${n} 项到 ${baseOf(dest)}`)
    for (const d of new Set([dest, ...groups.keys()])) if (d === dest || dirsRef.current[d]) await refresh(d)
    setOpen((o) => new Set(o).add(dest))
  }
  const copyPath = (rel: boolean) => {
    if (!items.length) return
    navigator.clipboard?.writeText(items.map((i) => (rel ? i.path.slice(root.length).replace(/^\//, '') || i.name : i.path)).join('\n'))
    setInfo(rel ? '已复制相对路径' : '已复制路径')
  }
  // 删除：100MB 以内悄悄移进服务器的垃圾目录；超过的弹窗确认后永久删除
  const doDelete = async () => {
    if (!items.length) return
    setWork(true); setInfo('')
    const groups = groupByDir(items)
    let n = 0, e = ''
    for (const [dir, names] of groups) {
      const r = await api.ssh_trash(alias, dir, names)
      if (!r.ok) { e = r.error || '删除失败'; break }
      if (r.big) {
        if (!window.confirm(`“${names.join('、')}”超过 100MB，删除后无法恢复，确定删除吗？`)) continue
        const r2 = await api.ssh_rm(alias, dir, names)
        if (!r2.ok) { e = r2.error || '删除失败'; break }
      }
      n += names.length
    }
    setWork(false)
    setSel(new Set())
    for (const d of groups.keys()) if (dirsRef.current[d]) await refresh(d)
    setInfo(e || `已删除 ${n} 项`)
  }
  const doArchive = () => {
    if (!sameParent) return
    const parent = parentOf(items[0].path)
    run(() => api.ssh_archive(alias, parent, items.map((i) => i.name), 'zip'), `已压缩 ${items.length} 项`, parent)
  }
  const doExtract = () => { if (single) run(() => api.ssh_extract(alias, parentOf(single.path), [single.name], false), `已解压 ${single.name}`, parentOf(single.path)) }

  // ---- 快捷键（树获得焦点时）：Ctrl+X/C/V、Shift+Alt+C、Ctrl+K Ctrl+Shift+C、F2、Delete
  const onKey = (e: React.KeyboardEvent) => {
    if (prompt || menu) return
    const c = e.ctrlKey || e.metaKey
    if (c && e.code === 'KeyK') { e.preventDefault(); chord.current = Date.now(); return }
    const chorded = chord.current && Date.now() - chord.current < 2000; chord.current = 0
    if (chorded && c && e.shiftKey && e.code === 'KeyC') { e.preventDefault(); copyPath(true); return }
    if (c && !e.shiftKey && !e.altKey && e.code === 'KeyC') { e.preventDefault(); doCopy() }
    else if (c && !e.shiftKey && !e.altKey && e.code === 'KeyX') { e.preventDefault(); doCut() }
    else if (c && !e.shiftKey && !e.altKey && e.code === 'KeyV') { e.preventDefault(); doPaste() }
    else if (e.shiftKey && e.altKey && !c && e.code === 'KeyC') { e.preventDefault(); copyPath(false) }
    else if (e.key === 'F2') { e.preventDefault(); startRename() }
    else if (e.key === 'Delete') { e.preventDefault(); doDelete() }
  }

  const act = (f: () => void) => () => { setMenu(null); f() }
  const hint = (t: string) => <Typography variant="caption" color="text.secondary" sx={{ ml: 3, whiteSpace: 'nowrap' }}>{t}</Typography>
  const item = (label: string, key: string, f: () => void, extra?: { color?: string; disabled?: boolean }) => (
    <MenuItem dense disabled={extra?.disabled} onClick={act(f)} sx={{ color: extra?.color }}><ListItemText>{label}</ListItemText>{key && hint(key)}</MenuItem>
  )
  const pct = prog && prog.total ? Math.min(100, (prog.sent / prog.total) * 100) : 0
  const hasMenu = items.length > 0 || !!CLIP

  return (
    <Box ref={box} tabIndex={0} onKeyDown={onKey} sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, userSelect: 'none', outline: 'none' }}
      onContextMenu={(e) => { e.preventDefault(); setSel(new Set()); if (CLIP) setMenu({ x: e.clientX, y: e.clientY }) }}>
      <Box sx={{ display: 'flex', alignItems: 'center', px: 1, height: 34, flexShrink: 0 }}>
        <Typography sx={{ fontSize: 11.5, fontWeight: 700, letterSpacing: 0.5, color: 'text.secondary', flex: 1 }}>资源管理器</Typography>
        <Tooltip title="新建文件"><IconButton size="small" disabled={!root} onClick={() => setPrompt({ kind: 'file', dir: single?.dir ? single.path : single ? parentOf(single.path) : root, text: '' })}><NoteAddOutlined sx={{ fontSize: 17 }} /></IconButton></Tooltip>
        <Tooltip title="新建文件夹"><IconButton size="small" disabled={!root} onClick={() => setPrompt({ kind: 'dir', dir: single?.dir ? single.path : single ? parentOf(single.path) : root, text: '' })}><CreateNewFolderOutlined sx={{ fontSize: 17 }} /></IconButton></Tooltip>
        <Tooltip title="上传文件到服务器（也可以把文件拖进窗口）"><span><IconButton size="small" disabled={!root || !!prog} onClick={async () => upload(await api.pick_files('any'))}><UploadFileOutlined sx={{ fontSize: 17 }} /></IconButton></span></Tooltip>
        <Tooltip title="上传文件夹"><span><IconButton size="small" disabled={!root || !!prog} onClick={async () => { const d = await api.pick_folder(); if (d) upload([d]) }}><DriveFolderUploadOutlined sx={{ fontSize: 17 }} /></IconButton></span></Tooltip>
        <Tooltip title="刷新"><IconButton size="small" disabled={!root} onClick={() => open.forEach((p) => refresh(p))}><RefreshRounded sx={{ fontSize: 17 }} /></IconButton></Tooltip>
      </Box>
      {root && <Box data-exrow={root} data-dir="1" onClick={() => toggle(root)} sx={{ outline: dropOn === root ? '1px solid' : 'none', outlineColor: 'primary.main', outlineOffset: -1, display: 'flex', alignItems: 'center', px: 0.8, height: 24, flexShrink: 0, cursor: 'pointer', fontSize: 12.5, fontWeight: 700, '&:hover': { bgcolor: 'action.hover' } }}>
        {open.has(root) ? <ExpandMoreRounded sx={{ fontSize: 18 }} /> : <ChevronRightRounded sx={{ fontSize: 18 }} />}<span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{baseOf(root).toUpperCase()}</span>
      </Box>}
      {prog ? <LinearProgress variant={prog.total ? 'determinate' : 'indeterminate'} value={pct} sx={{ height: 2, flexShrink: 0 }} />
        : (busy.size > 0 || work) && <LinearProgress sx={{ height: 2, flexShrink: 0 }} />}
      <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto', pb: 1 }}>
        {err && <Typography sx={{ m: 1, fontSize: 12.5, color: 'text.secondary' }}>{err}</Typography>}
        {rows.map(({ path, ent, depth }) => (
          <Box key={path} data-exrow={path} data-dir={ent.dir ? '1' : '0'} onClick={(e) => clickRow(e, path, ent)} onMouseDown={(e) => startDrag(e, path, ent)}
            onContextMenu={(e) => { e.preventDefault(); e.stopPropagation(); box.current?.focus(); if (!sel.has(path)) { setSel(new Set([path])); anchor.current = path } setMenu({ x: e.clientX, y: e.clientY }) }}
            sx={{ display: 'flex', alignItems: 'center', height: 24, pl: `${6 + depth * 12}px`, pr: 1, cursor: 'pointer', userSelect: 'none', fontSize: 13, bgcolor: sel.has(path) ? 'action.selected' : 'transparent', outline: dropOn && ent.dir && dropOn === path ? '1px solid' : 'none', outlineColor: 'primary.main', outlineOffset: -1, '&:hover': { bgcolor: sel.has(path) ? 'action.selected' : 'action.hover' },
              opacity: CLIP?.cut && CLIP.alias === alias && CLIP.items.some((i) => i.path === path) ? 0.5 : 1 }}>
            <Box sx={{ width: 18, flexShrink: 0, display: 'flex' }}>{ent.dir ? (open.has(path) ? <ExpandMoreRounded sx={{ fontSize: 18 }} /> : <ChevronRightRounded sx={{ fontSize: 18 }} />) : null}</Box>
            {ent.dir ? <FolderRounded sx={{ fontSize: 17, mr: 0.7, color: 'primary.main', flexShrink: 0 }} /> : <FileIcon name={ent.name} dark={dark} />}
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ent.name}</span>
            {busy.has(path) && <Box sx={{ ml: 'auto', width: 10, height: 10, borderRadius: '50%', border: 2, borderColor: 'primary.main', borderTopColor: 'transparent', animation: 'spin 0.8s linear infinite', '@keyframes spin': { to: { transform: 'rotate(360deg)' } } }} />}
          </Box>
        ))}
      </Box>
      {(info || prog) && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1, py: 0.5, borderTop: 1, borderColor: 'divider' }}>
          <Typography sx={{ fontSize: 11.5, color: 'text.secondary', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={info}>
            {prog ? `${info || '传输中…'}${prog.total ? ` ${Math.round(pct)}%` : ''}` : info}
          </Typography>
          {prog && <Typography onClick={() => api.ssh_cancel()} sx={{ fontSize: 11.5, color: 'primary.main', cursor: 'pointer', flexShrink: 0 }}>取消</Typography>}
        </Box>
      )}

      <Menu open={!!menu && hasMenu} onClose={() => setMenu(null)} anchorReference="anchorPosition" anchorPosition={menu ? { top: menu.y, left: menu.x } : undefined} slotProps={{ paper: { sx: { borderRadius: 2, minWidth: 250 } } }} onContextMenu={(e) => { e.preventDefault(); setMenu(null) }}>
        {items.length > 0 && item('剪切', 'Ctrl+X', doCut)}
        {items.length > 0 && item('复制', 'Ctrl+C', doCopy)}
        {!!CLIP && item(`粘贴${CLIP.alias === alias ? `（${CLIP.items.length} 项）` : ''}`, 'Ctrl+V', doPaste, { disabled: CLIP.alias !== alias })}
        {items.length > 0 && <Divider />}
        {items.length > 0 && item('下载…', '', doDownload)}
        {(sameParent || (single && !single.dir && ARC.test(single.name))) && <Divider />}
        {sameParent && item('压缩为 ZIP', '', doArchive)}
        {single && !single.dir && ARC.test(single.name) && item('解压到同名文件夹', '', doExtract)}
        {items.length > 0 && <Divider />}
        {items.length > 0 && item('复制路径', 'Shift+Alt+C', () => copyPath(false))}
        {items.length > 0 && item('复制相对路径', 'Ctrl+K Ctrl+Shift+C', () => copyPath(true))}
        {items.length > 0 && <Divider />}
        {single && item('重命名…', 'F2', startRename)}
        {items.length > 0 && item('删除', 'Del', doDelete, { color: 'error.main' })}
      </Menu>
      <Dialog open={!!prompt} onClose={() => setPrompt(null)} slotProps={{ paper: { sx: { borderRadius: 3, width: 380 } } }}>
        <DialogTitle sx={{ fontWeight: 700, fontSize: 16 }}>{prompt?.kind === 'file' ? '新建文件' : prompt?.kind === 'dir' ? '新建文件夹' : '重命名'}</DialogTitle>
        <DialogContent>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, wordBreak: 'break-all' }}>{prompt?.dir}</Typography>
          <TextField autoFocus fullWidth size="small" value={prompt?.text || ''} onChange={(e) => setPrompt((p) => p && { ...p, text: e.target.value })} onKeyDown={(e) => { if (e.key === 'Enter') submitPrompt() }} sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }} />
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={() => setPrompt(null)} sx={rounded}>取消</Button><Button variant="contained" onClick={submitPrompt} sx={rounded}>确定</Button></DialogActions>
      </Dialog>
    </Box>
  )
}
