import AddRounded from '@mui/icons-material/AddRounded'
import BoltRounded from '@mui/icons-material/BoltRounded'
import CloseRounded from '@mui/icons-material/CloseRounded'
import DragIndicatorRounded from '@mui/icons-material/DragIndicatorRounded'
import ArrowUpwardRounded from '@mui/icons-material/ArrowUpwardRounded'
import UndoRounded from '@mui/icons-material/UndoRounded'
import CheckCircleOutline from '@mui/icons-material/CheckCircleOutline'
import CreateNewFolderOutlined from '@mui/icons-material/CreateNewFolderOutlined'
import DownloadOutlined from '@mui/icons-material/DownloadOutlined'
import DriveFolderUploadOutlined from '@mui/icons-material/DriveFolderUploadOutlined'
import EditOutlined from '@mui/icons-material/EditOutlined'
import ErrorOutline from '@mui/icons-material/ErrorOutline'
import FolderRounded from '@mui/icons-material/FolderRounded'
import FolderZipOutlined from '@mui/icons-material/FolderZipOutlined'
import UnarchiveOutlined from '@mui/icons-material/UnarchiveOutlined'
import InsertDriveFileOutlined from '@mui/icons-material/InsertDriveFileOutlined'
import RefreshRounded from '@mui/icons-material/RefreshRounded'
import TerminalOutlined from '@mui/icons-material/TerminalOutlined'
import UploadFileOutlined from '@mui/icons-material/UploadFileOutlined'
import VpnKeyOutlined from '@mui/icons-material/VpnKeyOutlined'
import DnsOutlined from '@mui/icons-material/DnsOutlined'
import ContentCopyOutlined from '@mui/icons-material/ContentCopyOutlined'
import ContentCutOutlined from '@mui/icons-material/ContentCutOutlined'
import ContentPasteOutlined from '@mui/icons-material/ContentPasteOutlined'
import DeleteOutline from '@mui/icons-material/DeleteOutline'
import DriveFileRenameOutline from '@mui/icons-material/DriveFileRenameOutline'
import FolderOpenOutlined from '@mui/icons-material/FolderOpenOutlined'
import ShareOutlined from '@mui/icons-material/ShareOutlined'
import { alpha, Alert, Badge, Box, Button, Checkbox, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Divider, IconButton, InputAdornment, LinearProgress, ListItemIcon, ListItemText, Menu, MenuItem, Tab, Tabs, TextField, Tooltip, Typography, useTheme } from '@mui/material'
import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { api } from '../bridge'
import { BasePage } from '../components/base-page'
import { Switch } from '../components/base-switch'
import { InfoTip, rounded, Row, Segment } from '../components/common'
import { EnhancedCard } from '../components/enhanced-card'
import { GpuBars, GpuBoard, GpuMini, useGpu } from '../components/gpu-board'
import SysInfoBar, { SysInfoBadge, type SysInfo } from '../components/sysinfo-bar'
import { CUR_DIR } from '../ide/explorer'
import IdePane from '../ide/ide-pane'
import VsCodeIcon from '../components/vscode-icon'
import { groupSessions } from '../components/share-people'
import { human, useEvent } from '../hooks'

type Addr = { host: string; port: number; internal?: boolean | null }
type Host = { common_key?: boolean; alias: string; host: string; user: string; port: number; identity: string; has_password: boolean; managed: boolean; addrs?: Addr[] }
const isPrivate = (h: string) => /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h.trim())
const field = { size: 'small' as const, fullWidth: true, sx: { mb: 1.2, '& .MuiOutlinedInput-root': { borderRadius: 2 } } }
const fmtDate = (t: number) => (t ? new Date(t * 1000).toLocaleString('zh-CN', { hour12: false, year: '2-digit', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '')
const soft = (e?: string) => (e || '').replace(/^连接失败：/, '').replace(/^所有地址都连不上/, '所有地址都没连上')
// 连接类的提示用平和口吻：SSH 主机可能长期不在线，不是需要马上修的故障
const softMsg = (e: string) => (/^(连接失败|所有地址|连接 .*超时|.*拒绝了连接|找不到主机)/.test(e) ? '暂时没连上这台主机（可能不在线，或不在同一网络）。' + soft(e) : e)
const parentOf = (p: string) => { const s = p.replace(/\/+$/, ''); const i = s.lastIndexOf('/'); return i <= 0 ? '/' : s.slice(0, i) }
const joinPath = (a: string, b: string) => (a.endsWith('/') ? a + b : a + '/' + b)
const ARC_RE = /\.(zip|jar|tar|tgz|tbz2|txz|tar\.(gz|bz2|xz|zst|lz)|7z|rar|gz|bz2|xz)$/i
const arcStem = (n: string) => n.replace(ARC_RE, '') || n
const target = (h: Host) => `${h.user ? h.user + '@' : ''}${h.host}${h.port !== 22 ? ':' + h.port : ''}`

// ----------------------------------------------------------------------------------- 添加 / 编辑主机
// 解析一条 ssh 命令：ssh -p 2222 -i ~/.ssh/k user@host（也认 -l 用户、-o Port=/User=/HostName=/IdentityFile=、-p2222 连写；-J/-L 等其它选项忽略）。认不出主机就返回 null。
function parseSshCmd(text: string): { host: string; port: number; user: string; identity: string } | null {
  const toks = (text.trim().match(/"[^"]*"|'[^']*'|\S+/g) || []).map((t) => t.replace(/^["']|["']$/g, ''))
  if (!toks.length) return null
  let i = /^(.*[\/])?ssh(\.exe)?$/i.test(toks[0]) ? 1 : 0
  let host = '', port = 0, user = '', identity = ''
  const withArg = new Set(['-b', '-c', '-D', '-E', '-e', '-F', '-I', '-J', '-L', '-m', '-O', '-Q', '-R', '-S', '-W', '-w'])
  for (; i < toks.length; i++) {
    const t = toks[i]
    if (t.startsWith('-')) {
      const flag = t.slice(0, 2), rest = t.slice(2)
      const val = () => (rest || toks[++i] || '')
      if (flag === '-p') port = parseInt(val(), 10) || 0
      else if (flag === '-l') user = val()
      else if (flag === '-i') identity = val()
      else if (flag === '-o') {
        const m = /^(\w+)[= ]\s*(.*)$/.exec(val())
        if (m) { const k = m[1].toLowerCase(); if (k === 'port') port = parseInt(m[2], 10) || port; else if (k === 'user') user = m[2]; else if (k === 'hostname') host = host || m[2]; else if (k === 'identityfile') identity = m[2] }
      } else if (withArg.has(flag) && !rest) i++
      continue
    }
    if (!host) {
      const m = /^(?:([^@]+)@)?(\[[^\]]+\]|[^:@\s]+)(?::(\d+))?$/.exec(t)
      if (!m) return null
      if (m[1]) user = m[1]
      host = m[2].replace(/^\[|\]$/g, '')
      if (m[3] && !port) port = parseInt(m[3], 10)
    }
    break                                          // 主机后面是要在远端执行的命令，不管它
  }
  return host ? { host, port: port || 22, user, identity } : null
}

