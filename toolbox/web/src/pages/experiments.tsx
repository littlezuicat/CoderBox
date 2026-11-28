// 实验：自动记录各台服务器上正在跑的深度学习训练（进度不调用模型，只读日志；每个实验的一句话说明可选用 Haiku / GPT 生成一次）。
// 后端 py/majing/core/expmon.py 每分钟扫一次已连接的 Linux 主机：谁在占显存 → 读它的日志 → 算进度条和预计结束时间；进程消失后自动归档为 完成 / 出错 / 中断。
// 版式：Clash Verge「连接」页那样的一张表——顶部 运行中/已结束 切换 + 过滤框，表头可点击排序，斑马纹行，点一行展开命令/日志。
import ArrowDownwardRounded from '@mui/icons-material/ArrowDownwardRounded'
import ArrowUpwardRounded from '@mui/icons-material/ArrowUpwardRounded'
import AutoAwesomeOutlined from '@mui/icons-material/AutoAwesomeOutlined'
import DeleteSweepOutlined from '@mui/icons-material/DeleteSweepOutlined'
import ErrorOutline from '@mui/icons-material/ErrorOutline'
import MarkEmailReadOutlined from '@mui/icons-material/MarkEmailReadOutlined'
import NotificationsActive from '@mui/icons-material/NotificationsActive'
import NotificationsNoneOutlined from '@mui/icons-material/NotificationsNoneOutlined'
import HourglassTopRounded from '@mui/icons-material/HourglassTopRounded'
import RefreshRounded from '@mui/icons-material/RefreshRounded'
import { alpha, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Menu, MenuItem, Tooltip, Typography, useTheme } from '@mui/material'
import { useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../bridge'
import { BasePage } from '../components/base-page'
import { fmtDur, gb } from '../components/gpu-board'
import { useEvent } from '../hooks'

type Exp = {
  id: string; alias: string; user: string; cwd: string; cmd: string; launcher?: string; name: string; gpus: number[]; mem: number; pid: number
  start: number; end: number | null; status: 'running' | 'done' | 'failed' | 'stopped'; frac: number | null; label: string; stage: string
  gpu_model?: string; note?: string; sub?: boolean; mail?: 'pending' | 'sent' | 'failed'; mail_err?: string; eta_ts: number | null; eta_src: 'log' | 'rate' | 'elapsed' | 'epoch-eta' | null; last_line: string; metrics: Record<string, string>; log: string; error: string; updated: number
}
type HostGpu = { index: number; name: string; mem_used: number; mem_total: number; util: number }
type Hosts = Record<string, { t: number; gpus: HostGpu[] }>
type Ai = { mode: 'off' | 'haiku' | 'gpt'; ok: boolean | null; error: string; kind: string }
type Tab = 'run' | 'end'
type SortKey = 'alias' | 'name' | 'frac' | 'start' | 'end'

const COLS = '92px 140px 122px minmax(210px,2.4fr) minmax(104px,0.7fr) 50px 118px 118px 34px'      // 主机 | 显卡 | 利用率·显存 | 实验（一句话）| 进度 | % | 开始 | 预计结束（已结束页：结束）
const MIN_W = 1110
const AI_NAMES: Record<string, string> = { off: '关闭', haiku: 'Haiku', gpt: 'GPT-6-Luna' }
const TASK_COLORS = ['#378ADD', '#1D9E75', '#BA7517', '#7F77DD', '#D4537E', '#639922']
const pad = (n: number) => String(n).padStart(2, '0')
const clock = (t: number) => {
  const d = new Date(t * 1000), n = new Date()
  const day = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() - new Date(n.getFullYear(), n.getMonth(), n.getDate()).getTime()) / 86400000)
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return day === 0 ? `今天 ${hm}` : day === 1 ? `明天 ${hm}` : day === -1 ? `昨天 ${hm}` : `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`
}
const shortName = (n: string) => n.replace(/^NVIDIA\s+(GeForce\s+)?/i, '')

