// 资源管理器：VS Code 那样的可展开文件树，点文件夹才去服务器读它。
// 支持多选（Ctrl/Shift+点击）、右键菜单和快捷键：剪切/复制/粘贴、下载、复制路径、重命名、删除、压缩（多选才有）、解压。
// “复制”会把文件下载到本机临时目录并放上 Windows 的文件剪贴板，之后在资源管理器/桌面里直接 Ctrl+V 就是粘贴出来；也可以在树里 Ctrl+V 粘贴到服务器的另一个文件夹。
import ChevronRightRounded from '@mui/icons-material/ChevronRightRounded'
import CreateNewFolderOutlined from '@mui/icons-material/CreateNewFolderOutlined'
import ExpandMoreRounded from '@mui/icons-material/ExpandMoreRounded'
import FolderRounded from '@mui/icons-material/FolderRounded'
import FolderOpenOutlined from '@mui/icons-material/FolderOpenOutlined'
import NoteAddOutlined from '@mui/icons-material/NoteAddOutlined'
import UndoRounded from '@mui/icons-material/UndoRounded'
import RefreshRounded from '@mui/icons-material/RefreshRounded'
import { alpha, Box, Divider, IconButton, InputBase, LinearProgress, ListItemText, Menu, MenuItem, Tooltip, Typography, useTheme } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'
import { getSetting, putSetting, useEvent } from '../hooks'
import FileIcon from './file-icon'
import FolderPicker from './folder-picker'

type Ent = { name: string; dir: boolean; size: number; mtime: number }
type Item = { path: string; name: string; dir: boolean }
const join = (a: string, b: string) => (a.endsWith('/') ? a + b : a + '/' + b)
const parentOf = (p: string) => { const s = p.replace(/\/+$/, ''); const i = s.lastIndexOf('/'); return i <= 0 ? '/' : s.slice(0, i) }
const baseOf = (p: string) => p.replace(/\/+$/, '').split('/').pop() || '/'
const ARC = /\.(zip|jar|tar|tgz|tbz2|txz|tar\.(gz|bz2|xz|zst|lz)|7z|rar|gz|bz2|xz)$/i
const groupByDir = (items: Item[]) => { const m = new Map<string, string[]>(); items.forEach((i) => { const d = parentOf(i.path); m.set(d, [...(m.get(d) || []), i.name]) }); return m }