function HostDialog({ open, host, onClose, onSaved }: { open: boolean; host: Host | null; onClose: () => void; onSaved: (h: Host, note: string) => void }) {
  const edit = !!host
  const [f, setF] = useState({ alias: '', user: '', password: '', identity: '' })
  const [addrs, setAddrs] = useState<{ host: string; port: string }[]>([{ host: '', port: '22' }])
  const [adv, setAdv] = useState(false)
  const [over, setOver] = useState(-1)
  const overRef = useRef(-1)
  const rowRefs = useRef<(HTMLElement | null)[]>([])
  const [show, setShow] = useState(false)
  const [res, setRes] = useState<null | { ok: boolean; text: string; via?: string; rows?: any[] }>(null)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [cmd, setCmd] = useState('')
  const [cmdHint, setCmdHint] = useState('')

  useEffect(() => {
    if (!open) return
    setCmd(''); setCmdHint('')
    setF(host ? { alias: host.alias, user: host.user, password: '', identity: host.identity } : { alias: '', user: '', password: '', identity: '' })
    const list = host ? (host.addrs?.length ? host.addrs : [{ host: host.host, port: host.port }]) : [{ host: '', port: 22 }]
    setAddrs(list.map((a) => ({ host: a.host, port: String(a.port) }))); setAdv(list.length > 1)
    setRes(null); setErr(''); setShow(false)
  }, [open, host])
  const set = (k: string) => (e: any) => { setF({ ...f, [k]: e.target.value }); setRes(null) }
  const setAddr = (i: number, k: 'host' | 'port') => (e: any) => { setAddrs((l) => l.map((a, j) => (j === i ? { ...a, [k]: e.target.value } : a))); setRes(null) }
  // 使用命令添加：粘贴 ssh -p 端口 用户@主机，自动填好下面的字段（别名留空时用主机名）
  const onCmd = (e: any) => {
    const v = e.target.value
    setCmd(v)
    const r = parseSshCmd(v)
    if (!v.trim()) { setCmdHint(''); return }
    if (!r) { setCmdHint('没认出主机，格式像：ssh -p 2222 用户名@主机'); return }
    setF((o) => ({ ...o, user: r.user || o.user, identity: r.identity || o.identity }))
    setAddrs((l) => [{ host: r.host, port: String(r.port) }, ...l.slice(1)])
    setRes(null)
    setCmdHint(`已识别：${r.user ? r.user + '@' : ''}${r.host}  端口 ${r.port}${r.identity ? '  私钥 ' + r.identity : ''}。密码在下面填。`)
  }
  const moveAddr = (from: number, to: number) => { if (from < 0 || from === to) return; setAddrs((l) => { const x = [...l]; const [it] = x.splice(from, 1); x.splice(to, 0, it); return x }); setRes(null) }
  const startDrag = (i: number) => (e: React.MouseEvent) => {
    e.preventDefault(); overRef.current = i; setOver(i)
    document.body.style.cursor = 'grabbing'; document.body.style.userSelect = 'none'
    const move = (ev: MouseEvent) => {
      const mids = rowRefs.current.map((r) => { if (!r) return Infinity; const b = r.getBoundingClientRect(); return b.top + b.height / 2 })
      let idx = mids.findIndex((m) => ev.clientY < m); if (idx < 0) idx = Math.max(0, rowRefs.current.length - 1)
      if (idx !== overRef.current) { overRef.current = idx; setOver(idx) }
    }
    const up = () => {
      document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up)
      document.body.style.cursor = ''; document.body.style.userSelect = ''
      moveAddr(i, overRef.current); setOver(-1)
    }
    document.addEventListener('mousemove', move); document.addEventListener('mouseup', up)
  }
  const filled = addrs.filter((a) => a.host.trim())
  const defAlias = () => { const h = filled[0]?.host.trim() || ''; const pt = Number(filled[0]?.port) || 22; return (pt === 22 ? h : `${h}-${pt}`).replace(/[^A-Za-z0-9._-]/g, '-').slice(0, 64) }      // 别名没填就用主机地址（非 22 端口加上端口号）
  const payload = () => ({ ...f, alias: f.alias.trim() || defAlias(), addrs: filled.map((a) => ({ host: a.host.trim(), port: Number(a.port) || 22 })), old_alias: host?.alias })

  const test = async () => {
    setBusy('test'); setErr(''); setRes(null)
    const r = await api.ssh_test(payload())
    setBusy('')
    const rows: any[] = r.rows || []
    setRes(r.ok
      ? { ok: true, via: r.via, rows, text: `连接成功（${r.via === 'key' ? '密钥' : '密码'}登录${r.addr && filled.length > 1 ? ' · 走 ' + r.addr.host + (r.internal ? '（内网）' : '') : ''}${r.os ? ' · ' + r.os : ''}）` }
      : { ok: false, rows, text: rows.length > 1 ? '所有地址都没连上，看每一行右边的原因。' : r.error })
  }
  const save = async () => {
    setBusy('save'); setErr('')
    const r = await api.ssh_save(payload(), host?.alias)
    setBusy('')
    if (!r.ok) return setErr(r.error)
    onSaved(r.host, r.note || '')
    onClose()
  }
  const del = async () => { await api.ssh_delete(host!.alias); onSaved({ ...host!, alias: '' }, '已删除。'); onClose() }
  const pickKey = async () => { const r = await api.pick_files('any'); if (r?.length) { setF({ ...f, identity: r[0] }); setRes(null) } }

  return (
    <Dialog open={open} onClose={() => !busy && onClose()} PaperProps={{ sx: { borderRadius: 3, width: 460 } }}>
      <DialogTitle sx={{ fontWeight: 700 }}>{edit ? '编辑主机' : '添加主机'}</DialogTitle>
      <DialogContent>
        <Box sx={{ pt: 1 }}>
          {!edit && (
            <>
              <TextField {...field} label="使用SSH命令添加（可选）" placeholder="粘贴 ssh 命令，如 ssh -p 2222 用户名@主机" value={cmd} onChange={onCmd} autoFocus
                inputProps={{ spellCheck: false, style: { fontFamily: 'Consolas, monospace', fontSize: 13 } }} sx={{ ...field.sx, mb: cmdHint ? 0.3 : 1.2 }} />
              {cmdHint && <Typography variant="caption" color={cmdHint.startsWith('没认出') ? 'error' : 'text.secondary'} component="div" sx={{ mb: 1.2, ml: 0.5 }}>{cmdHint}</Typography>}
            </>
          )}
          {edit && <TextField {...field} label="别名" placeholder="比如 nas、公司服务器" value={f.alias} onChange={set('alias')} />}
          {!adv ? (
            <Box sx={{ display: 'flex', gap: 1.5 }}>
              <TextField {...field} label="IP / 域名" value={addrs[0].host} onChange={setAddr(0, 'host')} />
              <TextField {...field} label="端口" value={addrs[0].port} onChange={setAddr(0, 'port')} sx={{ ...field.sx, width: 110 }} />
            </Box>
          ) : (
            <Box sx={{ mb: 1.2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.8 }}><Typography variant="body2" color="text.secondary">IP 池（从上到下依次尝试）</Typography><InfoTip text="前面连不上才用后面的。把内网地址拖到最上面，就默认走内网。" /></Box>
              {addrs.map((a, i) => (
                <Box key={i} ref={(el: HTMLElement | null) => { rowRefs.current[i] = el }}
                  sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.8, p: 0.4, borderRadius: 2, border: 1, borderColor: over === i ? 'primary.main' : 'transparent', bgcolor: over === i ? 'action.hover' : 'transparent' }}>
                  <Box title="按住拖动调整顺序" onMouseDown={startDrag(i)}
                    sx={{ cursor: 'grab', display: 'flex', color: 'text.disabled', '&:hover': { color: 'text.primary' } }}><DragIndicatorRounded fontSize="small" /></Box>
                  <TextField size="small" fullWidth placeholder="IP / 域名" value={a.host} onChange={setAddr(i, 'host')} sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }} />
                  <TextField size="small" value={a.port} onChange={setAddr(i, 'port')} sx={{ width: 84, flexShrink: 0, '& .MuiOutlinedInput-root': { borderRadius: 2 } }} />
                  <Box sx={{ width: 40, flexShrink: 0, textAlign: 'center' }}>{isPrivate(a.host) ? <Typography variant="caption" sx={{ fontWeight: 700, color: 'success.main' }}>内网</Typography> : i === 0 ? null : null}</Box>
                  <IconButton size="small" disabled={addrs.length <= 1} onClick={() => { setAddrs((l) => l.filter((_, j) => j !== i)); setRes(null) }}><CloseRounded fontSize="small" /></IconButton>
                </Box>
              ))}
              {res?.rows && res.rows.length > 1 && (
                <Box sx={{ mb: 0.8, display: 'flex', flexDirection: 'column', gap: 0.3 }}>
                  {res.rows.map((x: any, i: number) => (
                    <Typography key={i} variant="caption" color={x.ok ? 'success.main' : 'error.main'} sx={{ wordBreak: 'break-all' }}>
                      {x.ok ? '✓' : '✗'} {x.host}:{x.port} · {x.ok ? `${x.via === 'key' ? '密钥' : '密码'}登录 · ${x.ms} ms${x.internal ? ' · 内网' : ''}` : x.error}
                    </Typography>
                  ))}
                </Box>
              )}
              <Button size="small" startIcon={<AddRounded />} onClick={() => setAddrs((l) => [...l, { host: '', port: '22' }])}>添加地址</Button>
            </Box>
          )}
          <TextField {...field} label="用户名" placeholder={'留空则用本机用户名'} value={f.user} onChange={set('user')} />
          <TextField {...field} label="密码" type={show ? 'text' : 'password'} value={f.password} onChange={set('password')} autoComplete="new-password"
            placeholder={edit && host!.has_password ? '已保存，不改就留空' : ''}
            InputProps={{ endAdornment: <InputAdornment position="end"><Button size="small" onClick={() => setShow(!show)}>{show ? '隐藏' : '显示'}</Button></InputAdornment> }} />
          <TextField {...field} label="私钥文件（可选）" placeholder="用密码就不用填" value={f.identity} onChange={set('identity')}
            InputProps={{ endAdornment: <InputAdornment position="end"><Button size="small" onClick={pickKey}>选择</Button></InputAdornment> }} />
          {!adv && <Button size="small" sx={{ alignSelf: 'flex-start', ml: -1, mb: 0.5 }} onClick={() => setAdv(true)}>高级：IP 池（添加备用地址）</Button>}
          {res && <Alert severity={res.ok ? 'success' : 'error'} sx={{ borderRadius: 2, mb: 1 }}>{res.text}</Alert>}
          {err && <Alert severity="error" sx={{ borderRadius: 2, mb: 1 }}>{err}</Alert>}
        </Box>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        {edit && <Button color="error" onClick={del} sx={{ ...rounded, mr: 'auto' }}>删除</Button>}
        <Box sx={{ flex: 1 }} />
        <Button onClick={onClose} sx={rounded} disabled={!!busy}>取消</Button>
        <Button variant="outlined" onClick={test} sx={rounded} disabled={!!busy || filled.length === 0}>{busy === 'test' ? '测试中…' : '测试连接'}</Button>
        <Button variant="contained" onClick={save} sx={rounded} disabled={!!busy || filled.length === 0}>保存</Button>
      </DialogActions>
    </Dialog>
  )
}

// ----------------------------------------------------------------------------------- 文件
let CLIP: { alias: string; dir: string; names: string[]; cut: boolean } | null = null      // 复制/剪切板（应用内，同一台主机里粘贴）
// 撤销栈：每台主机一份（应用运行期间有效）。能撤销：重命名、移动（含剪切粘贴、拖进文件夹）、复制粘贴、新建文件夹。
// 删除：100MB 以内移进对方机器的垃圾目录，可撤销；超过 100MB 的确认后永久删除，不能撤销。
type Undo = { label: string; run: () => Promise<any> }
const UNDO: Record<string, Undo[]> = {}
type PaneResult = (alias: string, ok: boolean, conn: boolean, error?: string, addr?: any) => void