// 显卡两列：每张卡一行 —— 第一列 GPU0 胶囊 + 型号，第二列 利用率 · 显存（实时数据来自最近一次扫描；已结束的记录没有第二列）
function GpuCol({ e, host, color }: { e: Exp; host?: { gpus: HostGpu[] }; color: string }) {
  const model = shortName(e.gpu_model || host?.gpus?.[0]?.name || '')
  if (!e.gpus.length) return <Typography noWrap sx={{ fontSize: 12, color: 'text.disabled' }}>GPU ?{model ? ` · ${model}` : ''}</Typography>
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.4 }}>
      {e.gpus.map((g) => {
        return (
          <Box key={g} sx={{ display: 'flex', alignItems: 'center', gap: 0.8, whiteSpace: 'nowrap' }}>
            <Box component="span" sx={{ fontSize: 11, fontWeight: 600, lineHeight: '17px', px: 0.9, borderRadius: 9, color, bgcolor: alpha(color, 0.14), border: `0.5px solid ${alpha(color, 0.5)}` }}>GPU{g}</Box>
            <Typography component="span" noWrap sx={{ fontSize: 12, lineHeight: '17px', color: 'text.secondary' }}>{model}</Typography>
          </Box>
        )
      })}
    </Box>
  )
}

function GpuUse({ e, host }: { e: Exp; host?: { gpus: HostGpu[] } }) {
  if (e.status !== 'running' || !e.gpus.length) return <span />
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.4 }}>
      {e.gpus.map((g) => {
        const h = host?.gpus?.find((x) => x.index === g)
        return <Typography key={g} noWrap sx={{ fontSize: 12, lineHeight: '17px', fontVariantNumeric: 'tabular-nums' }}>{h ? `${h.util}% · ${gb(h.mem_used)}/${gb(h.mem_total)}G` : '—'}</Typography>
      })}
    </Box>
  )
}

function Bar({ frac, color, running, dark }: { frac: number | null; color: string; running: boolean; dark: boolean }) {
  return (
    <Box sx={{ position: 'relative', height: 6, borderRadius: 3, overflow: 'hidden', bgcolor: dark ? 'rgba(255,255,255,.1)' : 'rgba(0,0,0,.08)' }}>
      {frac !== null ? <Box sx={{ height: '100%', width: `${Math.max(1, Math.min(100, frac * 100))}%`, borderRadius: 3, bgcolor: color, transition: 'width .6s' }} />
        : running ? <Box sx={{ position: 'absolute', top: 0, bottom: 0, width: '30%', borderRadius: 3, bgcolor: alpha(color, 0.6), animation: 'expslide 1.6s ease-in-out infinite', '@keyframes expslide': { '0%': { left: '-30%' }, '100%': { left: '100%' } } }} /> : null}
    </Box>
  )
}

