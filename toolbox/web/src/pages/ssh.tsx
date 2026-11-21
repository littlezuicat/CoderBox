import AddRounded from '@mui/icons-material/AddRounded'
import BoltRounded from '@mui/icons-material/BoltRounded'
import CloseRounded from '@mui/icons-material/CloseRounded'
import DragIndicatorRounded from '@mui/icons-material/DragIndicatorRounded'
import ArrowUpwardRounded from '@mui/icons-material/ArrowUpwardRounded'
import CheckCircleOutline from '@mui/icons-material/CheckCircleOutline'
import CreateNewFolderOutlined from '@mui/icons-material/CreateNewFolderOutlined'
import DownloadOutlined from '@mui/icons-material/DownloadOutlined'
import DriveFolderUploadOutlined from '@mui/icons-material/DriveFolderUploadOutlined'
import EditOutlined from '@mui/icons-material/EditOutlined'
import ErrorOutline from '@mui/icons-material/ErrorOutline'
import FolderRounded from '@mui/icons-material/FolderRounded'
import InsertDriveFileOutlined from '@mui/icons-material/InsertDriveFileOutlined'
import RefreshRounded from '@mui/icons-material/RefreshRounded'
import TerminalOutlined from '@mui/icons-material/TerminalOutlined'
import UploadFileOutlined from '@mui/icons-material/UploadFileOutlined'
import VpnKeyOutlined from '@mui/icons-material/VpnKeyOutlined'
import DnsOutlined from '@mui/icons-material/DnsOutlined'
import ContentCopyOutlined from '@mui/icons-material/ContentCopyOutlined'
import ShareOutlined from '@mui/icons-material/ShareOutlined'
import { Alert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, InputAdornment, LinearProgress, Tab, Tabs, TextField, Tooltip, Typography } from '@mui/material'
import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'
import { BasePage } from '../components/base-page'
import { Switch } from '../components/base-switch'
import { InfoTip, rounded, Row, Segment } from '../components/common'
import { EnhancedCard } from '../components/enhanced-card'
import { human, useEvent } from '../hooks'