function FilesPane({ alias, active, onResult }: { alias: string; active: boolean; onResult?: PaneResult }) {
  const [path, setPath] = useState('')
  const [pathText, setPathText] = useState('')
  const [ents, setEnts] = useState<any[]>([])
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [last, setLast] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [prog, setProg] = useState<any>(null)
  const [info, setInfo] = useState('')
  const [dest, setDest] = useState('')
  const [mk, setMk] = useState<null | string>(null)
  const [menu, setMenu] = useState<null | { x: number; y: number }>(null)
  const [renaming, setRenaming] = useState<null | { old: string; text: string }>(null)
  const [delAsk, setDelAsk] = useState<string[] | null>(null)
  const [opBusy, setOpBusy] = useState(false)
  const [, setClipVer] = useState(0)
  const [, setUndoVer] = useState(0)
  const [band, setBand] = useState<null | { x0: number; y0: number; x1: number; y1: number }>(null)
  const [drag, setDrag] = useState<null | { names: string[]; x: number; y: number; over: string | null }>(null)
  const box = useRef<HTMLDivElement>(null)
  const pathRef = useRef(''); pathRef.current = path
  const selRef = useRef(sel); selRef.current = sel
  const suppress = useRef(false)

  const ls = async (p: string) => {
    setLoading(true); setErr('')
    const r = await api.ssh_ls(alias, p)
    setLoading(false)
    onResult?.(alias, !!r.ok, !!r.conn, r.error, r.addr ? { ...r.addr, internal: r.internal, via: r.via } : undefined)
    if (!r.ok) return setErr(r.error)
    setPath(r.path); setPathText(r.path); setEnts(r.entries); setSel(new Set()); setLast(null)
  }
  useEffect(() => { ls('') }, [alias])
  useEvent('ssh:progress', (d: any) => setProg(d))
  useEvent('ssh:done', (d: any) => {
    setProg(null)
    if (d.alias !== alias) return
    if (d.ok) { setInfo(`${d.kind === 'up' ? '已上传' : '已下载'} ${d.count} 个文件，用了 ${Math.max(1, Math.round(d.secs))} 秒。`); if (d.kind === 'up') ls(pathRef.current); else setDest(d.dest || '') }
    else setInfo(d.cancelled ? '已取消。' : d.error || '传输失败。')
  })
  const upload = async (paths: string[]) => {
    if (!paths?.length || !pathRef.current) return
    setInfo(''); const r = await api.ssh_upload(alias, paths, pathRef.current)
    if (!r.ok) setInfo(r.error)
  }
  useEvent('files:ssh', (paths: string[]) => { if (active) upload(paths) })
  const pickUp = async () => upload(await api.pick_files('any'))
  const pickUpDir = async () => { const d = await api.pick_folder(); if (d) upload([d]) }
  const selNames = () => ents.filter((e) => sel.has(e.name)).map((e) => e.name)
  const download = async () => {
    const items = ents.filter((e) => sel.has(e.name)).map((e) => ({ path: joinPath(path, e.name), name: e.name, dir: e.dir }))
    if (!items.length) return
    setInfo(''); setDest('')
    const r = await api.ssh_download(alias, items)
    if (!r.ok) setInfo(r.error)
  }
  const doMk = async () => {
    const name = (mk || '').trim(); setMk(null)
    if (!name) return
    const dir = path
    const r = await api.ssh_mkdir(alias, dir, name)
    if (!r.ok) setInfo(r.error); else { pushUndo({ label: `新建文件夹“${name}”`, run: () => api.ssh_rmdir(alias, joinPath(dir, name)) }); ls(path) }
  }

  // 重命名 / 删除 / 复制 / 剪切 / 粘贴 / 拖进文件夹：都是在对方机器上直接做
  const pushUndo = (u: Undo) => { const l = UNDO[alias] || (UNDO[alias] = []); l.push(u); if (l.length > 50) l.shift(); setUndoVer((v) => v + 1) }
  // undoOf(r)：根据操作结果生成撤销动作（没有就不记）
  const op = async (fn: () => Promise<any>, done: (r: any) => string, undoOf?: (r: any) => Undo | null, busyText?: string) => {
    setOpBusy(true); setInfo(busyText || ''); setDest('')
    const r = await fn()
    setOpBusy(false)
    if (!r.ok) { setInfo(r.error || '操作失败。'); if (r.conn) onResult?.(alias, false, true, r.error); else ls(pathRef.current); return }
    const u = undoOf?.(r); if (u) pushUndo(u)
    setInfo(done(r)); await ls(pathRef.current)
  }
  const doUndo = async () => {
    const l = UNDO[alias]; const u = l?.pop()
    if (!u || opBusy) return
    setUndoVer((v) => v + 1)
    setOpBusy(true); setInfo(''); setDest('')
    const r = await u.run()
    setOpBusy(false)
    setInfo(r.ok ? `已撤销：${u.label}` : `撤销没成功：${r.error || ''}`)
    await ls(pathRef.current)
  }
  const doCopy = (cut: boolean) => {
    const n = selNames(); if (!n.length) return
    CLIP = { alias, dir: path, names: n, cut }; setClipVer((v) => v + 1)
    setInfo(`已${cut ? '剪切' : '复制'} ${n.length} 项，到目标文件夹里右键“粘贴”。`)
  }
  const doPaste = () => {
    const c = CLIP; if (!c || !path) return
    if (c.alias !== alias) return setInfo('暂不支持跨主机粘贴，请先下载再上传。')
    const dir = path
    op(() => (c.cut ? api.ssh_mv(alias, c.dir, c.names, path) : api.ssh_cp(alias, c.dir, c.names, path)), (r) => { if (c.cut) { CLIP = null; setClipVer((v) => v + 1) } return `已${c.cut ? '移动' : '复制'} ${r.count ?? c.names.length} 项。` },
      (r) => c.cut
        ? (r.pairs?.length ? { label: `移动 ${r.pairs.length} 项`, run: () => api.ssh_mv_paths(alias, r.pairs.map(([a, b]: string[]) => [b, a])) } : null)
        : (r.created?.length ? { label: `复制 ${r.created.length} 项`, run: () => api.ssh_rm_paths(alias, r.created) } : null))
    void dir
  }
  // 删除：100MB 以内悄悄移进对方的垃圾目录（可撤销）；超过的弹窗确认后永久删除
  const doTrash = async (n: string[]) => {
    if (!n.length || opBusy) return
    setOpBusy(true); setInfo(''); setDest('')
    const r = await api.ssh_trash(alias, path, n)
    setOpBusy(false)
    if (!r.ok) { setInfo(r.error || '操作失败。'); if (r.conn) onResult?.(alias, false, true, r.error); else ls(pathRef.current); return }
    if (r.big) { setDelAsk(n); return }
    if (r.pairs?.length) pushUndo({ label: `删除 ${r.pairs.length} 项`, run: () => api.ssh_restore(alias, r.pairs) })
    setInfo(`已删除 ${r.count ?? n.length} 项。`); await ls(pathRef.current)
  }
  const doDelete = (n: string[]) => { setDelAsk(null); op(() => api.ssh_rm(alias, path, n), (r) => `已删除 ${r.count ?? n.length} 项。`) }
  const doRename = () => {
    const r = renaming; setRenaming(null)
    if (!r || !r.text.trim() || r.text.trim() === r.old) return
    const dir = path, from = r.old, to = r.text.trim()
    op(() => api.ssh_rename(alias, dir, from, to), () => '已重命名。', () => ({ label: `重命名“${from}”`, run: () => api.ssh_rename(alias, dir, to, from) }))
  }
  const moveInto = (n: string[], folder: string) => op(() => api.ssh_mv(alias, path, n, joinPath(path, folder)), (r) => `已把 ${r.count ?? n.length} 项移到“${folder}”里。`,
    (r) => (r.pairs?.length ? { label: `移动 ${r.pairs.length} 项`, run: () => api.ssh_mv_paths(alias, r.pairs.map(([a, b]: string[]) => [b, a])) } : null))
  const askRename = () => { const n = selNames(); if (n.length === 1) setRenaming({ old: n[0], text: n[0] }) }
  // 压缩 / 解压：都在对方机器上做（不经过本机）；解压默认进同名新文件夹，不覆盖任何东西
  const doExtract = (here: boolean) => {
    const n = selNames(); if (!n.length) return
    const dir = path
    op(() => api.ssh_extract(alias, dir, n, here), (r) => (here ? `已解压 ${n.length} 个压缩包到当前文件夹（同名文件已跳过）。` : r.created?.length === 1 ? `已解压到“${r.created[0].split('/').pop()}”。` : `已解压 ${n.length} 个压缩包，每个都在自己的同名文件夹里。`),
      (r) => (r.created?.length ? { label: `解压 ${n.length} 个压缩包`, run: () => api.ssh_rm_paths(alias, r.created) } : null), '正在解压…')
  }
  const doArchive = (kind: 'zip' | 'tgz') => {
    const n = selNames(); if (!n.length) return
    const dir = path
    op(() => api.ssh_archive(alias, dir, n, kind), (r) => `已压缩为“${r.created?.[0]?.split('/').pop()}”。`,
      (r) => (r.created?.length ? { label: '压缩', run: () => api.ssh_rm_paths(alias, r.created) } : null), '正在压缩…')
  }

  const rowClick = (ev: React.MouseEvent, n: string) => {
    if (suppress.current) return
    if (ev.ctrlKey || ev.metaKey) { const s = new Set(sel); s.has(n) ? s.delete(n) : s.add(n); setSel(s) }
    else if (ev.shiftKey && last) {
      const a = ents.findIndex((e) => e.name === last), b = ents.findIndex((e) => e.name === n)
      if (a >= 0 && b >= 0) setSel(new Set(ents.slice(Math.min(a, b), Math.max(a, b) + 1).map((e) => e.name)))
    } else setSel(new Set([n]))
    setLast(n)
  }
  const toggle = (n: string) => { const s = new Set(sel); s.has(n) ? s.delete(n) : s.add(n); setSel(s); setLast(n) }

  // 鼠标左键：在名字上按住拖 = 拖动所选（落在文件夹上就塞进去）；在别处（空白、大小、时间）按住拖 = 框选
  const onDown = (ev: React.MouseEvent) => {
    if (ev.button !== 0 || opBusy || !box.current) return
    const t = ev.target as HTMLElement
    if (t.closest('input,button,.MuiCheckbox-root,.MuiAlert-root')) return
    const cr0 = box.current.getBoundingClientRect()
    if (ev.clientX - cr0.left > box.current.clientWidth) return            // 点在滚动条上
    ev.preventDefault(); box.current.focus()
    const nmEl = t.closest('[data-nm]') as HTMLElement | null
    const x0 = ev.clientX, y0 = ev.clientY
    const additive = ev.ctrlKey || ev.metaKey || ev.shiftKey
    const base = new Set(selRef.current)
    const dragNames = nmEl ? (base.has(nmEl.dataset.nm!) ? [...base] : [nmEl.dataset.nm!]) : []
    let mode: 'none' | 'band' | 'drag' = 'none'
    let overNow: string | null = null
    const move = (e: MouseEvent) => {
      if (mode === 'none') {
        if (Math.abs(e.clientX - x0) + Math.abs(e.clientY - y0) < 5) return
        mode = nmEl ? 'drag' : 'band'
        if (nmEl && !base.has(nmEl.dataset.nm!)) setSel(new Set(dragNames))
      }
      const b = box.current; if (!b) return
      const r = b.getBoundingClientRect()
      if (e.clientY > r.bottom - 22) b.scrollTop += 14; else if (e.clientY < r.top + 22) b.scrollTop -= 14      // 靠边自动滚动
      if (mode === 'band') {
        setBand({ x0, y0, x1: e.clientX, y1: e.clientY })
        const lo = Math.min(y0, e.clientY), hi = Math.max(y0, e.clientY)
        const hit = new Set<string>(additive ? base : [])
        b.querySelectorAll<HTMLElement>('[data-row]').forEach((el) => { const q = el.getBoundingClientRect(); if (q.bottom >= lo && q.top <= hi) hit.add(el.dataset.row!) })
        setSel(hit)
      } else {
        const el = (document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null)?.closest('[data-row]') as HTMLElement | null
        overNow = el && el.dataset.dir === '1' && !dragNames.includes(el.dataset.row!) ? el.dataset.row! : null
        setDrag({ names: dragNames, x: e.clientX, y: e.clientY, over: overNow })
      }
    }
    const up = () => {
      window.removeEventListener('mousemove', move)
      setBand(null); setDrag(null)
      if (mode !== 'none') { suppress.current = true; setTimeout(() => { suppress.current = false }, 0) }
      if (mode === 'drag' && overNow) moveInto(dragNames, overNow)
      else if (mode === 'none' && !nmEl && !additive) { setSel(new Set()); setLast(null) }
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up, { once: true })
  }
  const onCtx = (ev: React.MouseEvent) => {
    ev.preventDefault()
    if (opBusy) return
    const row = ((ev.target as HTMLElement).closest('[data-row]') as HTMLElement | null)?.dataset.row ?? null
    if (row && !sel.has(row)) { setSel(new Set([row])); setLast(row) }
    if (!row) setSel(new Set())
    setMenu({ x: ev.clientX, y: ev.clientY })
  }
  const onKey = (ev: React.KeyboardEvent) => {
    if (opBusy) return
    const c = ev.ctrlKey || ev.metaKey, k = ev.key.toLowerCase()
    if (c && k === 'a') { ev.preventDefault(); setSel(new Set(ents.map((e) => e.name))) }
    else if (c && k === 'c') { ev.preventDefault(); doCopy(false) }
    else if (c && k === 'x') { ev.preventDefault(); doCopy(true) }
    else if (c && k === 'v') { ev.preventDefault(); doPaste() }
    else if (c && k === 'z') { ev.preventDefault(); doUndo() }
    else if (ev.key === 'Delete' && sel.size) { ev.preventDefault(); doTrash(selNames()) }
    else if (ev.key === 'F2') { ev.preventDefault(); askRename() }
    else if (ev.key === 'Escape') setSel(new Set())
  }

  const busy = !!prog || opBusy
  const undoTop = (UNDO[alias] || [])[(UNDO[alias] || []).length - 1]
  const nSel = sel.size
  const one = nSel === 1 ? ents.find((e) => sel.has(e.name)) : null
  const allArc = nSel > 0 && ents.filter((e) => sel.has(e.name)).every((e) => !e.dir && ARC_RE.test(e.name))
  const act = (f: () => void) => () => { setMenu(null); f() }
  const cr = box.current?.getBoundingClientRect()
  const cb = band && cr ? { l: Math.max(cr.left, Math.min(band.x0, band.x1)), t: Math.max(cr.top, Math.min(band.y0, band.y1)), r: Math.min(cr.right, Math.max(band.x0, band.x1)), b: Math.min(cr.bottom, Math.max(band.y0, band.y1)) } : null
  const hint = { ml: 3 }

  return (
    <Box sx={{ display: active ? 'flex' : 'none', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 1 }}>
        <Tooltip title="上一级"><span><IconButton size="small" disabled={!path || path === '/'} onClick={() => ls(parentOf(path))}><ArrowUpwardRounded fontSize="small" /></IconButton></span></Tooltip>
        <Tooltip title="刷新"><IconButton size="small" onClick={() => ls(path)}><RefreshRounded fontSize="small" /></IconButton></Tooltip>
        <TextField size="small" fullWidth value={pathText} onChange={(e) => setPathText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && ls(pathText)}
          sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2, fontFamily: 'Consolas, monospace', fontSize: 13 } }} />
        <Tooltip title="新建文件夹"><IconButton size="small" onClick={() => setMk('')}><CreateNewFolderOutlined fontSize="small" /></IconButton></Tooltip>
        <Tooltip title={undoTop ? `撤销：${undoTop.label}（Ctrl+Z）` : '撤销（Ctrl+Z）'}><span><IconButton size="small" disabled={!undoTop || busy} onClick={doUndo}><UndoRounded fontSize="small" /></IconButton></span></Tooltip>
      </Box>
      {mk !== null && (
        <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
          <TextField size="small" autoFocus placeholder="文件夹名" value={mk} onChange={(e) => setMk(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') doMk(); if (e.key === 'Escape') setMk(null) }} sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }} />
          <Button size="small" variant="contained" sx={rounded} onClick={doMk}>新建</Button><Button size="small" onClick={() => setMk(null)}>取消</Button>
        </Box>
      )}
      <Box ref={box} tabIndex={0} onMouseDown={onDown} onContextMenu={onCtx} onKeyDown={onKey}
        sx={{ flex: 1, minHeight: 0, overflow: 'auto', border: 1, borderColor: 'divider', borderRadius: 2, outline: 'none', userSelect: 'none', position: 'relative' }}>
        {err && <Alert severity="info" sx={{ m: 1, borderRadius: 2 }}>{softMsg(err)}</Alert>}
        {(loading || opBusy) && <LinearProgress />}
        {!err && !loading && ents.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>空文件夹</Typography>}
        {ents.map((e) => {
          const over = drag?.over === e.name
          const cutting = !!CLIP?.cut && CLIP.alias === alias && CLIP.dir === path && CLIP.names.includes(e.name)
          return (
            <Box key={e.name} data-row={e.name} data-dir={e.dir ? '1' : '0'} onDoubleClick={() => e.dir && ls(joinPath(path, e.name))} onClick={(ev) => rowClick(ev, e.name)}
              sx={{ display: 'grid', gridTemplateColumns: '34px 26px minmax(0,1fr) 90px 120px', alignItems: 'center', px: 0.5, py: 0.2, cursor: 'default', bgcolor: over ? 'primary.main' : sel.has(e.name) ? 'action.selected' : 'transparent', color: over ? 'primary.contrastText' : 'inherit', opacity: cutting ? 0.5 : 1, '&:hover': { bgcolor: over ? 'primary.main' : sel.has(e.name) ? 'action.selected' : 'action.hover' } }}>
              <Checkbox size="small" checked={sel.has(e.name)} onClick={(ev) => ev.stopPropagation()} onChange={() => toggle(e.name)} sx={{ p: 0.5 }} />
              <Box data-nm={e.name} sx={{ display: 'flex', alignItems: 'center' }}>{e.dir ? <FolderRounded fontSize="small" color={over ? 'inherit' : 'primary'} /> : <InsertDriveFileOutlined fontSize="small" sx={{ color: over ? 'inherit' : 'text.secondary' }} />}</Box>
              <Box sx={{ minWidth: 0, display: 'flex' }}><Typography data-nm={e.name} noWrap sx={{ fontSize: 13.5, maxWidth: '100%' }}>{e.name}</Typography></Box>
              <Typography variant="caption" color={over ? 'inherit' : 'text.secondary'} sx={{ textAlign: 'right', pr: 1.5 }}>{e.dir ? '' : human(e.size)}</Typography>
              <Typography variant="caption" color={over ? 'inherit' : 'text.secondary'}>{fmtDate(e.mtime)}</Typography>
            </Box>
          )
        })}
      </Box>
      {cb && <Box sx={{ position: 'fixed', left: cb.l, top: cb.t, width: cb.r - cb.l, height: cb.b - cb.t, border: 1, borderColor: 'primary.main', bgcolor: 'rgba(25,118,210,0.14)', pointerEvents: 'none', zIndex: 1300 }} />}
      {drag && <Box sx={{ position: 'fixed', left: drag.x + 14, top: drag.y + 14, px: 1.2, py: 0.4, borderRadius: 1.5, bgcolor: 'primary.main', color: 'primary.contrastText', fontSize: 12.5, fontWeight: 700, pointerEvents: 'none', zIndex: 1400, boxShadow: 3 }}>{drag.names.length === 1 ? drag.names[0] : `${drag.names.length} 项`}{drag.over ? ` → ${drag.over}` : ''}</Box>}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1.2, flexWrap: 'wrap' }}>
        <Button variant="contained" size="small" startIcon={<UploadFileOutlined />} sx={rounded} disabled={busy || !path} onClick={pickUp}>上传文件</Button>
        <Button variant="outlined" size="small" startIcon={<DriveFolderUploadOutlined />} sx={rounded} disabled={busy || !path} onClick={pickUpDir}>上传文件夹</Button>
        <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>拖动框选 · 右键更多操作 · 把文件拖进窗口也能上传到这个目录</Typography>
      </Box>
      {prog && (
        <Box sx={{ mt: 1 }}>
          <LinearProgress variant="determinate" value={prog.total ? Math.min(100, (prog.sent / prog.total) * 100) : 0} sx={{ height: 6, borderRadius: 3 }} />
          <Box sx={{ display: 'flex', alignItems: 'center', mt: 0.5 }}>
            <Typography variant="caption" color="text.secondary" noWrap sx={{ flex: 1 }}>{prog.kind === 'up' ? '上传' : '下载'} {human(prog.sent)} / {human(prog.total)}{prog.speed ? ` · ${human(prog.speed)}/s` : ''}{prog.file ? ` · ${prog.file}` : ''}</Typography>
            <Button size="small" color="error" onClick={() => api.ssh_cancel()}>取消</Button>
          </Box>
        </Box>
      )}
      {info && !prog && <Typography variant="caption" color={info.startsWith('已') && !info.includes('取消') ? 'success.main' : 'text.secondary'} sx={{ mt: 1, userSelect: 'text' }}>{info}{dest && <Button size="small" sx={{ ml: 1, py: 0, minWidth: 0 }} onClick={() => api.open_path(dest)}>打开下载位置</Button>}</Typography>}

      <Menu open={!!menu} onClose={() => setMenu(null)} anchorReference="anchorPosition" anchorPosition={menu ? { top: menu.y, left: menu.x } : undefined}
        slotProps={{ paper: { sx: { borderRadius: 2, minWidth: 200 } } }} onContextMenu={(e) => { e.preventDefault(); setMenu(null) }}>
        {one?.dir && <MenuItem onClick={act(() => ls(joinPath(path, one.name)))}><ListItemIcon><FolderOpenOutlined fontSize="small" /></ListItemIcon><ListItemText>打开</ListItemText></MenuItem>}
        {nSel > 0 && <MenuItem disabled={busy} onClick={act(download)}><ListItemIcon><DownloadOutlined fontSize="small" /></ListItemIcon><ListItemText>下载{nSel > 1 ? `所选（${nSel}）` : ''}</ListItemText></MenuItem>}
        {allArc && <MenuItem disabled={busy} onClick={act(() => doExtract(false))}><ListItemIcon><UnarchiveOutlined fontSize="small" /></ListItemIcon><ListItemText>解压到{nSel === 1 ? `“${arcStem(selNames()[0])}”文件夹` : '各自的文件夹'}</ListItemText></MenuItem>}
        {allArc && <MenuItem disabled={busy} onClick={act(() => doExtract(true))}><ListItemIcon><UnarchiveOutlined fontSize="small" /></ListItemIcon><ListItemText>解压到当前文件夹</ListItemText></MenuItem>}
        {nSel > 0 && <MenuItem disabled={busy} onClick={act(() => doArchive('zip'))}><ListItemIcon><FolderZipOutlined fontSize="small" /></ListItemIcon><ListItemText>压缩为 ZIP</ListItemText></MenuItem>}
        {nSel > 0 && <MenuItem disabled={busy} onClick={act(() => doArchive('tgz'))}><ListItemIcon><FolderZipOutlined fontSize="small" /></ListItemIcon><ListItemText>压缩为 TAR.GZ</ListItemText></MenuItem>}
        {nSel > 0 && <Divider />}
        {nSel > 0 && <MenuItem disabled={busy} onClick={act(() => doCopy(false))}><ListItemIcon><ContentCopyOutlined fontSize="small" /></ListItemIcon><ListItemText>复制</ListItemText><Typography variant="caption" color="text.secondary" sx={hint}>Ctrl+C</Typography></MenuItem>}
        {nSel > 0 && <MenuItem disabled={busy} onClick={act(() => doCopy(true))}><ListItemIcon><ContentCutOutlined fontSize="small" /></ListItemIcon><ListItemText>剪切</ListItemText><Typography variant="caption" color="text.secondary" sx={hint}>Ctrl+X</Typography></MenuItem>}
        <MenuItem disabled={busy || !CLIP || !path} onClick={act(doPaste)}><ListItemIcon><ContentPasteOutlined fontSize="small" /></ListItemIcon><ListItemText>粘贴{CLIP ? `（${CLIP.names.length} 项）` : ''}</ListItemText><Typography variant="caption" color="text.secondary" sx={hint}>Ctrl+V</Typography></MenuItem>
        {nSel === 1 && <MenuItem disabled={busy} onClick={act(askRename)}><ListItemIcon><DriveFileRenameOutline fontSize="small" /></ListItemIcon><ListItemText>重命名</ListItemText><Typography variant="caption" color="text.secondary" sx={hint}>F2</Typography></MenuItem>}
        {nSel > 0 && <MenuItem disabled={busy} onClick={act(() => doTrash(selNames()))} sx={{ color: 'error.main' }}><ListItemIcon><DeleteOutline fontSize="small" color="error" /></ListItemIcon><ListItemText>删除{nSel > 1 ? `（${nSel}）` : ''}</ListItemText><Typography variant="caption" color="text.secondary" sx={hint}>Del</Typography></MenuItem>}
        <Divider />
        <MenuItem disabled={busy || !undoTop} onClick={act(doUndo)}><ListItemIcon><UndoRounded fontSize="small" /></ListItemIcon><ListItemText>撤销{undoTop ? `：${undoTop.label}` : ''}</ListItemText><Typography variant="caption" color="text.secondary" sx={hint}>Ctrl+Z</Typography></MenuItem>
        <MenuItem disabled={!path} onClick={act(() => setMk(''))}><ListItemIcon><CreateNewFolderOutlined fontSize="small" /></ListItemIcon><ListItemText>新建文件夹</ListItemText></MenuItem>
        {nSel === 0 && <MenuItem disabled={busy || !path} onClick={act(pickUp)}><ListItemIcon><UploadFileOutlined fontSize="small" /></ListItemIcon><ListItemText>上传文件</ListItemText></MenuItem>}
        {nSel === 0 && <MenuItem disabled={busy || !path} onClick={act(pickUpDir)}><ListItemIcon><DriveFolderUploadOutlined fontSize="small" /></ListItemIcon><ListItemText>上传文件夹</ListItemText></MenuItem>}
        <MenuItem onClick={act(() => ls(path))}><ListItemIcon><RefreshRounded fontSize="small" /></ListItemIcon><ListItemText>刷新</ListItemText></MenuItem>
      </Menu>
      <Dialog open={!!renaming} onClose={() => setRenaming(null)} PaperProps={{ sx: { borderRadius: 3, width: 400 } }}>
        <DialogTitle sx={{ fontWeight: 700 }}>重命名</DialogTitle>
        <DialogContent><TextField autoFocus fullWidth size="small" sx={{ mt: 0.5, '& .MuiOutlinedInput-root': { borderRadius: 2 } }} value={renaming?.text || ''} onChange={(e) => setRenaming((r) => r && { ...r, text: e.target.value })}
          onFocus={(e) => { const v = e.target.value, i = v.lastIndexOf('.'); e.target.setSelectionRange(0, i > 0 ? i : v.length) }} onKeyDown={(e) => { if (e.key === 'Enter') doRename() }} /></DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={() => setRenaming(null)} sx={rounded}>取消</Button><Button variant="contained" sx={rounded} onClick={doRename}>确定</Button></DialogActions>
      </Dialog>
      <Dialog open={!!delAsk} onClose={() => setDelAsk(null)} PaperProps={{ sx: { borderRadius: 3, width: 420 } }}>
        <DialogTitle sx={{ fontWeight: 700 }}>删除大文件{delAsk && delAsk.length > 1 ? `（${delAsk.length} 项）` : ''}？</DialogTitle>
        <DialogContent><Typography sx={{ lineHeight: 1.8, wordBreak: 'break-all' }}>{delAsk && delAsk.length === 1 ? `“${delAsk[0]}”` : '所选内容'}超过 100MB，删除后<b>无法恢复</b>。</Typography></DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={() => setDelAsk(null)} sx={rounded}>取消</Button><Button color="error" variant="contained" sx={rounded} onClick={() => delAsk && doDelete(delAsk)}>删除</Button></DialogActions>
      </Dialog>
    </Box>
  )
}