type RowProps = { e: Exp; host?: { gpus: HostGpu[] }; showHost: boolean; zebra: boolean; now: number; dark: boolean; color: string; ended: boolean; onLog: () => void; onRemove: () => void; onSub: () => void }
function Row({ e, host, showHost, zebra, now, dark, color, ended, onLog, onRemove, onSub }: RowProps) {
  const theme = useTheme()
  const [open, setOpen] = useState(false)
  const running = e.status === 'running'
  const stale = running && now - e.updated > 240
  const pct = e.frac === null ? null : Math.min(100, Math.floor(e.frac * 1000) / 10)
  const sc = e.status === 'done' ? theme.palette.success.main : e.status === 'failed' ? theme.palette.error.main : e.status === 'stopped' ? theme.palette.warning.main : color
  const stageText = running ? e.stage.replace(/（.*）/, '') : e.status === 'done' ? '已完成' : e.status === 'failed' ? '出错退出' : '中途退出'
  const m = e.metrics || {}
  const mets = [['PSNR', m.psnr], ['SSIM', m.ssim], ['loss', m.loss]].filter((x) => x[1])
  const endText = running ? (e.eta_ts ? `${clock(e.eta_ts)}${e.eta_src === 'elapsed' ? ' ≈' : ''}` : stale ? `停在 ${fmtDur(now - e.updated)} 前` : '—') : clock(e.end || e.updated)
  return (
    <Box sx={{ bgcolor: zebra ? (dark ? 'rgba(255,255,255,.035)' : 'rgba(0,0,0,.028)') : 'transparent', '&:hover': { bgcolor: dark ? 'rgba(255,255,255,.07)' : 'rgba(0,0,0,.055)' } }}>
      <Box onClick={() => setOpen((v) => !v)} sx={{ display: 'grid', gridTemplateColumns: COLS, alignItems: 'center', columnGap: 1.5, px: 1.5, minHeight: 46, py: 0.6, cursor: 'pointer', opacity: stale ? 0.55 : 1 }}>
        <Typography noWrap sx={{ fontSize: 13.5, fontWeight: 600 }}>{showHost ? e.alias : ''}</Typography>
        <GpuCol e={e} host={host} color={color} />
        <GpuUse e={e} host={host} />
        <Box sx={{ minWidth: 0 }}>
          <Typography title={`${e.name}\n${e.note || ''}`} sx={{ fontSize: 13.5, lineHeight: 1.5, overflowWrap: 'anywhere', display: '-webkit-box', WebkitBoxOrient: 'vertical', WebkitLineClamp: 3, overflow: 'hidden' }}>
            {e.note || e.name}
            {!running && e.status !== 'done' && <Box component="span" sx={{ ml: 1, fontSize: 12, color: sc }}>{stageText}</Box>}
          </Typography>
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Bar frac={e.frac} color={sc} running={running} dark={dark} />
          <Typography noWrap title={e.label} sx={{ fontSize: 12, color: 'text.secondary', mt: 0.4 }}>{e.label.replace(/（本轮[^）]*）/, '') || (running ? '没认出进度' : '')}</Typography>
        </Box>
        <Typography sx={{ fontSize: 13.5, fontWeight: 600, fontVariantNumeric: 'tabular-nums', textAlign: 'right' }}>{pct === null ? '—' : `${Math.round(pct)}%`}</Typography>
        <Typography noWrap sx={{ fontSize: 13, fontVariantNumeric: 'tabular-nums' }}>{clock(e.start)}</Typography>
        <Typography noWrap sx={{ fontSize: 13, fontVariantNumeric: 'tabular-nums' }}>{endText}</Typography>
        {running ? (
          <Tooltip title={e.sub ? '已订阅：实验结束后会发邮件通知（点击取消）' : '订阅：实验结束后邮件通知我'}>
            <IconButton size="small" onClick={(ev) => { ev.stopPropagation(); onSub() }} sx={{ color: e.sub ? 'primary.main' : 'text.disabled' }}>{e.sub ? <NotificationsActive sx={{ fontSize: 19 }} /> : <NotificationsNoneOutlined sx={{ fontSize: 19 }} />}</IconButton>
          </Tooltip>
        ) : e.sub ? (
          <Tooltip title={e.mail === 'sent' ? '已发邮件通知' : e.mail === 'failed' ? `邮件没发出去：${e.mail_err || ''}` : '邮件发送中…'}>
            <Box sx={{ display: 'flex', justifyContent: 'center', color: e.mail === 'sent' ? 'success.main' : e.mail === 'failed' ? 'error.main' : 'text.disabled' }}>
              {e.mail === 'sent' ? <MarkEmailReadOutlined sx={{ fontSize: 19 }} /> : e.mail === 'failed' ? <ErrorOutline sx={{ fontSize: 19 }} /> : <HourglassTopRounded sx={{ fontSize: 18 }} />}
            </Box>
          </Tooltip>
        ) : <span />}
      </Box>
      {open && (
        <Box sx={{ px: 1.5, pb: 1.3, pt: 0.2, display: 'flex', flexDirection: 'column', gap: 0.6, fontSize: 12, color: 'text.secondary' }}>
          <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
            <span>{e.alias} · {e.user}</span>{mets.map(([k, v]) => <span key={k}>{k} {v}</span>)}
          </Box>
          {e.status === 'failed' && e.error && <Box sx={{ px: 1, py: 0.6, borderRadius: 1, bgcolor: alpha(theme.palette.error.main, dark ? 0.16 : 0.08), color: 'error.main', fontFamily: 'Consolas, monospace', wordBreak: 'break-all' }}>{e.error}</Box>}
          <Box sx={{ fontFamily: 'Consolas, monospace', wordBreak: 'break-all', userSelect: 'text', bgcolor: dark ? 'rgba(255,255,255,.05)' : 'rgba(0,0,0,.04)', borderRadius: 1, p: 1 }}>
            <div>{e.launcher || e.cmd}</div>
            <div>{e.cwd}</div>
            {e.log && <div>{e.log}</div>}
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            {e.log && <Button size="small" onClick={(ev) => { ev.stopPropagation(); onLog() }} sx={{ minWidth: 0, fontSize: 12 }}>看日志</Button>}
            {ended && <Button size="small" color="inherit" onClick={(ev) => { ev.stopPropagation(); onRemove() }} sx={{ minWidth: 0, fontSize: 12, color: 'text.secondary' }}>删除记录</Button>}
          </Box>
        </Box>
      )}
    </Box>
  )
}