type Addr = { host: string; port: number; internal?: boolean | null }
type Host = { alias: string; host: string; user: string; port: number; identity: string; has_password: boolean; managed: boolean; addrs?: Addr[] }
const isPrivate = (h: string) => /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h.trim())
const field = { size: 'small' as const, fullWidth: true, sx: { mb: 1.2, '& .MuiOutlinedInput-root': { borderRadius: 2 } } }
const fmtDate = (t: number) => (t ? new Date(t * 1000).toLocaleString('zh-CN', { hour12: false, year: '2-digit', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '')
const parentOf = (p: string) => { const s = p.replace(/\/+$/, ''); const i = s.lastIndexOf('/'); return i <= 0 ? '/' : s.slice(0, i) }
const joinPath = (a: string, b: string) => (a.endsWith('/') ? a + b : a + '/' + b)
const target = (h: Host) => `${h.user ? h.user + '@' : ''}${h.host}${h.port !== 22 ? ':' + h.port : ''}`

// ----------------------------------------------------------------------------------- 添加 / 编辑主机
function HostDialog({ open, host, onClose, onSaved, onKeys }: { open: boolean; host: Host | null; onClose: () => void; onSaved: (h: Host, note: string) => void; onKeys: () => void }) {
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

  useEffect(() => {
    if (!open) return
    setF(host ? { alias: host.alias, user: host.user, password: '', identity: host.identity } : { alias: '', user: '', password: '', identity: '' })
    const list = host ? (host.addrs?.length ? host.addrs : [{ host: host.host, port: host.port }]) : [{ host: '', port: 22 }]
    setAddrs(list.map((a) => ({ host: a.host, port: String(a.port) }))); setAdv(list.length > 1)
    setRes(null); setErr(''); setShow(false)
  }, [open, host])
  const set = (k: string) => (e: any) => { setF({ ...f, [k]: e.target.value }); setRes(null) }
  const setAddr = (i: number, k: 'host' | 'port') => (e: any) => { setAddrs((l) => l.map((a, j) => (j === i ? { ...a, [k]: e.target.value } : a))); setRes(null) }
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
  const payload = () => ({ ...f, addrs: filled.map((a) => ({ host: a.host.trim(), port: Number(a.port) || 22 })), old_alias: host?.alias })

  const test = async () => {
    setBusy('test'); setErr(''); setRes(null)
    const r = await api.ssh_test(payload())
    setBusy('')
    const rows: any[] = r.rows || []
    setRes(r.ok
      ? { ok: true, via: r.via, rows, text: `连接成功（${r.via === 'key' ? '密钥' : '密码'}登录${r.addr && filled.length > 1 ? ' · 走 ' + r.addr.host + (r.internal ? '（内网）' : '') : ''}${r.os ? ' · ' + r.os : ''}）` }
      : { ok: false, rows, text: rows.length > 1 ? '所有地址都没连上，看每一行右边的原因。' : r.error })
  }
  const save = async (thenKeys = false) => {
    setBusy('save'); setErr('')
    const r = await api.ssh_save(payload(), host?.alias)
    setBusy('')
    if (!r.ok) return setErr(r.error)
    onSaved(r.host, r.note || '')
    if (thenKeys) onKeys()
    onClose()
  }
  const del = async () => { await api.ssh_delete(host!.alias); onSaved({ ...host!, alias: '' }, '已删除。'); onClose() }
  const pickKey = async () => { const r = await api.pick_files('any'); if (r?.length) { setF({ ...f, identity: r[0] }); setRes(null) } }

  return (
    <Dialog open={open} onClose={() => !busy && onClose()} PaperProps={{ sx: { borderRadius: 3, width: 460 } }}>
      <DialogTitle sx={{ fontWeight: 700 }}>{edit ? '编辑主机' : '添加主机'}</DialogTitle>
      <DialogContent>
        <Box sx={{ pt: 1 }}>
          <TextField {...field} label="别名" placeholder="比如 nas、公司服务器" value={f.alias} onChange={set('alias')} autoFocus={!edit} />
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
          {res?.ok && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
              <Button variant="outlined" startIcon={<VpnKeyOutlined />} sx={rounded} disabled={!!busy} onClick={() => save(true)}>保存并一键创建密钥</Button>
              <InfoTip text="生成一对通用密钥并配给所有已保存的主机，之后不用再输密码。" />
            </Box>
          )}
        </Box>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        {edit && <Button color="error" onClick={del} sx={{ ...rounded, mr: 'auto' }}>删除</Button>}
        <Box sx={{ flex: 1 }} />
        <Button onClick={onClose} sx={rounded} disabled={!!busy}>取消</Button>
        <Button variant="outlined" onClick={test} sx={rounded} disabled={!!busy || filled.length === 0}>{busy === 'test' ? '测试中…' : '测试连接'}</Button>
        <Button variant="contained" onClick={() => save(false)} sx={rounded} disabled={!!busy || !f.alias.trim() || filled.length === 0}>保存</Button>
      </DialogActions>
    </Dialog>
  )
}

// ----------------------------------------------------------------------------------- 密钥结果
function KeyResult({ r, onClose }: { r: any; onClose: () => void }) {
  return (
    <Dialog open={!!r} onClose={onClose} PaperProps={{ sx: { borderRadius: 3, width: 460 } }}>
      <DialogTitle sx={{ fontWeight: 700 }}>SSH 密钥配置结果</DialogTitle>
      <DialogContent>
        {r?.error && <Alert severity="error" sx={{ borderRadius: 2 }}>{r.error}</Alert>}
        {r?.results?.length === 0 && <Typography color="text.secondary">还没有主机，先添加主机再配置。</Typography>}
        {r?.results?.map((x: any) => (
          <Box key={x.alias} sx={{ display: 'flex', gap: 1, py: 0.7, alignItems: 'flex-start' }}>
            {x.ok ? <CheckCircleOutline fontSize="small" color="success" /> : <ErrorOutline fontSize="small" color="error" />}
            <Box><Typography sx={{ fontWeight: 600 }}>{x.alias}</Typography>{!x.ok && <Typography variant="caption" color="error.main">{x.error}</Typography>}</Box>
          </Box>
        ))}
        {r?.key?.exists && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5, userSelect: 'text', wordBreak: 'break-all' }}>通用密钥：{r.key.path}（及 .pub）</Typography>}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}><Button variant="contained" onClick={onClose} sx={rounded}>好</Button></DialogActions>
    </Dialog>
  )
}