// ----------------------------------------------------------------------------------- 内嵌命令行（一台主机可以开多个会话）
// 终端配色：跟着界面主题走（亮色主题用白底，深色主题用深底）
const TERM_THEME = {
  dark: { background: '#1e1f27', foreground: '#e6e6e6', cursor: '#9fc3ff', selectionBackground: '#3b4a6b' },
  light: {
    background: '#ffffff', foreground: '#1f2328', cursor: '#0969da', cursorAccent: '#ffffff', selectionBackground: '#b6d4fe',
    black: '#24292f', red: '#cf222e', green: '#116329', yellow: '#7d4e00', blue: '#0969da', magenta: '#8250df', cyan: '#1b7c83', white: '#6e7781',
    brightBlack: '#57606a', brightRed: '#a40e26', brightGreen: '#1a7f37', brightYellow: '#9a6700', brightBlue: '#218bff', brightMagenta: '#a475f9', brightCyan: '#3192aa', brightWhite: '#8c959f',
  },
}

function TermSession({ alias, visible, onResult }: { alias: string; visible: boolean; onResult?: PaneResult }) {
  const box = useRef<HTMLDivElement>(null)
  const S = useRef<{ term?: Terminal; fit?: FitAddon; id: string | null; buf: { id: string; data: string }[] }>({ id: null, buf: [] })
  const [status, setStatus] = useState<'connecting' | 'on' | 'closed'>('connecting')
  const [msg, setMsg] = useState('')
  const termDark = useTheme().palette.mode === 'dark'
  const darkRef = useRef(termDark)

  const connect = async () => {
    const s = S.current; const term = s.term!
    setStatus('connecting'); setMsg('')
    s.fit?.fit()
    const r = await api.term_open(alias, term.cols, term.rows)
    onResult?.(alias, !!r.ok, !!r.conn, r.error)
    if (!r.ok) { setStatus('closed'); setMsg(r.error || '连接失败'); return }
    s.id = r.id; setStatus('on')
    s.buf.filter((x) => x.id === r.id).forEach((x) => term.write(x.data)); s.buf = []
    term.focus()
  }
  useEffect(() => {
    const term = new Terminal({
      fontFamily: 'Consolas, "Cascadia Mono", "Microsoft YaHei UI", "SimSun", monospace', fontSize: 13.5, cursorBlink: true, scrollback: 5000, allowProposedApi: true,
      theme: TERM_THEME[darkRef.current ? 'dark' : 'light'],
    })
    const fit = new FitAddon(); term.loadAddon(fit); term.open(box.current!)
    S.current.term = term; S.current.fit = fit
    term.onData((d) => { if (S.current.id) api.term_input(S.current.id, d) })
    term.onResize(({ cols, rows }) => { if (S.current.id) api.term_resize(S.current.id, cols, rows) })
    term.attachCustomKeyEventHandler((e) => {      // 选中文字时 Ctrl+C 是复制；Ctrl+Shift+C/V 也可用
      if (e.type === 'keydown' && e.ctrlKey && (e.key === 'c' || e.key === 'C') && (term.hasSelection() || e.shiftKey)) { navigator.clipboard?.writeText(term.getSelection()); return false }
      return true
    })
    const ro = new ResizeObserver(() => { if (box.current && box.current.offsetParent) { try { fit.fit() } catch { /* 隐藏时忽略 */ } } })
    ro.observe(box.current!)
    connect()
    return () => { ro.disconnect(); if (S.current.id) api.term_close(S.current.id); term.dispose() }
  }, [alias])
  useEffect(() => { darkRef.current = termDark; if (S.current.term) S.current.term.options.theme = TERM_THEME[termDark ? 'dark' : 'light'] }, [termDark])      // 切换主题时终端跟着换
  useEffect(() => { if (visible) setTimeout(() => { try { S.current.fit?.fit() } catch { /* */ } S.current.term?.focus() }, 30) }, [visible])

  useEvent('term:data', (d: any) => { const s = S.current; if (s.id === d.id) s.term?.write(d.data); else if (!s.id) s.buf.push(d) })
  useEvent('term:close', (d: any) => {
    const s = S.current
    if (s.id !== d.id) return
    s.id = null; setStatus('closed'); setMsg(d.reason || '')
    s.term?.write('\r\n\x1b[90m[连接已关闭]\x1b[0m\r\n')
  })

  return (
    <Box sx={{ position: 'absolute', inset: 0, display: visible ? 'flex' : 'none', flexDirection: 'column', minHeight: 0 }}>
      <Box sx={{ flex: 1, minHeight: 0, bgcolor: TERM_THEME[termDark ? 'dark' : 'light'].background, borderRadius: 2, p: 1, overflow: 'hidden', position: 'relative' }}>
        <div ref={box} style={{ width: '100%', height: '100%' }} />
        {status === 'connecting' && <Typography variant="caption" sx={{ position: 'absolute', top: 12, left: 16, color: termDark ? '#9aa0ad' : '#6e7781' }}>正在连接…</Typography>}
      </Box>
      {status === 'closed' && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 1 }}>
          <Button size="small" variant="contained" sx={rounded} onClick={connect}>重新连接</Button>
          {msg && <Typography variant="caption" color="text.secondary" sx={{ userSelect: 'text' }}>{softMsg(msg)}</Typography>}
        </Box>
      )}
    </Box>
  )
}