function Head({ ended, sort, desc, onSort }: { ended: boolean; sort: SortKey; desc: boolean; onSort: (k: SortKey) => void }) {
  const cell = (label: string, k?: SortKey, right?: boolean) => (
    <Box onClick={k ? () => onSort(k) : undefined} sx={{ display: 'flex', alignItems: 'center', gap: 0.3, cursor: k ? 'pointer' : 'default', justifyContent: right ? 'flex-end' : 'flex-start', userSelect: 'none', '&:hover': k ? { color: 'text.primary' } : undefined }}>
      {label}{k && !right && sort === k && (desc ? <ArrowDownwardRounded sx={{ fontSize: 14 }} /> : <ArrowUpwardRounded sx={{ fontSize: 14 }} />)}
    </Box>
  )
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: COLS, columnGap: 1.5, px: 1.5, py: 1, fontSize: 13, fontWeight: 500, color: 'text.secondary', borderBottom: 1, borderColor: 'divider' }}>
      {cell('主机', 'alias')}{cell('显卡')}{cell('利用率 · 显存')}{cell('实验', 'name')}{cell('进度', 'frac')}{cell('', 'frac', true)}{cell('开始', 'start')}{cell(ended ? '结束' : '预计结束', 'end')}{cell('')}
    </Box>
  )
}

function SubDialog({ exp, onClose, onDone }: { exp: Exp | null; onClose: () => void; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  useEffect(() => { setErr(''); setBusy(false) }, [exp?.id])
  const go = async () => {
    if (!exp) return
    setBusy(true); setErr('')
    const r: any = await api.exp_subscribe(exp.id, true)
    setBusy(false)
    if (!r.ok) { setErr(r.error || '订阅失败'); return }
    onDone()
  }
  return (
    <Dialog open={!!exp} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ fontSize: 16 }}>订阅这个实验？</DialogTitle>
      <DialogContent>
        <Typography sx={{ fontSize: 14, fontWeight: 600, mb: 0.5 }} noWrap>{exp?.note || exp?.name}</Typography>
        <Typography sx={{ fontSize: 13.5, color: 'text.secondary' }}>
          它结束时（完成、出错或中途退出），码境服务器会给你码境账号里已验证的邮箱发一封通知邮件，只通知这一次。
        </Typography>
        {err && <Typography sx={{ fontSize: 13, color: 'error.main', mt: 1.2 }}>{err}</Typography>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>取消</Button>
        <Button variant="contained" onClick={go} disabled={busy}>{busy ? '正在确认…' : '确认订阅'}</Button>
      </DialogActions>
    </Dialog>
  )
}

function LogDialog({ id, name, onClose }: { id: string | null; name: string; onClose: () => void }) {
  const [text, setText] = useState('')
  const [err, setErr] = useState('')
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLPreElement>(null)
  const load = async () => {
    if (!id) return
    setBusy(true)
    const r: any = await api.exp_log(id)
    setBusy(false)
    if (!r.ok) { setErr(r.error || '读不到日志'); return }
    setErr(''); setText(r.text); setPath(r.path)
    setTimeout(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight }, 30)
  }
  useEffect(() => { setText(''); setErr(''); if (id) load() }, [id])
  return (
    <Dialog open={!!id} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, fontSize: 16 }}>
        <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name} · 日志最后 300 行</span>
        <IconButton size="small" onClick={load} disabled={busy}>{busy ? <CircularProgress size={16} /> : <RefreshRounded fontSize="small" />}</IconButton>
      </DialogTitle>
      <DialogContent>
        {path && <Typography sx={{ fontSize: 12, color: 'text.secondary', mb: 1, fontFamily: 'Consolas, monospace', wordBreak: 'break-all' }}>{path}</Typography>}
        {err ? <Typography color="error">{err}</Typography> : (
          <Box component="pre" ref={box} sx={{ m: 0, height: '60vh', overflow: 'auto', fontSize: 12.5, lineHeight: 1.5, fontFamily: 'Consolas, "Cascadia Mono", monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-all', userSelect: 'text', bgcolor: (t) => (t.palette.mode === 'dark' ? '#1e1f27' : '#f5f5f5'), p: 1.2, borderRadius: 1 }}>{text || '正在读取…'}</Box>
        )}
      </DialogContent>
      <DialogActions><Button onClick={onClose}>关闭</Button></DialogActions>
    </Dialog>
  )
}