// ----------------------------------------------------------------------------------- 文件
function FilesPane({ alias, active }: { alias: string; active: boolean }) {
  const [path, setPath] = useState('')
  const [pathText, setPathText] = useState('')
  const [ents, setEnts] = useState<any[]>([])
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [prog, setProg] = useState<any>(null)
  const [info, setInfo] = useState('')
  const [dest, setDest] = useState('')
  const [mk, setMk] = useState<null | string>(null)
  const pathRef = useRef(''); pathRef.current = path

  const ls = async (p: string) => {
    setLoading(true); setErr('')
    const r = await api.ssh_ls(alias, p)
    setLoading(false)
    if (!r.ok) return setErr(r.error)
    setPath(r.path); setPathText(r.path); setEnts(r.entries); setSel(new Set())
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
    const r = await api.ssh_mkdir(alias, path, name)
    if (!r.ok) setInfo(r.error); else ls(path)
  }
  const toggle = (n: string) => { const s = new Set(sel); s.has(n) ? s.delete(n) : s.add(n); setSel(s) }
  const busy = !!prog

  return (
    <Box sx={{ display: active ? 'flex' : 'none', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 1 }}>
        <Tooltip title="上一级"><span><IconButton size="small" disabled={!path || path === '/'} onClick={() => ls(parentOf(path))}><ArrowUpwardRounded fontSize="small" /></IconButton></span></Tooltip>
        <Tooltip title="刷新"><IconButton size="small" onClick={() => ls(path)}><RefreshRounded fontSize="small" /></IconButton></Tooltip>
        <TextField size="small" fullWidth value={pathText} onChange={(e) => setPathText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && ls(pathText)}
          sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2, fontFamily: 'Consolas, monospace', fontSize: 13 } }} />
        <Tooltip title="新建文件夹"><IconButton size="small" onClick={() => setMk('')}><CreateNewFolderOutlined fontSize="small" /></IconButton></Tooltip>
      </Box>
      {mk !== null && (
        <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
          <TextField size="small" autoFocus placeholder="文件夹名" value={mk} onChange={(e) => setMk(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') doMk(); if (e.key === 'Escape') setMk(null) }} sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 } }} />
          <Button size="small" variant="contained" sx={rounded} onClick={doMk}>新建</Button><Button size="small" onClick={() => setMk(null)}>取消</Button>
        </Box>
      )}
      <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto', border: 1, borderColor: 'divider', borderRadius: 2 }}>
        {err && <Alert severity="error" sx={{ m: 1, borderRadius: 2 }}>{err}</Alert>}
        {loading && <LinearProgress />}
        {!err && !loading && ents.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>空文件夹</Typography>}
        {ents.map((e) => (
          <Box key={e.name} onDoubleClick={() => e.dir && ls(joinPath(path, e.name))} onClick={() => toggle(e.name)}
            sx={{ display: 'grid', gridTemplateColumns: '34px 26px 1fr 90px 120px', alignItems: 'center', px: 0.5, py: 0.2, cursor: 'default', bgcolor: sel.has(e.name) ? 'action.selected' : 'transparent', '&:hover': { bgcolor: 'action.hover' }, userSelect: 'none' }}>
            <Checkbox size="small" checked={sel.has(e.name)} onClick={(ev) => ev.stopPropagation()} onChange={() => toggle(e.name)} sx={{ p: 0.5 }} />
            {e.dir ? <FolderRounded fontSize="small" color="primary" /> : <InsertDriveFileOutlined fontSize="small" sx={{ color: 'text.secondary' }} />}
            <Typography noWrap sx={{ fontSize: 13.5 }}>{e.name}</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ textAlign: 'right', pr: 1.5 }}>{e.dir ? '' : human(e.size)}</Typography>
            <Typography variant="caption" color="text.secondary">{fmtDate(e.mtime)}</Typography>
          </Box>
        ))}
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1.2, flexWrap: 'wrap' }}>
        <Button variant="contained" size="small" startIcon={<UploadFileOutlined />} sx={rounded} disabled={busy || !path} onClick={pickUp}>上传文件</Button>
        <Button variant="outlined" size="small" startIcon={<DriveFolderUploadOutlined />} sx={rounded} disabled={busy || !path} onClick={pickUpDir}>上传文件夹</Button>
        <Button variant="outlined" size="small" startIcon={<DownloadOutlined />} sx={rounded} disabled={busy || sel.size === 0} onClick={download}>下载所选{sel.size ? `（${sel.size}）` : ''}</Button>
        <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>把文件拖进窗口也能上传到这个目录</Typography>
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
    </Box>
  )
}