const MAX_SESSIONS = 8
function TermPane({ alias, active, onResult, slot, onEmpty }: { alias: string; active: boolean; onResult?: PaneResult; slot?: HTMLElement | null; onEmpty?: () => void }) {
  const [list, setList] = useState<number[]>([1])
  const [cur, setCur] = useState(1)
  const next = useRef(2)
  const add = () => { if (list.length >= MAX_SESSIONS) return; const k = next.current++; setList((l) => [...l, k]); setCur(k) }
  // 关掉最后一个会话 = 关掉终端并让上层把终端面板收起；再展开时自动开一个新会话
  const close = (k: number) => {
    const i = list.indexOf(k), n = list.filter((x) => x !== k)
    setList(n); if (cur === k && n.length) setCur(n[Math.max(0, i - 1)])
    if (!n.length) onEmpty?.()
  }
  useEffect(() => { if (active && !list.length) { const k = next.current++; setList([k]); setCur(k) } }, [active, list.length])
  const addBtn = <Tooltip title={list.length >= MAX_SESSIONS ? `最多 ${MAX_SESSIONS} 个会话` : '新建会话（再开一个命令行）'}><span><IconButton size="small" disabled={list.length >= MAX_SESSIONS} onClick={add}><AddRounded fontSize="small" /></IconButton></span></Tooltip>
  if (slot !== undefined) {
    // 新布局：“+”放在面板右上角，多个会话缩成右侧一列小图标（只有一个会话时不显示这一列）
    return (
      <Box sx={{ display: active ? 'flex' : 'none', height: '100%', minHeight: 0 }}>
        {slot && createPortal(<>
          {list.length > 1 && <Tooltip title="关闭当前会话"><IconButton size="small" onClick={() => close(cur)}><DeleteOutline fontSize="small" /></IconButton></Tooltip>}
          {addBtn}
        </>, slot)}
        <Box sx={{ flex: 1, minWidth: 0, minHeight: 0, position: 'relative' }}>
          {list.map((k) => <TermSession key={k} alias={alias} visible={active && k === cur} onResult={onResult} />)}
        </Box>
        {list.length > 1 && (
          <Box sx={{ flex: '0 0 32px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0.3, pt: 0.5, overflowY: 'auto' }}>
            {list.map((k) => (
              <Tooltip key={k} title={`会话 ${k}`} placement="left">
                <Box onClick={() => setCur(k)} onAuxClick={(e) => { if (e.button === 1) close(k) }}
                  sx={{ width: 26, height: 26, flexShrink: 0, borderRadius: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: k === cur ? 'primary.main' : 'text.secondary',
                    bgcolor: k === cur ? 'action.selected' : 'transparent', '&:hover': { bgcolor: k === cur ? 'action.selected' : 'action.hover' } }}>
                  <TerminalOutlined sx={{ fontSize: 17 }} />
                </Box>
              </Tooltip>
            ))}
          </Box>
        )}
      </Box>
    )
  }
  return (
    <Box sx={{ display: active ? 'flex' : 'none', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.6, mb: 0.8, overflowX: 'auto', flexShrink: 0 }}>
        {list.map((k) => (
          <Box key={k} onClick={() => setCur(k)} sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.2, pl: 1.3, pr: 0.4, py: 0.3, borderRadius: 1.5, cursor: 'pointer', fontSize: 12.5, whiteSpace: 'nowrap', fontWeight: k === cur ? 700 : 400,
            bgcolor: k === cur ? 'action.selected' : 'action.hover', '&:hover': { bgcolor: 'action.selected' } }}>
            会话 {k}
            <IconButton size="small" aria-label="关闭会话" sx={{ p: 0.2 }} onClick={(e) => { e.stopPropagation(); close(k) }}><CloseRounded sx={{ fontSize: 14 }} /></IconButton>
          </Box>
        ))}
        <Tooltip title={list.length >= MAX_SESSIONS ? `最多 ${MAX_SESSIONS} 个会话` : '新建会话（再开一个命令行）'}><span><IconButton size="small" disabled={list.length >= MAX_SESSIONS} onClick={add}><AddRounded fontSize="small" /></IconButton></span></Tooltip>
      </Box>
      <Box sx={{ flex: 1, minHeight: 0, position: 'relative' }}>
        {list.map((k) => <TermSession key={k} alias={alias} visible={active && k === cur} onResult={onResult} />)}
      </Box>
    </Box>
  )
}