type Edit = null | { kind: 'file' | 'dir' | 'rename'; dir: string; old?: string; isDir?: boolean; text: string; err?: string }      // 树里正在行内输入名字的那一行
type Undo = { label: string; run: () => Promise<any>; refresh: string[] }
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
  const [edit, setEdit] = useState<Edit>(null)
  const [undos, setUndos] = useState<Undo[]>([])
  const [picker, setPicker] = useState(false)
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
  useEffect(() => {
    setUndos([]); setEdit(null); setSel(new Set()); setDirs({})
    const saved = getSetting('ide.folder.' + alias, '') as string
    const go = async () => {
      let p = saved ? await load(saved) : null
      if (!p) p = await load('')
      if (p) { setRoot(p); setOpen(new Set([p])) }
    }
    go()
  }, [alias])
  const openFolder = (p: string) => {
    putSetting('ide.folder.' + alias, p)
    setPicker(false); setUndos([]); setSel(new Set()); setEdit(null); setDirs({})
    load(p).then((q) => { if (q) { setRoot(q); setOpen(new Set([q])) } })
  }

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
  const view: ({ path: string; ent: Ent; depth: number } | { edit: true; depth: number })[] = []
  const walk = (p: string, depth: number) => {
    const es = dirsRef.current[p] || []
    const nd = es.filter((e) => e.dir).length
    if (edit && edit.kind === 'dir' && edit.dir === p) view.push({ edit: true, depth })              // 新建文件夹：在这个目录的最上面
    es.forEach((e, i) => {
      if (edit && edit.kind === 'file' && edit.dir === p && i === nd) view.push({ edit: true, depth })  // 新建文件：排在文件夹后面、文件前面
      const q = join(p, e.name)
      const r = { path: q, ent: e, depth }
      rows.push(r); view.push(r)
      if (e.dir && open.has(q)) walk(q, depth + 1)
    })
    if (edit && edit.kind === 'file' && edit.dir === p && nd >= es.length) view.push({ edit: true, depth })
  }
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
  const [ghost, setGhost] = useState<null | { x: number; y: number; name: string; n: number; dir: boolean; paths: Set<string> }>(null)      // 跟着鼠标的“拿起来”标签
  const dragging = useRef(false)
  const moveTo = async (picked: Item[], dest: string) => {
    const groups = groupByDir(picked)
    for (const it of picked) if (it.dir && (dest === it.path || dest.startsWith(it.path + '/'))) return setInfo('不能把文件夹移动到它自己里面。')
    setWork(true); setInfo('')
    let n = 0, e = ''
    const moved: string[][] = []
    for (const [dir, names] of groups) {
      if (dir === dest) continue
      const r = await api.ssh_mv(alias, dir, names, dest)
      if (!r.ok) { e = r.error || '移动失败'; break }
      n += r.count ?? names.length; moved.push(...(r.pairs || []))
    }
    setWork(false)
    if (e) return setInfo(e)
    if (!n) return
    pushUndo({ label: `移动 ${n} 项`, run: () => api.ssh_mv_paths(alias, moved.map(([a, b]: string[]) => [b, a])), refresh: [dest, ...groups.keys()] })
    setInfo(`已移动 ${n} 项到 ${baseOf(dest)}`)
    for (const d of new Set([dest, ...groups.keys()])) if (d === dest || dirsRef.current[d]) await refresh(d)
    setOpen((o) => new Set(o).add(dest)); setSel(new Set())
  }
  const startDrag = (e: React.MouseEvent, path: string, ent: Ent) => {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || dragging.current) return
    const x0 = e.clientX, y0 = e.clientY
    let started = false, hover = '', hoverT = 0
    const picked: Item[] = sel.has(path) ? selItems() : [{ path, name: ent.name, dir: ent.dir }]
    const finish = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); clearTimeout(hoverT); setDropOn(''); setGhost(null); dragging.current = false; document.body.style.cursor = '' }
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
        window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); clearTimeout(hoverT); setDropOn(''); setGhost(null); document.body.style.cursor = ''
        setInfo(`正在拖出 ${picked.length} 项，放到资源管理器或桌面里就开始复制…`)
        api.ssh_drag(alias, picked).then((r: any) => { if (!r?.ok) setInfo(r?.error || '拖出失败') }).finally(() => { dragging.current = false })
        return
      }
      setGhost({ x: m.clientX, y: m.clientY, name: ent.name, n: picked.length, dir: ent.dir, paths: new Set(picked.map((i) => i.path)) })
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
  const pushUndo = (u: Undo) => setUndos((s) => [...s.slice(-49), u])
  const doUndo = async () => {
    const u = undos[undos.length - 1]; if (!u || work) return
    setUndos((s) => s.slice(0, -1)); setWork(true); setInfo('')
    const r = await u.run()
    setWork(false)
    if (!r?.ok) return setInfo(r?.error || '撤销失败')
    setInfo('已撤销：' + u.label)
    for (const d of new Set(u.refresh)) if (d === root || dirsRef.current[d]) await refresh(d)
  }
  // 行内新建 / 重命名（像 VS Code：树里直接出现一行输入框）
  const startCreate = async (kind: 'file' | 'dir') => {
    if (!root) return
    const dir = pasteDir() || root
    if (!open.has(dir)) { if (!dirsRef.current[dir]) await load(dir); setOpen((o) => new Set(o).add(dir)) }
    setEdit({ kind, dir, text: '' })
  }
  const startRename = () => { if (single) setEdit({ kind: 'rename', dir: parentOf(single.path), old: single.name, isDir: single.dir, text: single.name }) }
  const submitEdit = async (ed: NonNullable<Edit>) => {
    const name = ed.text.trim()
    if (!name || (ed.kind === 'rename' && name === ed.old)) return setEdit(null)
    if (/[\\/]/.test(name) || name === '.' || name === '..') return setEdit({ ...ed, err: '名字里不能有 / 或 \\' })
    if ((dirsRef.current[ed.dir] || []).some((e) => e.name === name)) return setEdit({ ...ed, err: `这里已经有“${name}”了` })
    setEdit(null)
    const full = join(ed.dir, name)
    if (ed.kind === 'file') {
      if (await run(() => api.ssh_write_file(alias, full, ''), `已新建 ${name}`, ed.dir)) { pushUndo({ label: `新建 ${name}`, run: () => api.ssh_rm_paths(alias, [full]), refresh: [ed.dir] }); onOpen(full) }
    } else if (ed.kind === 'dir') {
      if (await run(() => api.ssh_mkdir(alias, ed.dir, name), `已新建文件夹 ${name}`, ed.dir)) pushUndo({ label: `新建文件夹 ${name}`, run: () => api.ssh_rm_paths(alias, [full]), refresh: [ed.dir] })
    } else if (ed.old) {
      const from = join(ed.dir, ed.old)
      if (await run(() => api.ssh_rename(alias, ed.dir, ed.old!, name), '已重命名', ed.dir)) pushUndo({ label: `重命名 ${ed.old}`, run: () => api.ssh_mv_paths(alias, [[full, from]]), refresh: [ed.dir] })
    }
  }
  const editRow = (depth: number, isDir: boolean, key: string) => edit && (
    <Box key={key} sx={{ display: 'flex', alignItems: 'center', height: 24, pl: `${6 + depth * 12}px`, pr: 1, fontSize: 13 }}>
      <Box sx={{ width: 18, flexShrink: 0, display: 'flex' }}>{isDir ? <ChevronRightRounded sx={{ fontSize: 18 }} /> : null}</Box>
      {isDir ? <FolderRounded sx={{ fontSize: 17, mr: 0.7, color: 'primary.main', flexShrink: 0 }} /> : <FileIcon name={edit.text || 'x'} dark={dark} />}
      <Tooltip open={!!edit.err} title={edit.err || ''} placement="bottom-start" arrow>
        <InputBase autoFocus value={edit.text} spellCheck={false} onChange={(e) => setEdit((x) => x && { ...x, text: e.target.value, err: undefined })}
          onFocus={(e) => { const v = e.target.value, dot = v.lastIndexOf('.'); e.target.setSelectionRange(0, edit.kind === 'rename' && !isDir && dot > 0 ? dot : v.length) }}
          onKeyDown={(e) => { e.stopPropagation(); if (e.key === 'Enter') submitEdit(edit); else if (e.key === 'Escape') setEdit(null) }}
          onBlur={() => { if (edit.text.trim() && !edit.err) submitEdit(edit); else setEdit(null) }}
          onClick={(e) => e.stopPropagation()} onContextMenu={(e) => e.stopPropagation()}
          sx={{ flex: 1, minWidth: 0, height: 22, px: 0.6, fontSize: 13, borderRadius: 0.5, border: 1, borderColor: edit.err ? 'error.main' : 'primary.main', bgcolor: 'background.paper' }} />
      </Tooltip>
    </Box>
  )

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
    const moved: string[][] = [], made: string[] = []
    for (const [dir, names] of groups) {
      if (c.cut && dir === dest) continue
      const r = await (c.cut ? api.ssh_mv(alias, dir, names, dest) : api.ssh_cp(alias, dir, names, dest))
      if (!r.ok) { e = r.error || '操作失败'; break }
      n += r.count ?? names.length; moved.push(...(r.pairs || [])); made.push(...(r.created || []))
    }
    setWork(false)
    if (e) return setInfo(e)
    if (c.cut) { CLIP = null; setClipVer((v) => v + 1) }
    if (c.cut && moved.length) pushUndo({ label: `移动 ${n} 项`, run: () => api.ssh_mv_paths(alias, moved.map(([a, b]) => [b, a])), refresh: [dest, ...groups.keys()] })
    if (!c.cut && made.length) pushUndo({ label: `复制 ${n} 项`, run: () => api.ssh_rm_paths(alias, made), refresh: [dest] })
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
    const trashed: string[][] = []
    for (const [dir, names] of groups) {
      const r = await api.ssh_trash(alias, dir, names)
      if (!r.ok) { e = r.error || '删除失败'; break }
      if (!r.big) trashed.push(...(r.pairs || []))
      if (r.big) {
        if (!window.confirm(`“${names.join('、')}”超过 100MB，删除后无法恢复，确定删除吗？`)) continue
        const r2 = await api.ssh_rm(alias, dir, names)
        if (!r2.ok) { e = r2.error || '删除失败'; break }
      }
      n += names.length
    }
    setWork(false)
    setSel(new Set())
    if (trashed.length) pushUndo({ label: `删除 ${trashed.length} 项`, run: () => api.ssh_restore(alias, trashed), refresh: [...groups.keys()] })
    for (const d of groups.keys()) if (dirsRef.current[d]) await refresh(d)
    setInfo(e || `已删除 ${n} 项`)
  }
  const doArchive = () => {
    if (!sameParent) return
    const parent = parentOf(items[0].path)
    let made: string[] = []
    run(async () => { const r = await api.ssh_archive(alias, parent, items.map((i) => i.name), 'zip'); made = r.created || []; return r }, `已压缩 ${items.length} 项`, parent).then((ok) => { if (ok && made.length) pushUndo({ label: '压缩', run: () => api.ssh_rm_paths(alias, made), refresh: [parent] }) })
  }
  const doExtract = () => {
    if (!single) return
    const par = parentOf(single.path)
    let made: string[] = []
    run(async () => { const r = await api.ssh_extract(alias, par, [single.name], false); made = r.created || []; return r }, `已解压 ${single.name}`, par).then((ok) => { if (ok && made.length) pushUndo({ label: '解压', run: () => api.ssh_rm_paths(alias, made), refresh: [par] }) })
  }

  // ---- 快捷键（树获得焦点时）：Ctrl+X/C/V、Shift+Alt+C、Ctrl+K Ctrl+Shift+C、F2、Delete
  const onKey = (e: React.KeyboardEvent) => {
    if (edit || menu) return
    const c = e.ctrlKey || e.metaKey
    if (c && e.code === 'KeyK') { e.preventDefault(); chord.current = Date.now(); return }
    const chorded = chord.current && Date.now() - chord.current < 2000; chord.current = 0
    if (chorded && c && e.shiftKey && e.code === 'KeyC') { e.preventDefault(); copyPath(true); return }
    if (c && !e.shiftKey && !e.altKey && e.code === 'KeyC') { e.preventDefault(); doCopy() }
    else if (c && !e.shiftKey && !e.altKey && e.code === 'KeyX') { e.preventDefault(); doCut() }
    else if (c && !e.shiftKey && !e.altKey && e.code === 'KeyV') { e.preventDefault(); doPaste() }
    else if (e.shiftKey && e.altKey && !c && e.code === 'KeyC') { e.preventDefault(); copyPath(false) }
    else if (c && !e.shiftKey && !e.altKey && e.code === 'KeyZ') { e.preventDefault(); doUndo() }
    else if (e.key === 'F2') { e.preventDefault(); startRename() }
    else if (e.key === 'Delete') { e.preventDefault(); doDelete() }
  }

  const act = (f: () => void) => () => { setMenu(null); f() }
  const hint = (t: string) => <Typography variant="caption" color="text.secondary" sx={{ ml: 3, whiteSpace: 'nowrap' }}>{t}</Typography>
  const item = (label: string, key: string, f: () => void, extra?: { color?: string; disabled?: boolean }) => (
    <MenuItem dense disabled={extra?.disabled} onClick={act(f)} sx={{ color: extra?.color }}><ListItemText>{label}</ListItemText>{key && hint(key)}</MenuItem>
  )
  const pct = prog && prog.total ? Math.min(100, (prog.sent / prog.total) * 100) : 0
  const hasMenu = !!root

  return (
    <Box ref={box} tabIndex={0} onKeyDown={onKey} sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, userSelect: 'none', outline: 'none' }}
      onContextMenu={(e) => { e.preventDefault(); setSel(new Set()); setMenu({ x: e.clientX, y: e.clientY }) }}>
      {ghost && (
        <Box sx={{ position: 'fixed', left: ghost.x + 14, top: ghost.y + 10, zIndex: 3000, pointerEvents: 'none', display: 'flex', alignItems: 'center', gap: 0.7, px: 1, height: 26, borderRadius: 1.5, fontSize: 13, maxWidth: 260,
          bgcolor: 'background.paper', color: 'text.primary', border: 1, borderColor: 'primary.main', boxShadow: 4 }}>
          {ghost.dir ? <FolderRounded sx={{ fontSize: 17, color: 'primary.main', flexShrink: 0 }} /> : <FileIcon name={ghost.name} dark={dark} />}
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ghost.name}</span>
          {ghost.n > 1 && <Box component="span" sx={{ ml: 0.3, px: 0.7, minWidth: 18, textAlign: 'center', borderRadius: 9, bgcolor: 'primary.main', color: 'primary.contrastText', fontSize: 11.5, fontWeight: 700, lineHeight: '18px' }}>{ghost.n}</Box>}
        </Box>
      )}
      <Box sx={{ display: 'flex', alignItems: 'center', px: 1, height: 34, flexShrink: 0 }}>
        <Typography sx={{ fontSize: 11.5, fontWeight: 700, letterSpacing: 0.5, color: 'text.secondary', flex: 1 }}>资源管理器</Typography>
        <Tooltip title="打开文件夹"><span><IconButton size="small" disabled={!root} onClick={() => setPicker(true)}><FolderOpenOutlined sx={{ fontSize: 17 }} /></IconButton></span></Tooltip>
        <Tooltip title="新建文件"><span><IconButton size="small" disabled={!root} onClick={() => startCreate('file')}><NoteAddOutlined sx={{ fontSize: 17 }} /></IconButton></span></Tooltip>
        <Tooltip title="新建文件夹"><span><IconButton size="small" disabled={!root} onClick={() => startCreate('dir')}><CreateNewFolderOutlined sx={{ fontSize: 17 }} /></IconButton></span></Tooltip>
        <Tooltip title={undos.length ? `撤销：${undos[undos.length - 1].label}（Ctrl+Z）` : '没有可撤销的操作'}><span><IconButton size="small" disabled={!undos.length || work} onClick={doUndo}><UndoRounded sx={{ fontSize: 17 }} /></IconButton></span></Tooltip>
        <Tooltip title="刷新"><IconButton size="small" disabled={!root} onClick={() => open.forEach((p) => refresh(p))}><RefreshRounded sx={{ fontSize: 17 }} /></IconButton></Tooltip>
      </Box>
      {root && <Box data-exrow={root} data-dir="1" onClick={() => toggle(root)} sx={{ outline: dropOn === root ? '1px solid' : 'none', outlineColor: 'primary.main', outlineOffset: -1, display: 'flex', alignItems: 'center', px: 0.8, height: 24, flexShrink: 0, cursor: 'pointer', fontSize: 12.5, fontWeight: 700, '&:hover': { bgcolor: 'action.hover' } }}>
        {open.has(root) ? <ExpandMoreRounded sx={{ fontSize: 18 }} /> : <ChevronRightRounded sx={{ fontSize: 18 }} />}<span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{baseOf(root).toUpperCase()}</span>
      </Box>}
      {prog ? <LinearProgress variant={prog.total ? 'determinate' : 'indeterminate'} value={pct} sx={{ height: 2, flexShrink: 0 }} />
        : (busy.size > 0 || work) && <LinearProgress sx={{ height: 2, flexShrink: 0 }} />}
      <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto', pb: 1 }}>
        {err && <Typography sx={{ m: 1, fontSize: 12.5, color: 'text.secondary' }}>{err}</Typography>}
        {view.map((v, vi) => 'edit' in v ? editRow(v.depth, edit?.kind === 'dir', 'edit' + vi) : (edit?.kind === 'rename' && edit.dir === parentOf(v.path) && edit.old === v.ent.name) ? editRow(v.depth, v.ent.dir, v.path) : (({ path, ent, depth }) => (
          <Box key={path} data-exrow={path} data-dir={ent.dir ? '1' : '0'} onClick={(e) => clickRow(e, path, ent)} onMouseDown={(e) => startDrag(e, path, ent)}
            onContextMenu={(e) => { e.preventDefault(); e.stopPropagation(); box.current?.focus(); if (!sel.has(path)) { setSel(new Set([path])); anchor.current = path } setMenu({ x: e.clientX, y: e.clientY }) }}
            sx={{ display: 'flex', alignItems: 'center', height: 24, pl: `${6 + depth * 12}px`, pr: 1, cursor: 'pointer', userSelect: 'none', fontSize: 13, bgcolor: sel.has(path) ? 'action.selected' : 'transparent', outline: dropOn && ent.dir && dropOn === path ? '1px solid' : 'none', ...(dropOn && ent.dir && dropOn === path ? { bgcolor: (th: any) => alpha(th.palette.primary.main, 0.16) } : {}), outlineColor: 'primary.main', outlineOffset: -1, '&:hover': { bgcolor: sel.has(path) ? 'action.selected' : 'action.hover' },
              opacity: ghost?.paths.has(path) || (CLIP?.cut && CLIP.alias === alias && CLIP.items.some((i) => i.path === path)) ? 0.5 : 1 }}>
            <Box sx={{ width: 18, flexShrink: 0, display: 'flex' }}>{ent.dir ? (open.has(path) ? <ExpandMoreRounded sx={{ fontSize: 18 }} /> : <ChevronRightRounded sx={{ fontSize: 18 }} />) : null}</Box>
            {ent.dir ? <FolderRounded sx={{ fontSize: 17, mr: 0.7, color: 'primary.main', flexShrink: 0 }} /> : <FileIcon name={ent.name} dark={dark} />}
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ent.name}</span>
            {busy.has(path) && <Box sx={{ ml: 'auto', width: 10, height: 10, borderRadius: '50%', border: 2, borderColor: 'primary.main', borderTopColor: 'transparent', animation: 'spin 0.8s linear infinite', '@keyframes spin': { to: { transform: 'rotate(360deg)' } } }} />}
          </Box>
        ))(v))}
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
        {item('新建文件…', '', () => startCreate('file'))}
        {item('新建文件夹…', '', () => startCreate('dir'))}
        <Divider />
        {items.length > 0 && item('剪切', 'Ctrl+X', doCut)}
        {items.length > 0 && item('复制', 'Ctrl+C', doCopy)}
        {!!CLIP && item(`粘贴${CLIP.alias === alias ? `（${CLIP.items.length} 项）` : ''}`, 'Ctrl+V', doPaste, { disabled: CLIP.alias !== alias })}
        {(items.length > 0 || !!CLIP) && <Divider />}
        {items.length > 0 && item('下载…', '', doDownload)}
        {(sameParent || (single && !single.dir && ARC.test(single.name))) && <Divider />}
        {sameParent && item('压缩为 ZIP', '', doArchive)}
        {single && !single.dir && ARC.test(single.name) && item('解压到同名文件夹', '', doExtract)}
        {items.length > 0 && <Divider />}
        {items.length > 0 && item('复制路径', 'Shift+Alt+C', () => copyPath(false))}
        {items.length > 0 && item('复制相对路径', 'Ctrl+K Ctrl+Shift+C', () => copyPath(true))}
        {items.length > 0 && <Divider />}
        {undos.length > 0 && item(`撤销：${undos[undos.length - 1].label}`, 'Ctrl+Z', doUndo)}
        {single && item('重命名…', 'F2', startRename)}
        {items.length > 0 && item('删除', 'Del', doDelete, { color: 'error.main' })}
      </Menu>
      <FolderPicker alias={alias} open={picker} initial={root} onClose={() => setPicker(false)} onPick={openFolder} />
    </Box>
  )
}