// ----------------------------------------------------------------------------------- 内嵌命令行
function TermPane({ alias, active }: { alias: string; active: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  const S = useRef<{ term?: Terminal; fit?: FitAddon; id: string | null; buf: { id: string; data: string }[] }>({ id: null, buf: [] })
  const [status, setStatus] = useState<'connecting' | 'on' | 'closed'>('connecting')
  const [msg, setMsg] = useState('')

  const connect = async () => {
    const s = S.current; const term = s.term!
    setStatus('connecting'); setMsg('')
    s.fit?.fit()
    const r = await api.term_open(alias, term.cols, term.rows)
    if (!r.ok) { setStatus('closed'); setMsg(r.error || '连接失败'); return }
    s.id = r.id; setStatus('on')
    s.buf.filter((x) => x.id === r.id).forEach((x) => term.write(x.data)); s.buf = []
    term.focus()
  }
  useEffect(() => {
    const term = new Terminal({
      fontFamily: 'Consolas, "Cascadia Mono", "Microsoft YaHei UI", monospace', fontSize: 13.5, cursorBlink: true, scrollback: 5000, allowProposedApi: true,
      theme: { background: '#1e1f27', foreground: '#e6e6e6', cursor: '#9fc3ff', selectionBackground: '#3b4a6b' },
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
  useEffect(() => { if (active) setTimeout(() => { try { S.current.fit?.fit() } catch { /* */ } S.current.term?.focus() }, 30) }, [active])

  useEvent('term:data', (d: any) => { const s = S.current; if (s.id === d.id) s.term?.write(d.data); else if (!s.id) s.buf.push(d) })
  useEvent('term:close', (d: any) => {
    const s = S.current
    if (s.id !== d.id) return
    s.id = null; setStatus('closed'); setMsg(d.reason || '')
    s.term?.write('\r\n\x1b[90m[连接已关闭]\x1b[0m\r\n')
  })

  return (
    <Box sx={{ display: active ? 'flex' : 'none', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <Box sx={{ flex: 1, minHeight: 0, bgcolor: '#1e1f27', borderRadius: 2, p: 1, overflow: 'hidden', position: 'relative' }}>
        <div ref={box} style={{ width: '100%', height: '100%' }} />
        {status === 'connecting' && <Typography variant="caption" sx={{ position: 'absolute', top: 12, left: 16, color: '#9aa0ad' }}>正在连接…</Typography>}
      </Box>
      {status === 'closed' && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 1 }}>
          <Button size="small" variant="contained" sx={rounded} onClick={connect}>重新连接</Button>
          {msg && <Typography variant="caption" color="error.main" sx={{ userSelect: 'text' }}>{msg}</Typography>}
        </Box>
      )}
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

function ShareDialog({ open, st, onClose }: { open: boolean; st: any; onClose: () => void }) {
  const [dur, setDur] = useState(1)
  const [warn, setWarn] = useState<0 | 1 | 2>(0)
  const [agree, setAgree] = useState(false)
  const [now, setNow] = useState(Date.now())
  const [err, setErr] = useState('')
  const [ipIdx, setIpIdx] = useState(0)
  useEffect(() => { if (!open) return; const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [open])
  useEffect(() => { if (!open) { setWarn(0); setAgree(false); setErr('') } }, [open])

  const start = async () => {
    setWarn(0); setAgree(false); setErr('')
    const r = await api.share_start(DURS[dur].s)
    if (!r.ok) setErr(r.error || '开启失败')
  }
  const ips: string[] = st.ips?.length ? st.ips : ['<这台电脑的 IP>']
  const ip = ips[Math.min(ipIdx, ips.length - 1)]
  const cmd = `ssh -p ${st.port} ${st.user}@${ip}`
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
              <CopyRow label="用户名" value={st.user} />
              <CopyRow label="IP" value={ip} />
              {ips.length > 1 && (
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', ml: '64px', mb: 0.3 }}>
                  {ips.map((x, i) => <Button key={x} size="small" variant={i === ipIdx ? 'contained' : 'text'} sx={{ ...rounded, py: 0, minWidth: 0, fontSize: 12 }} onClick={() => setIpIdx(i)}>{x}</Button>)}
                </Box>
              )}
              <CopyRow label="端口" value={String(st.port)} big />
              <CopyRow label="密码" value={st.password} big />
              <Box sx={{ mt: 1, p: 1.2, borderRadius: 2, bgcolor: 'action.hover' }}><CopyRow label="命令" value={cmd} /></Box>
              <Typography variant="subtitle2" sx={{ mt: 2, mb: 0.5 }}>当前连接</Typography>
              {st.sessions?.length ? st.sessions.map((x: any) => (
                <Box key={x.sid} sx={{ display: 'flex', alignItems: 'center', py: 0.3 }}>
                  <Typography sx={{ flex: 1, fontFamily: 'Consolas, monospace', fontSize: 14 }}>{x.ip} <Typography component="span" variant="caption" color="text.secondary">· {fmtDate(x.since)}</Typography></Typography>
                  <Button size="small" color="error" onClick={() => api.share_kick(x.sid)}>踢掉</Button>
                </Box>
              )) : <Typography variant="body2" color="text.secondary">暂无</Typography>}
              {st.log?.length > 0 && <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 1.5, userSelect: 'text' }}>{[...st.log].reverse().slice(0, 4).map((l: any) => `${new Date(l.t * 1000).toLocaleTimeString('zh-CN', { hour12: false })}  ${l.text}`).map((t: string) => <div key={t}>{t}</div>)}</Typography>}
            </Box>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
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
export default function SshPage({ active }: { active?: boolean }) {
  const [hosts, setHosts] = useState<Host[]>([])
  const [key, setKey] = useState<any>({ exists: false })
  const [autoKey, setAutoKey] = useState(false)
  const [cfg, setCfg] = useState('')
  const [err, setErr] = useState('')
  const [sel, setSel] = useState('')
  const [tab, setTab] = useState(0)
  const [termHosts, setTermHosts] = useState<string[]>([])
  const [fileHosts, setFileHosts] = useState<string[]>([])
  const [dlg, setDlg] = useState<null | { host: Host | null }>(null)
  const [keyRes, setKeyRes] = useState<any>(null)
  const [keyBusy, setKeyBusy] = useState<null | { i: number; n: number; alias: string }>(null)
  const [note, setNote] = useState('')
  const [keyNote, setKeyNote] = useState('')
  const exportKey = async () => { setKeyNote(''); const r = await api.ssh_key_export(); if (!r.ok && !r.cancelled) setKeyNote(r.error || '保存失败') }
  const [share, setShare] = useState<any>({ on: false })
  const [shareOpen, setShareOpen] = useState(false)
  type Chk = { st: 'checking' | 'ok' | 'bad'; via?: string; ms?: number; error?: string; internal?: boolean; addr?: { host: string; port: number }; t?: number }
  const [chk, setChk] = useState<Record<string, Chk>>({})
  const running = useRef(false)
  const [refreshing, setRefreshing] = useState(false)

  // 全量测一遍连通性（并发 4 个）；进入页面、增删改主机、点刷新时都会跑
  const checkAll = async (list: Host[]) => {
    if (running.current) return
    running.current = true; setRefreshing(true)
    setChk((cur) => Object.fromEntries(list.map((h) => [h.alias, cur[h.alias] && cur[h.alias].st !== 'checking' ? cur[h.alias] : ({ st: 'checking' } as Chk)])))      // 刷新中先保留上次的结果，别让整个列表乱跳
    const queue = [...list]
    const worker = async () => {
      for (let h = queue.shift(); h; h = queue.shift()) {
        const r = await api.ssh_check(h.alias)
        setChk((c) => ({ ...c, [h.alias]: r.ok ? { st: 'ok', via: r.via, ms: r.ms, internal: r.internal, addr: r.addr, t: Date.now() / 1000 } : { st: 'bad', error: r.error, t: Date.now() / 1000 } }))
      }
    }
    await Promise.all([worker(), worker(), worker(), worker()])
    running.current = false; setRefreshing(false)
    setChk((c) => ({ ...c }))      // 触发一次重绘，让“默认选第一个连得通的”生效
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
    setErr(''); setHosts(r.hosts); setKey(r.key); setAutoKey(r.auto_key); setCfg(r.config)
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
    const byName = [...(r.hosts as Host[])].sort((a, b) => a.alias.localeCompare(b.alias, undefined, { sensitivity: 'base' }))
    const firstOk = byName.find((h) => r.status?.[h.alias]?.ok)?.alias || byName[0]?.alias || ''       // 默认选第一个连得通的（按列表顺序）
    setSel((cur) => { const c = keep ?? cur; return r.hosts.some((h: Host) => h.alias === c) ? c : firstOk })
    return r.hosts as Host[]
  }
  const refresh = async () => { const l = await load(); if (l) checkAll(l) }          // 只有点刷新按钮才会全量测试连通性
  useEffect(() => { if (active) load() }, [active])
  useEvent('ssh:keyprogress', (d: any) => setKeyBusy(d))
  useEvent('share:state', (d: any) => setShare(d))
  useEffect(() => { api.share_info().then(setShare) }, [])

  const picked = useRef(false)      // 用户自己点过主机之后，就不再自动换选中项
  const openFiles = (a: string) => { picked.current = true; setSel(a); setTab(0); setFileHosts((l) => (l.includes(a) ? l : [...l, a])) }
  const openTerm = (a: string) => { picked.current = true; setSel(a); setTab(1); setTermHosts((l) => (l.includes(a) ? l : [...l, a])) }
  const choose = (a: string) => { if (a === sel) return; picked.current = true; setSel(a); if (tab === 1) openTerm(a); else openFiles(a) }
  useEffect(() => { if (sel && tab === 0) setFileHosts((l) => (l.includes(sel) ? l : [...l, sel])) }, [sel, tab])
  useEffect(() => { if (sel && tab === 1) setTermHosts((l) => (l.includes(sel) ? l : [...l, sel])) }, [sel, tab])

  const runKeys = async () => {
    setKeyBusy({ i: 0, n: hosts.length, alias: '' })
    const r = await api.ssh_key_all()
    setKeyBusy(null); setKeyRes(r); setChk({}); load().then((l) => { if (l) checkAll(l) })      // 密钥配置变了，登录方式也会变，全部重测
  }
  const toggleAuto = async (on: boolean) => { setAutoKey(on); await api.ssh_auto_key(on) }
  const onSaved = (h: Host, n: string) => {
    setNote(n)
    setChk((c) => { const x = { ...c }; delete x[dlg?.host?.alias || '']; delete x[h.alias]; return x })       // 改过的主机状态先作废，保存后马上自动重测这一台
    if (h.alias) { load(h.alias).then(() => { openFiles(h.alias); checkOne(h.alias) }) } else { setFileHosts((l) => l.filter((x) => x !== dlg?.host?.alias)); setTermHosts((l) => l.filter((x) => x !== dlg?.host?.alias)); load() }
  }
  // 只有测通了的排上面，没测/测不通的都在下面；各自按字母
  const sorted = [...hosts].sort((a, b) => ((chk[a.alias]?.st === 'ok' ? 0 : 1) - (chk[b.alias]?.st === 'ok' ? 0 : 1)) || a.alias.localeCompare(b.alias, undefined, { sensitivity: 'base' }))
  const cur = hosts.find((h) => h.alias === sel)
  // 手动刷新测完之后，如果用户还没自己选过，就换成第一个连得通的
  useEffect(() => {
    if (picked.current || running.current) return
    const first = sorted.find((h) => chk[h.alias]?.st === 'ok')
    if (first && first.alias !== sel) setSel(first.alias)
  })

  const title = <Box sx={{ display: 'flex', alignItems: 'center' }}>SSH管理</Box>
  return (
    <BasePage title={title} info="主机列表和 ~/.ssh/config 同步；传文件、开命令行都是两端直连，不经过中转。"
      header={<Box sx={{ display: 'flex', gap: 1 }}>
        <Button variant="outlined" size="small" startIcon={<ShareOutlined />} sx={rounded} onClick={() => setShareOpen(true)}>
          共享本机{share.on && <Box component="span" sx={{ ml: 0.8, width: 8, height: 8, borderRadius: '50%', bgcolor: 'success.main', display: 'inline-block' }} />}
        </Button>
        <Button variant="contained" size="small" startIcon={<AddRounded />} sx={rounded} onClick={() => setDlg({ host: null })}>添加主机</Button>
      </Box>}>
      {err && <Alert severity="error" sx={{ mb: 1.5, borderRadius: 2 }}>{err}</Alert>}
      <Box sx={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 1.5, alignItems: 'start', height: 'calc(100vh - 150px)', minHeight: 460 }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, minHeight: 0, maxHeight: '100%' }}>
          <EnhancedCard title="主机" icon={<DnsOutlined />} minHeight={120} action={<Tooltip title="重新测试所有主机的连通性"><span><IconButton size="small" disabled={(refreshing || Object.values(chk).some((x) => x.st === 'checking'))} onClick={refresh}><RefreshRounded fontSize="small" /></IconButton></span></Tooltip>}>
            {hosts.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 2 }}>还没有主机</Typography>}
            <Box sx={{ maxHeight: 'calc(100vh - 420px)', minHeight: 60, overflow: 'auto', mx: -0.5 }}>
              {sorted.map((h) => {
                const c = chk[h.alias]
                return (
                  <Box key={h.alias} onClick={() => choose(h.alias)} onDoubleClick={() => openTerm(h.alias)}
                    sx={{ display: 'flex', alignItems: 'center', gap: 0.5, py: 0.9, px: 1, borderRadius: 1.5, cursor: 'pointer', bgcolor: sel === h.alias ? 'action.selected' : 'transparent', '&:hover': { bgcolor: sel === h.alias ? 'action.selected' : 'action.hover' } }}>
                    <Tooltip title={!c ? '还没测试，点右上角刷新' : c.st === 'checking' ? '正在测试连通性…' : `${c.st === 'ok' ? `连通 · ${c.internal ? '内网' : '公网'} ${c.addr?.host || ''} · ${c.via === 'key' ? '密钥登录' : '密码登录'}` : c.error}${c.t ? `（上次测试 ${new Date(c.t * 1000).toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}）` : ''}`}>
                      <Box sx={{ width: 9, height: 9, borderRadius: '50%', flexShrink: 0, mr: 0.8, bgcolor: !c || c.st === 'checking' ? 'text.disabled' : c.st === 'ok' ? 'success.main' : 'error.main', animation: c?.st === 'checking' ? 'pulse 1s ease-in-out infinite' : 'none', '@keyframes pulse': { '0%,100%': { opacity: 0.35 }, '50%': { opacity: 1 } } }} />
                    </Tooltip>
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.8 }}>
                        <Typography noWrap sx={{ fontWeight: 700, fontSize: 14 }}>{h.alias}</Typography>
                        {c?.st === 'ok' && c.internal && (
                          <Tooltip title="内网直连，速度更快">
                            <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.2, px: 0.7, borderRadius: 1, fontSize: 11, fontWeight: 700, color: 'primary.main', bgcolor: 'action.hover', lineHeight: 1.6, flexShrink: 0, cursor: 'default' }}>
                              <BoltRounded sx={{ fontSize: 12 }} />高速
                            </Box>
                          </Tooltip>
                        )}
                        {c?.st === 'ok' && c.via === 'key' && (
                          <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.3, px: 0.7, borderRadius: 1, fontSize: 11, fontWeight: 700, color: 'success.main', bgcolor: 'action.hover', lineHeight: 1.6, flexShrink: 0, cursor: 'default' }}>
                            <VpnKeyOutlined sx={{ fontSize: 11 }} />密钥
                          </Box>
                        )}
                      </Box>
                      <Typography noWrap variant="caption" color={c?.st === 'bad' ? 'error.main' : 'text.secondary'}>{c?.st === 'bad' ? '连不上' : target(c?.st === 'ok' && c.addr ? { ...h, host: c.addr.host, port: c.addr.port } : h)}</Typography>
                    </Box>
                    <Tooltip title="打开命令行"><IconButton size="small" onClick={(e) => { e.stopPropagation(); openTerm(h.alias) }}><TerminalOutlined fontSize="small" /></IconButton></Tooltip>
                    <Tooltip title="编辑"><IconButton size="small" onClick={(e) => { e.stopPropagation(); setDlg({ host: h }) }}><EditOutlined fontSize="small" /></IconButton></Tooltip>
                  </Box>
                )
              })}
            </Box>
          </EnhancedCard>
          <EnhancedCard title={<Box sx={{ display: 'flex', alignItems: 'center' }}><Typography variant="h6" sx={{ fontWeight: 'medium', fontSize: 16 }}>SSH 密钥</Typography>
            <InfoTip text="所有主机共用同一对密钥，配好后连任何主机都不用输密码。" /></Box>} icon={<VpnKeyOutlined />}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.8 }}>
              <Box sx={{ width: 9, height: 9, borderRadius: '50%', bgcolor: key.exists ? 'success.main' : 'text.disabled' }} />
              <Typography sx={{ fontSize: 14, fontWeight: 600 }}>{key.exists ? '通用密钥已就绪' : '还没有通用密钥'}</Typography>
              {key.exists && <Button size="small" variant="outlined" startIcon={<DownloadOutlined />} sx={{ ...rounded, ml: 'auto' }} onClick={exportKey}>下载密钥</Button>}
            </Box>
            {keyNote && <Typography variant="caption" color="error.main" sx={{ display: 'block', mb: 0.8, wordBreak: 'break-all', userSelect: 'text' }}>{keyNote}</Typography>}
            {hosts.length > 0 && Object.keys(chk).length > 0 && !(refreshing || Object.values(chk).some((x) => x.st === 'checking')) && (
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.8 }}>{Object.values(chk).filter((x) => x.st === 'ok' && x.via === 'key').length} / {hosts.length} 台主机已用密钥登录</Typography>
            )}
            <Row label="新增主机自动配置密钥"><Switch checked={autoKey} onChange={(_, v) => toggleAuto(v)} /></Row>
            <Button size="small" sx={{ alignSelf: 'flex-start', ml: -1, mt: 0.3 }} disabled={!!keyBusy || hosts.length === 0} onClick={runKeys}>
              {keyBusy ? `配置中 ${Math.min(keyBusy.i + 1, keyBusy.n)}/${keyBusy.n}…` : key.exists ? '为所有主机重新配置' : '创建并配置到所有主机'}
            </Button>
          </EnhancedCard>
        </Box>
        <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
          {!cur ? (
            <Typography color="text.secondary" sx={{ textAlign: 'center', pt: 10 }}>添加一个主机开始</Typography>
          ) : (
            <>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                <Tabs value={tab} onChange={(_, v) => (v === 1 ? openTerm(cur.alias) : openFiles(cur.alias))} sx={{ minHeight: 36, '& .MuiTab-root': { minHeight: 36, fontWeight: 700, py: 0 } }}>
                  <Tab label="文件" /><Tab label="命令行" />
                </Tabs>
                <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto', mr: 1 }}>{cur.alias} · {target(cur)}</Typography>
                <Tooltip title="在系统终端里打开"><IconButton size="small" onClick={() => api.open_terminal(cur.alias)}><TerminalOutlined fontSize="small" /></IconButton></Tooltip>
              </Box>
              <Box sx={{ flex: 1, minHeight: 0, position: 'relative' }}>
                {fileHosts.filter((a) => hosts.some((h) => h.alias === a)).map((a) => <Box key={a} sx={{ display: a === sel ? 'block' : 'none', height: '100%' }}><FilesPane alias={a} active={a === sel && tab === 0} /></Box>)}
                {termHosts.filter((a) => hosts.some((h) => h.alias === a)).map((a) => <Box key={a} sx={{ display: a === sel && tab === 1 ? 'block' : 'none', position: 'absolute', inset: 0 }}><TermPane alias={a} active={a === sel && tab === 1} /></Box>)}
              </Box>
            </>
          )}
          {note && <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>{note}</Typography>}
        </Box>
      </Box>
      <HostDialog open={!!dlg} host={dlg?.host || null} onClose={() => setDlg(null)} onSaved={onSaved} onKeys={runKeys} />
      <KeyResult r={keyRes} onClose={() => setKeyRes(null)} />
      <ShareDialog open={shareOpen} st={share} onClose={() => setShareOpen(false)} />
    </BasePage>
  )
}