// ----------------------------------------------------------------------------------- 共享本机 SSH
const DURS = [{ l: '30 分钟', s: 1800 }, { l: '2 小时', s: 7200 }, { l: '1 天', s: 86400 }, { l: '7 天', s: 604800 }, { l: '长期', s: 0 }]
const fmtLeft = (sec: number) => { const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), x = sec % 60; return h > 0 ? `${h} 小时 ${m} 分` : m > 0 ? `${m} 分 ${x} 秒` : `${x} 秒` }
const copy = (t: string) => navigator.clipboard?.writeText(t)

function CopyRow({ label, value, mono = true, big = false }: { label: string; value: string; mono?: boolean; big?: boolean }) {
  const [ok, setOk] = useState(false)
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', py: 0.5 }}>
      <Typography variant="body2" color="text.secondary" sx={{ width: 64, flexShrink: 0 }}>{label}</Typography>
      <Typography sx={{ flex: 1, fontFamily: mono ? 'Consolas, monospace' : undefined, fontWeight: 700, fontSize: big ? 17 : 14.5, userSelect: 'text', wordBreak: 'break-all' }}>{value}</Typography>
      <Tooltip title={ok ? '已复制' : '复制'}><IconButton size="small" onClick={() => { copy(value); setOk(true); setTimeout(() => setOk(false), 1200) }}>{ok ? <CheckCircleOutline fontSize="small" color="success" /> : <ContentCopyOutlined fontSize="small" />}</IconButton></Tooltip>
    </Box>
  )
}

// 共享图标右下角的人数角标：有人连着才显示
function PeopleBadge({ n, children }: { n: number; children: React.ReactNode }) {
  return <Badge badgeContent={n} color="success" invisible={!n} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} sx={{ '& .MuiBadge-badge': { minWidth: 15, height: 15, fontSize: 10, padding: '0 3px', right: -3, bottom: -3 } }}>{children}</Badge>
}