export default function ExperimentsPage({ active }: { active?: boolean }) {
  const theme = useTheme()
  const dark = theme.palette.mode === 'dark'
  const [items, setItems] = useState<Exp[]>([])
  const [hosts, setHosts] = useState<Hosts>({})
  const [ai, setAi] = useState<Ai>({ mode: 'haiku', ok: null, error: '', kind: '' })
  const [tab, setTab] = useState<Tab>('run')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<{ k: SortKey; desc: boolean }>({ k: 'alias', desc: false })
  const [busy, setBusy] = useState(false)
  const [last, setLast] = useState(0)
  const [now, setNow] = useState(Math.floor(Date.now() / 1000))
  const [logFor, setLogFor] = useState<Exp | null>(null)
  const [menu, setMenu] = useState<HTMLElement | null>(null)
  const [subFor, setSubFor] = useState<Exp | null>(null)
  const set = (s: any) => { setItems(s.items || []); setHosts(s.hosts || {}); setLast(s.last_poll || 0); setBusy(!!s.busy); if (s.ai) setAi(s.ai) }

  useEffect(() => { api.exp_state().then(set) }, [])
  useEffect(() => { if (active) { setBusy(true); api.exp_refresh() } }, [active])
  useEffect(() => { const t = setInterval(() => setNow(Math.floor(Date.now() / 1000)), 20000); return () => clearInterval(t) }, [])
  useEvent('exp:update', (s) => { set(s); setNow(Math.floor(Date.now() / 1000)) })

  const runningN = useMemo(() => items.filter((x) => x.status === 'running').length, [items])
  const endedN = items.length - runningN
  const ended = tab === 'end'
  const rows = useMemo(() => {
    const kw = q.trim().toLowerCase()
    const f = items.filter((x) => (ended ? x.status !== 'running' : x.status === 'running') &&
      (!kw || [x.alias, x.user, x.name, x.note, x.cmd, x.cwd, x.label, x.gpu_model, ...x.gpus.map((g) => `gpu${g}`)].join(' ').toLowerCase().includes(kw)))
    const val = (x: Exp): string | number => sort.k === 'alias' ? x.alias : sort.k === 'name' ? x.name : sort.k === 'frac' ? (x.frac ?? -1) : sort.k === 'start' ? x.start : (ended ? (x.end || x.updated) : (x.eta_ts ?? 9e12))
    const dir = sort.desc ? -1 : 1
    return f.sort((a, b) => {
      const va = val(a), vb = val(b)
      const c = typeof va === 'string' ? va.localeCompare(vb as string) : (va as number) - (vb as number)
      return c * dir || (a.gpus[0] ?? 99) - (b.gpus[0] ?? 99) || a.start - b.start
    })
  }, [items, tab, q, sort, ended])
  const onSort = (k: SortKey) => setSort((s) => (s.k === k ? { k, desc: !s.desc } : { k, desc: k === 'start' || k === 'end' ? true : false }))
  const hostColor: Record<string, number> = {}
  const colorOf = (e: Exp) => { hostColor[e.alias] = (hostColor[e.alias] ?? -1) + 1; return TASK_COLORS[hostColor[e.alias] % TASK_COLORS.length] }

  const seg = (k: Tab, text: string, n: number) => (
    <Box onClick={() => { setTab(k); setSort(k === 'end' ? { k: 'end', desc: true } : { k: 'alias', desc: false }) }} sx={{ px: 1.6, py: 0.55, fontSize: 13, cursor: 'pointer', userSelect: 'none', color: tab === k ? '#fff' : 'primary.main', bgcolor: tab === k ? 'primary.main' : 'transparent', border: 1, borderColor: 'primary.main', borderRight: k === 'run' ? 0 : 1, borderRadius: k === 'run' ? '4px 0 0 4px' : '0 4px 4px 0', lineHeight: 1.2 }}>
      {text} {n}
    </Box>
  )
  const aiHint = ai.mode !== 'off' && ai.ok === false ? (ai.kind === 'auth' ? '命令行还没登录，登录后会自动补上说明' : ai.kind === 'missing' ? '没找到 claude / codex 命令行' : ai.error) : ''
  return (
    <BasePage title="实验" full contentStyle={{ padding: 0 }} info="自动发现各台已连接的 Linux 服务器上正在占用显存的 Python 训练任务，读日志算进度和预计结束时间，跑完自动归档；进度不调用模型。每个实验的一句话说明可选用 Haiku 或 GPT-6-Luna 生成一次（发给模型的内容已打码，只含命令、配置和日志开头）。后台每分钟扫一次；只记录深度学习训练，Jupyter 等不算。"
      header={
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {last > 0 && <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>{busy ? '正在扫描…' : `${fmtDur(now - last)}前扫描`}</Typography>}
          <Tooltip title={aiHint || '一句话实验说明用哪个模型生成'}>
            <Button size="small" color={aiHint ? 'warning' : 'inherit'} startIcon={<AutoAwesomeOutlined sx={{ fontSize: 17 }} />} onClick={(ev) => setMenu(ev.currentTarget)} sx={{ fontSize: 12.5, color: aiHint ? undefined : 'text.secondary', minWidth: 0 }}>说明：{AI_NAMES[ai.mode]}</Button>
          </Tooltip>
          <Menu anchorEl={menu} open={!!menu} onClose={() => setMenu(null)}>
            {(['haiku', 'gpt', 'off'] as const).map((m) => (
              <MenuItem key={m} dense selected={ai.mode === m} onClick={() => { setMenu(null); setAi({ ...ai, mode: m }); api.exp_ai_set(m) }}>
                {m === 'haiku' ? 'Haiku（最低档推理）' : m === 'gpt' ? 'GPT-6-Luna（low）' : '关闭'}
              </MenuItem>
            ))}
          </Menu>
          <Tooltip title="清空已结束的记录"><span><IconButton size="small" disabled={!endedN} onClick={() => { if (window.confirm('清空所有已结束的实验记录？')) api.exp_clear_finished() }}><DeleteSweepOutlined fontSize="small" /></IconButton></span></Tooltip>
          <Tooltip title="立即扫描"><span><IconButton size="small" disabled={busy} onClick={() => { setBusy(true); api.exp_refresh() }}>{busy ? <CircularProgress size={18} /> : <RefreshRounded />}</IconButton></span></Tooltip>
        </Box>
      }>
      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, px: 1.5, py: 1.2 }}>
          <Box sx={{ display: 'flex' }}>{seg('run', '运行中', runningN)}{seg('end', '已结束', endedN)}</Box>
          <Box component="input" value={q} onChange={(ev: any) => setQ(ev.target.value)} placeholder="过滤条件" sx={{ flex: 1, minWidth: 0, boxSizing: 'border-box', height: 36, px: 1.5, fontSize: 14, color: 'text.primary', bgcolor: dark ? 'rgba(255,255,255,.04)' : '#fff', border: 1, borderColor: 'divider', borderRadius: 1, outline: 'none', fontFamily: 'inherit', '&:focus': { borderColor: 'primary.main' }, '&::placeholder': { color: 'text.disabled' } }} />
        </Box>
        <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
          <Box sx={{ minWidth: MIN_W }}>
            <Head ended={ended} sort={sort.k} desc={sort.desc} onSort={onSort} />
            {rows.length === 0 ? (
              <Box sx={{ py: 6, textAlign: 'center', color: 'text.disabled', fontSize: 13.5 }}>
                {q ? '没有符合过滤条件的实验' : ended ? (endedN ? '' : '跑完的实验会自动记在这里') : items.length || Object.keys(hosts).length ? '现在没有实验在跑' : '还没发现实验。在「主机」里连上服务器后，占着显存的 Python 训练任务（跑满 2 分钟）会自动出现在这里'}
              </Box>
            ) : rows.map((e, i) => (
              <Row key={e.id} e={e} host={hosts[e.alias]} showHost={sort.k !== 'alias' || i === 0 || rows[i - 1].alias !== e.alias} zebra={i % 2 === 1} now={now} dark={dark} color={colorOf(e)} ended={ended}
                onLog={() => setLogFor(e)} onRemove={() => api.exp_remove(e.id)} onSub={() => (e.sub ? api.exp_subscribe(e.id, false) : setSubFor(e))} />
            ))}
          </Box>
        </Box>
      </Box>
      <SubDialog exp={subFor} onClose={() => setSubFor(null)} onDone={() => setSubFor(null)} />
      <LogDialog id={logFor?.id ?? null} name={logFor?.name ?? ''} onClose={() => setLogFor(null)} />
    </BasePage>
  )
}