function ShareDialog({ open, st, onClose }: { open: boolean; st: any; onClose: () => void }) {
  const [dur, setDur] = useState(1)
  const [warn, setWarn] = useState<0 | 1 | 2>(0)
  const [agree, setAgree] = useState(false)
  const [now, setNow] = useState(Date.now())
  const [err, setErr] = useState('')
  useEffect(() => { if (!open) return; const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [open])
  useEffect(() => { if (!open) { setWarn(0); setAgree(false); setErr('') } }, [open])

  const start = async () => {
    setWarn(0); setAgree(false); setErr('')
    const r = await api.share_start(DURS[dur].s)
    if (!r.ok) setErr(r.error || '开启失败')
  }
  // 命令只有公网这一条：别人用你的码境用户名经 code.zuicat.cn 连进来（局域网不能直连）。公网入口没连上时显示状态，不显示命令。
  const pub = st.public as { host: string; port: number; user: string } | undefined
  const cmd = pub ? `ssh -p ${pub.port} ${pub.user}@${pub.host}` : (st.tunnel_error ? '公网入口没连上' : '正在连接公网入口…')
  const left = st.expires ? Math.max(0, Math.round(st.expires - now / 1000)) : 0

  return (
    <>
      <Dialog open={open} onClose={onClose} PaperProps={{ sx: { borderRadius: 3, width: 520 } }}>
        <DialogTitle sx={{ fontWeight: 700, display: 'flex', alignItems: 'center' }}>共享本机 SSH
          <InfoTip text="开启后别人可用下面的信息 SSH 连上这台电脑；关闭工具箱或到时间自动关闭。" /></DialogTitle>
        <DialogContent>
          {!st.on ? (
            <Box sx={{ pt: 0.5 }}>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>开放多久</Typography>
              <Segment value={dur} options={DURS.map((d) => d.l)} onChange={setDur} />
              {err && <Alert severity="error" sx={{ mt: 1.5, borderRadius: 2 }}>{err}</Alert>}
            </Box>
          ) : (
            <Box>
              <Alert severity="warning" sx={{ borderRadius: 2, mb: 1.5 }}>正在开放：知道下面信息的人，可以用你的账户操作这台电脑。{st.expires ? `还剩 ${fmtLeft(left)}。` : '不会自动关闭，直到你手动关闭或退出工具箱。'}</Alert>
              <CopyRow label="命令" value={cmd} />
              <CopyRow label="密码" value={st.password} big />
              {!pub && st.tunnel_error && (
                <Typography variant="caption" color="warning.main" component="div" sx={{ ml: '64px', mt: 0.3 }}>{st.tunnel_error}（会自动重试）</Typography>
              )}
              <Typography variant="subtitle2" sx={{ mt: 2, mb: 0.5 }}>当前连接</Typography>
              {st.sessions?.length ? groupSessions(st.sessions).map((g) => (
                <Box key={g.key} sx={{ display: 'flex', alignItems: 'center', py: 0.3 }}>
                  <Typography sx={{ flex: 1, fontSize: 14 }}>{g.label} <Typography component="span" variant="caption" color="text.secondary">· {fmtDate(g.since)}</Typography></Typography>
                  <Button size="small" variant="outlined" color="error" sx={{ ...rounded, py: 0, minWidth: 56 }} onClick={() => g.sids.forEach((id: any) => api.share_kick(id))}>踢掉</Button>
                </Box>
              )) : <Typography variant="body2" color="text.secondary">暂无</Typography>}
            </Box>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          {st.on && <Button sx={{ ...rounded, mr: 'auto' }} onClick={() => { if (window.confirm('重置后旧密码作废，所有正在连着的人会立刻断开，需要用新密码重新连接。确定重置吗？')) api.share_reset_password() }}>重置密码</Button>}
          <Button onClick={onClose} sx={rounded}>{st.on ? '收起' : '取消'}</Button>
          {st.on
            ? <Button variant="contained" color="error" sx={rounded} onClick={() => api.share_stop()}>关闭共享</Button>
            : <Button variant="contained" color="error" sx={rounded} onClick={() => (DURS[dur].s === 0 ? setWarn(1) : start())}>开启共享</Button>}
        </DialogActions>
      </Dialog>
      <Dialog open={warn === 1} onClose={() => setWarn(0)} PaperProps={{ sx: { borderRadius: 3, width: 440 } }}>
        <DialogTitle sx={{ fontWeight: 700 }}>长期开放</DialogTitle>
        <DialogContent>
          <Typography sx={{ lineHeight: 1.8 }}>开启后，知道 IP、端口和密码的人，能以当前账户在这台电脑上运行命令、读写文件。</Typography>
          <Typography sx={{ color: 'error.main', fontWeight: 700, mt: 1, lineHeight: 1.8 }}>长期开放不会自动关闭，直到你手动关闭或退出工具箱。</Typography>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={() => setWarn(0)} sx={rounded}>取消</Button><Button color="error" variant="outlined" sx={rounded} onClick={() => { setAgree(false); setWarn(2) }}>继续</Button></DialogActions>
      </Dialog>
      <Dialog open={warn === 2} onClose={() => setWarn(0)} PaperProps={{ sx: { borderRadius: 3, width: 440 } }}>
        <DialogTitle sx={{ fontWeight: 700 }}>再确认一次</DialogTitle>
        <DialogContent>
          <Typography sx={{ color: 'error.main', fontWeight: 700, lineHeight: 1.8 }}>长期暴露在网络上会被持续扫描、猜密码，风险很高。</Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', mt: 1 }}>
            <Checkbox checked={agree} onChange={(_, v) => setAgree(v)} />
            <Typography>我已了解风险，确认长期开启</Typography>
          </Box>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={() => setWarn(0)} sx={rounded}>取消</Button><Button color="error" variant="contained" disabled={!agree} sx={rounded} onClick={start}>确认开启</Button></DialogActions>
      </Dialog>
    </>
  )
}

// ----------------------------------------------------------------------------------- 页面
export default function SshPage({ active, ide }: { active?: boolean; ide?: boolean }) {
  const dark = useTheme().palette.mode === 'dark'
  const [ideHosts, setIdeHosts] = useState<string[]>([])         // 新布局：打开过的主机（各自保留文件树、编辑器、终端）
  const [hosts, setHosts] = useState<Host[]>([])
  const [keyOn, setKeyOn] = useState<string | null>(null)      // 正在配置通用密钥的主机
  const [cfg, setCfg] = useState('')
  const [err, setErr] = useState('')
  const [sel, setSel] = useState('')
  const [tab, setTab] = useState(0)             // 0 文件 · 1 命令行 · 2 GPU 总览
  const { samples: gpuSamples } = useGpu(!!active && (ide || tab === 2))
  const [sysInfo, setSysInfo] = useState<SysInfo | null>(null)     // 当前主机的系统信息（头部名称 + 下面一行的 CPU/内存/硬盘）
  const [termHosts, setTermHosts] = useState<string[]>([])
  const [fileHosts, setFileHosts] = useState<string[]>([])
  const [dlg, setDlg] = useState<null | { host: Host | null }>(null)
  const [vscNote, setVscNote] = useState<Record<string, string>>({})      // 后台自动装 VS Code Server 的进度小字（按主机）
  useEvent('vsc:progress', (e: any) => { if (e.auto) setVscNote((m) => ({ ...m, [e.alias]: `正在后台给服务器装 VS Code Server ${e.pct ? e.pct + '%' : ''}` })) })
  useEvent('vsc:done', (e: any) => { if (e.auto) setVscNote((m) => { const n = { ...m }; delete n[e.alias]; return n }) })
  const [note, setNote] = useState('')
  const [share, setShare] = useState<any>({ on: false })
  const [shareOpen, setShareOpen] = useState(false)
  const people = groupSessions(share.sessions || []).length          // 现在连着的人数（不是连接数）
  type Chk = { st: 'checking' | 'ok' | 'bad'; via?: string; ms?: number; error?: string; internal?: boolean; addr?: { host: string; port: number }; t?: number }
  const [chk, setChk] = useState<Record<string, Chk>>({})
  const running = useRef(false)
  const runId = useRef(0)
  const frozen = useRef<string[] | null>(null)
  const sortedRef = useRef<Host[]>([])
  const [refreshing, setRefreshing] = useState(false)

  // 全量测一遍连通性（并发 4 个）；进入页面、增删改主机、点刷新时都会跑
  const checkAll = async (list: Host[], silent = false) => {
    if (silent && running.current) return           // 后台复测不重叠；手动点刷新则直接接管（旧的那一轮发现被顶替就自己退出）
    const id = ++runId.current
    running.current = true
    if (!silent) { setRefreshing(true); frozen.current = sortedRef.current.map((h) => h.alias) }      // 手动刷新：全部转圈，但列表顺序先冻住，别乱跳
    setChk((cur) => Object.fromEntries(list.map((h) => [h.alias, silent && cur[h.alias] && cur[h.alias].st !== 'checking' ? cur[h.alias] : ({ st: 'checking' } as Chk)])))      // 静默复测保留上次结果，只有手动刷新才全部转圈
    const queue = [...list]
    const worker = async () => {
      for (let h = queue.shift(); h && id === runId.current; h = queue.shift()) {
        const r = await api.ssh_check(h.alias)
        setChk((c) => ({ ...c, [h.alias]: r.ok ? { st: 'ok', via: r.via, ms: r.ms, internal: r.internal, addr: r.addr, t: Date.now() / 1000 } : { st: 'bad', error: r.error, t: Date.now() / 1000 } }))
      }
    }
    await Promise.all([worker(), worker(), worker(), worker()])
    if (id !== runId.current) return                 // 被新的一轮顶替了，收尾交给新的那轮
    running.current = false; setRefreshing(false); frozen.current = null
  }

  // 单台主机配置变了（新增/修改）：马上自动测一次
  const checkOne = async (alias: string) => {
    setChk((c) => ({ ...c, [alias]: { st: 'checking' } }))
    const r = await api.ssh_check(alias)
    setChk((c) => ({ ...c, [alias]: r.ok ? { st: 'ok', via: r.via, ms: r.ms, internal: r.internal, addr: r.addr, t: Date.now() / 1000 } : { st: 'bad', error: r.error, t: Date.now() / 1000 } }))
  }

  const load = async (keep?: string) => {
    const r = await api.ssh_hosts()
    if (!r.ok) return setErr(r.error)
    setErr(''); setHosts(r.hosts); setCfg(r.config)
    // 上次测试的结果是存在文件里的：打开就显示，不用再测；正在测的保持“测试中”
    setChk((cur) => {
      const x: Record<string, Chk> = {}
      for (const h of r.hosts as Host[]) {
        if (cur[h.alias]?.st === 'checking') x[h.alias] = cur[h.alias]
        else if (cur[h.alias]) x[h.alias] = cur[h.alias]
        else { const o = r.status?.[h.alias]; if (o) x[h.alias] = o.ok ? { st: 'ok', via: o.via, ms: o.ms, internal: o.internal, addr: o.addr, t: o.t } : { st: 'bad', error: o.error, t: o.t } }
      }
      return x
    })
    setSel((cur) => { const c = keep ?? cur; return r.hosts.some((h: Host) => h.alias === c) ? c : '' })       // 不再默认选中任何主机；原来选的还在就保留
    return r.hosts as Host[]
  }
  // 文件/命令行连接的结果直接同步到主机状态点：连不上→马上变红；连上了而之前是红的→重测这一台，恢复成绿
  const chkRef = useRef(chk); chkRef.current = chk
  const paneResult: PaneResult = (alias, ok, conn, error, addr) => {
    if (!ok) { if (conn) setChk((c) => ({ ...c, [alias]: { st: 'bad', error, t: Date.now() / 1000 } })); return }
    const cur = chkRef.current[alias]
    if (addr) setChk((c) => ({ ...c, [alias]: { st: 'ok', via: addr.via ?? c[alias]?.via, ms: c[alias]?.ms, internal: !!addr.internal, addr: { host: addr.host, port: addr.port }, t: Date.now() / 1000 } }))      // 文件页连上了就直接标绿，并显示实际在用的地址（内网超时自动走了公网）
    else if (cur?.st !== 'ok' && cur?.st !== 'checking') checkOne(alias)
  }
  const refresh = async () => { const l = await load(); if (l) checkAll(l) }          // 只有点刷新按钮才会全量测试连通性
  const hostsRef = useRef(hosts); hostsRef.current = hosts
  // 进入页面就测一遍；停留期间每 45 秒静默复测一次，状态变了点会自己变色
  useEffect(() => {
    if (!active) return
    load().then((l) => { if (l) checkAll(l, true) })
    const t = setInterval(() => { if (hostsRef.current.length) checkAll(hostsRef.current, true) }, 45000)
    return () => clearInterval(t)
  }, [active])
  useEvent('share:state', (d: any) => setShare(d))
  // 先走公网连上了、内网随后也通了：自动换成内网，状态点和地址跟着刷新
  useEvent('ssh:route', (d: any) => setChk((c) => (c[d.alias]?.st === 'ok' ? { ...c, [d.alias]: { ...c[d.alias], internal: !!d.internal, addr: d.addr, via: d.via ?? c[d.alias].via } } : c)))
  useEffect(() => { api.share_info().then(setShare) }, [])

  const picked = useRef(false)      // 用户自己点过主机之后，就不再自动换选中项
  const openFiles = (a: string) => { if (ide) { picked.current = true; setSel(a); return } picked.current = true; setSel(a); setTab(0); setFileHosts((l) => (l.includes(a) ? l : [...l, a])) }
  const openTerm = (a: string) => { if (ide) { picked.current = true; setSel(a); return } picked.current = true; setSel(a); setTab(1); setTermHosts((l) => (l.includes(a) ? l : [...l, a])) }
  // 用本机的 VS Code（Remote-SSH）打开这台主机；连接和密钥用的就是 ~/.ssh/config 里这台的配置
  const openVscode = async (alias: string) => {
    const r = await api.open_vscode(alias, CUR_DIR[alias] || '')
    setNote(r?.ok ? `已用 VS Code 打开 ${alias}（第一次连接要等它在服务器上准备一会儿）` : `${alias}：${r?.error || '没能打开 VS Code'}`)
  }
  const choose = (a: string) => { if (a === sel) return; picked.current = true; setSel(a); if (ide) return; if (tab === 1) openTerm(a); else if (tab === 0) openFiles(a) }
  const openGpu = () => { picked.current = true; setTab(2) }
  useEffect(() => { if (ide && sel) setIdeHosts((l) => (l.includes(sel) ? l : [...l, sel])) }, [sel, ide])
  useEffect(() => { if (sel && tab === 0) setFileHosts((l) => (l.includes(sel) ? l : [...l, sel])) }, [sel, tab])
  useEffect(() => { if (sel && tab === 1) setTermHosts((l) => (l.includes(sel) ? l : [...l, sel])) }, [sel, tab])

  // 点主机右边的“+密钥”：写入通用公钥、验证、改用通用密钥登录（旧密钥不动）
  const addKey = async (alias: string) => {
    setKeyOn(alias); setNote('')
    const r = await api.ssh_key_one(alias)
    setKeyOn(null)
    setNote(r.ok ? `${alias}：已配置通用密钥，之后用密钥登录。` : `${alias}：配置密钥没成功：${r.error}`)
    await load()
    checkOne(alias)
  }
  const onSaved = (h: Host, n: string) => {
    setNote(n)
    setChk((c) => { const x = { ...c }; delete x[dlg?.host?.alias || '']; delete x[h.alias]; return x })       // 改过的主机状态先作废，保存后马上自动重测这一台
    if (h.alias) { load(h.alias).then(() => { openFiles(h.alias); checkOne(h.alias) }) } else { setFileHosts((l) => l.filter((x) => x !== dlg?.host?.alias)); setTermHosts((l) => l.filter((x) => x !== dlg?.host?.alias)); load() }
  }
  // 只有测通了的排上面，没测/测不通的都在下面；各自按字母
  // 新布局：连得通的在上面，其中按总显存从大到小（没显卡/还没采到的算 0，排最后），再按字母
  const vram = (al: string) => { const s = gpuSamples[al]; return s?.state === 'ok' ? s.gpus.reduce((t, g) => t + g.mem_total, 0) : 0 }
  const sorted = [...hosts].sort((a, b) => frozen.current ? frozen.current.indexOf(a.alias) - frozen.current.indexOf(b.alias) : ((chk[a.alias]?.st === 'ok' ? 0 : 1) - (chk[b.alias]?.st === 'ok' ? 0 : 1)) || (ide ? vram(b.alias) - vram(a.alias) : 0) || a.alias.localeCompare(b.alias, undefined, { sensitivity: 'base' }))
  sortedRef.current = sorted
  const cur = hosts.find((h) => h.alias === sel)

  const hostActions = <Box sx={{ display: 'flex' }}>{ide && <><Tooltip title="共享本机 SSH"><IconButton size="small" onClick={() => setShareOpen(true)}><PeopleBadge n={people}><ShareOutlined fontSize="small" color={share.on ? 'success' : 'inherit'} /></PeopleBadge></IconButton></Tooltip><Tooltip title="添加主机"><IconButton size="small" onClick={() => setDlg({ host: null })}><AddRounded fontSize="small" /></IconButton></Tooltip></>}<Tooltip title="测试连接"><span><IconButton size="small" disabled={refreshing} onClick={refresh}><RefreshRounded fontSize="small" /></IconButton></span></Tooltip></Box>
  const hostBody = (
          <>
            {hosts.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 2 }}>还没有主机</Typography>}
            <Box sx={{ flex: 1, minHeight: 60, overflow: 'auto', mx: -0.5 }}>
              {sorted.map((h) => {
                const c = chk[h.alias]
                return (
                  <Box key={h.alias} onClick={() => choose(h.alias)} onDoubleClick={() => openTerm(h.alias)}
                    sx={ide
                      ? {      // Clash Verge 节点卡片：白底圆角、没有描边；选中=淡蓝底 + 左边 3px 蓝条；悬停变灰
                          py: 1, pl: 1.1, pr: 1.1, mb: 1, mx: 0.5, borderRadius: 2, cursor: 'pointer', borderLeftWidth: 3, borderLeftStyle: 'solid', borderLeftColor: sel === h.alias ? 'primary.main' : 'transparent',
                          bgcolor: (th: any) => { const d = th.palette.mode === 'dark'; return sel === h.alias ? alpha(th.palette.primary.main, d ? 0.10 : 0.045) : d ? '#282a36' : '#ffffff' },
                          transition: 'background-color .15s',
                          '&:hover': { bgcolor: (th: any) => { const d = th.palette.mode === 'dark'; return sel === h.alias ? alpha(th.palette.primary.main, d ? 0.14 : 0.075) : d ? '#33364a' : '#eeeeee' } },
                        }
                      : { py: 0.9, px: 0.8, borderRadius: 1.5, cursor: 'pointer', bgcolor: sel === h.alias ? 'action.selected' : 'transparent', '&:hover': { bgcolor: sel === h.alias ? 'action.selected' : 'action.hover' } }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Tooltip title={!c ? '还没测试，点右上角刷新' : c.st === 'checking' ? '正在测试连通性…' : `${c.st === 'ok' ? `已连接 · ${c.internal ? '内网' : '公网'} ${c.addr?.host || ''} · ${c.via === 'key' ? '密钥登录' : '密码登录'}` : `当前未连接（可能不在线或不在同一网络，不影响使用）。${soft(c.error)}`}${c.t ? `（上次测试 ${new Date(c.t * 1000).toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}）` : ''}`}>
                      <Box sx={{ width: 9, height: 9, borderRadius: '50%', flexShrink: 0, mr: 0.8, bgcolor: c?.st === 'ok' ? 'success.main' : 'text.disabled', opacity: c?.st === 'bad' ? 0.55 : 1, animation: c?.st === 'checking' ? 'pulse 1s ease-in-out infinite' : 'none', '@keyframes pulse': { '0%,100%': { opacity: 0.35 }, '50%': { opacity: 1 } } }} />
                    </Tooltip>
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.8 }}>
                        <Typography noWrap sx={{ fontWeight: 700, fontSize: ide ? 15 : 14 }}>{h.alias}</Typography>
                        {c?.st === 'ok' && c.via === 'key' && h.common_key && (
                          <Tooltip title="已配置密钥免密登录">
                            <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', px: 0.7, borderRadius: 1, color: 'success.main', bgcolor: 'action.hover', lineHeight: 1.6, flexShrink: 0, cursor: 'default' }}>
                              <VpnKeyOutlined sx={{ fontSize: 11, mr: 0.3 }} /><Box component="span" sx={{ fontSize: 11, fontWeight: 700 }}>密钥</Box>
                            </Box>
                          </Tooltip>
                        )}
                        {c?.st === 'ok' && c.internal && (
                          <Tooltip title="内网直连，速度更快">
                            <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.2, px: 0.7, borderRadius: 1, fontSize: 11, fontWeight: 700, color: 'primary.main', bgcolor: 'action.hover', lineHeight: 1.6, flexShrink: 0, cursor: 'default' }}>
                              <BoltRounded sx={{ fontSize: 13 }} />
                            </Box>
                          </Tooltip>
                        )}
                      </Box>
                      {ide
                        ? null
                        : tab === 2
                          ? <GpuMini sample={gpuSamples[h.alias]} fallback={c?.st === 'ok' ? '等待采样…' : '未连接'} />
                          : <Typography noWrap variant="caption" color="text.secondary">{c?.st === 'bad' ? '未连接' : target(c?.st === 'ok' && c.addr ? { ...h, host: c.addr.host, port: c.addr.port } : h)}</Typography>}
                    </Box>
                    {c?.st === 'ok' && (!h.common_key || c.via === 'password') && (
                      <Tooltip title={keyOn === h.alias ? '正在配置通用密钥…' : '配置通用密钥并改用它登录（旧密钥不动）'}>
                        <span><IconButton size="small" disabled={!!keyOn} onClick={(e) => { e.stopPropagation(); addKey(h.alias) }} sx={{ position: 'relative' }}>
                          {keyOn === h.alias ? <CircularProgress size={16} /> : <><VpnKeyOutlined fontSize="small" /><AddRounded sx={{ position: 'absolute', right: 1, top: 1, fontSize: 11, bgcolor: 'background.paper', borderRadius: '50%', color: 'primary.main' }} /></>}
                        </IconButton></span>
                      </Tooltip>
                    )}
                    {!ide && <Tooltip title="打开命令行"><IconButton size="small" onClick={(e) => { e.stopPropagation(); openTerm(h.alias) }}><TerminalOutlined fontSize="small" /></IconButton></Tooltip>}
                    <Tooltip title="编辑"><IconButton size="small" onClick={(e) => { e.stopPropagation(); setDlg({ host: h }) }}><EditOutlined fontSize="small" /></IconButton></Tooltip>
                    </Box>
                    {ide && c?.st === 'ok' && <Box sx={{ pl: 2.2, pr: 0.3 }}><GpuBars sample={gpuSamples[h.alias]} fallback="等待采样…" /></Box>}
                  </Box>
                )
              })}
            </Box>
          </>
  )
  const hostCard = ide ? (
    // 新布局：不套卡片，标题行 + 列表直接放在左栏里（标题行和右边的主机头同高）
    <Box sx={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', px: 1, height: 50, flex: '0 0 auto' }}>
        <Typography sx={{ fontWeight: 700, fontSize: 14.5, flex: 1 }}>主机</Typography>
        {hostActions}
      </Box>
      {hostBody}
    </Box>
  ) : (
    <Box sx={{ flex: 1, minHeight: 0 }}><EnhancedCard title="主机" icon={<DnsOutlined />} minHeight={120} action={hostActions}>{hostBody}</EnhancedCard></Box>
  )
  const dialogs = (
    <>
      <HostDialog open={!!dlg} host={dlg?.host || null} onClose={() => setDlg(null)} onSaved={onSaved} />
      <ShareDialog open={shareOpen} st={share} onClose={() => setShareOpen(false)} />
    </>
  )
  if (ide) {
    const addrOf = (h: Host) => target(chk[h.alias]?.st === 'ok' && chk[h.alias].addr ? { ...h, host: chk[h.alias].addr!.host, port: chk[h.alias].addr!.port } : h)
    return (
      <Box sx={{ display: 'flex', height: '100%', minHeight: 0 }}>
        <Box sx={{ width: 244, flexShrink: 0, minHeight: 0, p: 0.8, display: 'flex', flexDirection: 'column' }}>{hostCard}</Box>
        <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', borderLeft: 1, borderColor: 'divider' }}>
          {err && <Alert severity="error" sx={{ mb: 1, borderRadius: 2 }}>{err}</Alert>}
          {!cur ? <Typography color="text.secondary" sx={{ textAlign: 'center', pt: 10 }}>{hosts.length ? '从左边选一台主机开始' : '添加一个主机开始'}</Typography> : (
            <>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.5, height: 50, flex: '0 0 auto', borderBottom: 1, borderColor: 'divider' }}>
                <Typography sx={{ fontWeight: 700, fontSize: 14.5 }}>{cur.alias}</Typography>
                <SysInfoBadge info={sysInfo} addr={addrOf(cur)} />
                {note && <Typography variant="caption" color="text.secondary" noWrap sx={{ minWidth: 0 }}>· {note}</Typography>}
                {vscNote[cur.alias] && <Typography variant="caption" color="text.disabled" noWrap sx={{ minWidth: 0 }}>· {vscNote[cur.alias]}</Typography>}
                <Box sx={{ flex: 1, minWidth: 8 }} />
                <SysInfoBar alias={cur.alias} connected={chk[cur.alias]?.st === 'ok'} info={sysInfo} setInfo={setSysInfo} hidden />
                <Tooltip title="用本机的 VS Code（Remote-SSH）打开这台主机"><span>
                  <Button size="small" color="inherit" startIcon={<VsCodeIcon />} sx={{ ...rounded, flexShrink: 0, whiteSpace: 'nowrap', minWidth: 'max-content', fontWeight: 600, px: 1.2, textTransform: 'none' }} disabled={chk[cur.alias]?.st === 'checking'} onClick={() => openVscode(cur.alias)}>在 VSCode 打开</Button>
                </span></Tooltip>
                <Tooltip title="在系统终端里打开"><IconButton size="small" onClick={() => api.open_terminal(cur.alias, CUR_DIR[cur.alias] || '')}><TerminalOutlined fontSize="small" /></IconButton></Tooltip>
              </Box>
              <Box sx={{ flex: 1, minHeight: 0, position: 'relative', overflow: 'hidden' }}>
                {ideHosts.filter((a) => hosts.some((h) => h.alias === a)).map((a) => (
                  <IdePane key={a} alias={a} active={!!active && a === sel} dark={dark} info={a === sel ? sysInfo : null}
                    renderTerm={(v, collapse) => <TermPane alias={a} active={v} onResult={paneResult} onEmpty={collapse} />}
                    onResult={(al, ok, conn, e) => paneResult(al, ok, conn, e)} />
                ))}
              </Box>
            </>
          )}
        </Box>
        {dialogs}
      </Box>
    )
  }
  const title = <Box sx={{ display: 'flex', alignItems: 'center' }}>SSH管理</Box>
  return (
    <BasePage contentStyle={{ height: '100%' }} title={title} info="主机列表和 ~/.ssh/config 同步；传文件、开命令行都是两端直连，不经过中转。"
      header={<Box sx={{ display: 'flex', gap: 1 }}>
        <Button variant="outlined" size="small" startIcon={<PeopleBadge n={people}><ShareOutlined /></PeopleBadge>} sx={rounded} onClick={() => setShareOpen(true)}>
          共享本机{share.on && <Box component="span" sx={{ ml: 0.8, width: 8, height: 8, borderRadius: '50%', bgcolor: 'success.main', display: 'inline-block' }} />}
        </Button>
        <Button variant="contained" size="small" startIcon={<AddRounded />} sx={rounded} onClick={() => setDlg({ host: null })}>添加主机</Button>
      </Box>}>
      {err && <Alert severity="error" sx={{ mb: 1.5, borderRadius: 2 }}>{err}</Alert>}
      <Box sx={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 1.5, alignItems: 'start', height: '100%', minHeight: 460 }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, minHeight: 0, height: '100%' }}>
          {hostCard}
        </Box>
        <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
          {!cur ? (
            <Typography color="text.secondary" sx={{ textAlign: 'center', pt: 10 }}>{hosts.length ? '从左边选一台主机开始' : '添加一个主机开始'}</Typography>
          ) : (
            <>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                <Tabs value={tab} onChange={(_, v) => (v === 2 ? openGpu() : v === 1 ? openTerm(cur.alias) : openFiles(cur.alias))} sx={{ minHeight: 36, '& .MuiTab-root': { minHeight: 36, fontWeight: 700, py: 0 } }}>
                  <Tab label="文件" /><Tab label="命令行" /><Tab label="GPU 总览" />
                </Tabs>
                {tab !== 2 && <>
                  <Tooltip title={`全部地址（同时尝试，哪个先通先用哪个；排在前面的连通后自动换过去）：${(cur.addrs?.length ? cur.addrs : [{ host: cur.host, port: cur.port }]).map((a) => a.host + (a.port !== 22 ? ':' + a.port : '')).join('  →  ')}`}><Typography variant="caption" color="text.secondary" sx={{ ml: 'auto', mr: 1 }}>{cur.alias} · {target(chk[cur.alias]?.st === 'ok' && chk[cur.alias].addr ? { ...cur, host: chk[cur.alias].addr!.host, port: chk[cur.alias].addr!.port } : cur)}</Typography></Tooltip>
                  <Tooltip title="在系统终端里打开"><IconButton size="small" onClick={() => api.open_terminal(cur.alias, CUR_DIR[cur.alias] || '')}><TerminalOutlined fontSize="small" /></IconButton></Tooltip>
                </>}
              </Box>
              <Box sx={{ flex: 1, minHeight: 0, position: 'relative' }}>
                <Box sx={{ display: tab === 2 ? 'block' : 'none', position: 'absolute', inset: 0 }}>
                  <GpuBoard aliases={sorted.map((h) => h.alias)} connected={Object.fromEntries(hosts.map((h) => [h.alias, chk[h.alias]?.st === 'ok']))} samples={gpuSamples}
                    sel={sel} onPick={(a) => { picked.current = true; setSel(a) }} active={!!active && tab === 2} />
                </Box>
                {fileHosts.filter((a) => hosts.some((h) => h.alias === a)).map((a) => <Box key={a} sx={{ display: a === sel && tab === 0 ? 'block' : 'none', height: '100%' }}><FilesPane alias={a} active={a === sel && tab === 0} onResult={paneResult} /></Box>)}
                {termHosts.filter((a) => hosts.some((h) => h.alias === a)).map((a) => <Box key={a} sx={{ display: a === sel && tab === 1 ? 'block' : 'none', position: 'absolute', inset: 0 }}><TermPane alias={a} active={a === sel && tab === 1} onResult={paneResult} /></Box>)}
              </Box>
            </>
          )}
          {note && <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>{note}</Typography>}
          {cur && vscNote[cur.alias] && <Typography variant="caption" color="text.disabled" sx={{ mt: 0.5, display: 'block' }}>{vscNote[cur.alias]}</Typography>}
        </Box>
      </Box>
      {dialogs}
    </BasePage>
  )
}
