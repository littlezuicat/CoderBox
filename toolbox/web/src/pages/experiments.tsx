// 实验：自动记录各台服务器上正在跑的深度学习训练（不调用模型，只读日志）。
// 后端 py/majing/core/expmon.py 每分钟扫一次已连接的 Linux 主机：谁在占显存 → 读它的日志 → 算进度条和预计结束时间；进程消失后自动归档为 完成 / 出错 / 中断。
// 版式：上面“正在运行”按主机分组（主机占左栏，一个任务一横条，显卡用 GPU0 GPU1 胶囊标出），下面是“历史记录”。
import DeleteSweepOutlined from '@mui/icons-material/DeleteSweepOutlined'
import RefreshRounded from '@mui/icons-material/RefreshRounded'
import { alpha, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Tooltip, Typography, useTheme } from '@mui/material'
import { useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../bridge'
import { BasePage } from '../components/base-page'
import { fmtDur } from '../components/gpu-board'
import { useEvent } from '../hooks'

type Exp = {
  id: string; alias: string; user: string; cwd: string; cmd: string; launcher?: string; name: string; gpus: number[]; mem: number; pid: number
  start: number; end: number | null; status: 'running' | 'done' | 'failed' | 'stopped'; frac: number | null; label: string; stage: string
  eta_ts: number | null; eta_src: 'log' | 'rate' | 'elapsed' | 'epoch-eta' | null; last_line: string; metrics: Record<string, string>; log: string; error: string; updated: number
}
type HostGpu = { index: number; name: string; mem_used: number; mem_total: number; util: number }
type Hosts = Record<string, { t: number; gpus: HostGpu[] }>
type HFilter = 'all' | 'done' | 'bad'

const COLS = '112px minmax(150px,1.1fr) minmax(200px,1.7fr) 54px minmax(160px,1.1fr)'      // 显卡 | 实验 | 进度 | % | 时间
const TASK_COLORS = ['#378ADD', '#1D9E75', '#BA7517', '#7F77DD', '#D4537E', '#639922']
const pad = (n: number) => String(n).padStart(2, '0')
const clock = (t: number) => {
  const d = new Date(t * 1000), n = new Date()
  const day = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() - new Date(n.getFullYear(), n.getMonth(), n.getDate()).getTime()) / 86400000)
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return day === 0 ? `今天 ${hm}` : day === 1 ? `明天 ${hm}` : day === -1 ? `昨天 ${hm}` : `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`
}
const span = (a: number, b: number) => {                       // 同一天只写一次日期
  const x = new Date(a * 1000), y = new Date(b * 1000)
  const same = x.getFullYear() === y.getFullYear() && x.getMonth() === y.getMonth() && x.getDate() === y.getDate()
  return same ? `${clock(a)} → ${pad(y.getHours())}:${pad(y.getMinutes())}` : `${clock(a)} → ${clock(b)}`
}
const shortName = (n: string) => n.replace(/^NVIDIA\s+(GeForce\s+)?/i, '')

// 显卡胶囊：GPU0 GPU1，颜色跟任务走；看不出在哪张卡（容器里 nvidia-smi 看不到进程）就写 GPU ?
function GpuTags({ gpus, color }: { gpus: number[]; color: string }) {
  if (!gpus.length) return <Typography sx={{ fontSize: 11.5, color: 'text.disabled' }}>GPU ?</Typography>
  return (
    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
      {gpus.map((g) => <Box key={g} component="span" sx={{ fontSize: 11, fontWeight: 600, lineHeight: '17px', px: 0.9, borderRadius: 9, color, bgcolor: alpha(color, 0.14), border: `0.5px solid ${alpha(color, 0.5)}` }}>GPU{g}</Box>)}
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

type RowProps = { e: Exp; now: number; dark: boolean; color: string; history?: boolean; onLog: () => void; onRemove: () => void }
function Row({ e, now, dark, color, history, onLog, onRemove }: RowProps) {
  const theme = useTheme()
  const [open, setOpen] = useState(false)
  const running = e.status === 'running'
  const stale = running && now - e.updated > 240
  const pct = e.frac === null ? null : Math.min(100, Math.floor(e.frac * 1000) / 10)
  const sc = e.status === 'done' ? theme.palette.success.main : e.status === 'failed' ? theme.palette.error.main : e.status === 'stopped' ? theme.palette.warning.main : color
  const stageText = running ? e.stage.replace(/（.*）/, '') : e.status === 'done' ? '已完成' : e.status === 'failed' ? '出错退出' : '中途退出'
  const total = e.eta_ts ? e.eta_ts - e.start : null
  const m = e.metrics || {}
  const mets = [['PSNR', m.psnr], ['SSIM', m.ssim], ['loss', m.loss]].filter((x) => x[1])
  return (
    <>
      <Box onClick={() => setOpen((v) => !v)} sx={{ display: 'grid', gridTemplateColumns: COLS, alignItems: 'center', gap: 2, px: 1.8, py: 1.15, cursor: 'pointer', opacity: stale ? 0.55 : 1, '&:hover': { bgcolor: 'action.hover' } }}>
        <GpuTags gpus={e.gpus} color={color} />
        <Box sx={{ minWidth: 0 }}>
          <Typography noWrap title={e.name} sx={{ fontSize: 13.5, fontWeight: 600 }}>{e.name}</Typography>
          <Typography noWrap sx={{ fontSize: 12, color: running ? 'text.secondary' : sc }}>{stageText}</Typography>
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Bar frac={e.frac} color={sc} running={running} dark={dark} />
          <Typography noWrap sx={{ fontSize: 12, color: 'text.secondary', mt: 0.4 }}>{e.label || (running ? '没认出进度' : '')}</Typography>
        </Box>
        <Typography sx={{ fontSize: 13.5, fontWeight: 600, fontVariantNumeric: 'tabular-nums', textAlign: 'right' }}>{pct === null ? '—' : `${Math.round(pct)}%`}</Typography>
        {running ? (
          <Box sx={{ fontVariantNumeric: 'tabular-nums', minWidth: 0 }}>
            <Typography noWrap sx={{ fontSize: 13 }}>{fmtDur(now - e.start)} / {total ? fmtDur(total) : '—'}</Typography>
            <Typography noWrap sx={{ fontSize: 12, color: 'text.secondary' }}>{e.eta_ts ? `${clock(e.eta_ts)} 结束${e.eta_src === 'elapsed' ? '（粗估）' : ''}` : stale ? `停在 ${fmtDur(now - e.updated)} 前` : '—'}</Typography>
          </Box>
        ) : (
          <Box sx={{ fontVariantNumeric: 'tabular-nums', minWidth: 0 }}>
            <Typography noWrap sx={{ fontSize: 13 }}>用时 {fmtDur((e.end || e.updated) - e.start)}</Typography>
            <Typography noWrap sx={{ fontSize: 12, color: 'text.secondary' }}>{span(e.start, e.end || e.updated)}</Typography>
          </Box>
        )}
      </Box>
      {open && (
        <Box sx={{ px: 1.8, pb: 1.3, pt: 0.2, display: 'flex', flexDirection: 'column', gap: 0.6, fontSize: 12, color: 'text.secondary' }}>
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
            {history && <Button size="small" color="inherit" onClick={(ev) => { ev.stopPropagation(); onRemove() }} sx={{ minWidth: 0, fontSize: 12, color: 'text.secondary' }}>删除记录</Button>}
          </Box>
        </Box>
      )}
    </>
  )
}

function ColHead({ last }: { last: string }) {
  return (
    <Box sx={{ display: 'flex', fontSize: 12, color: 'text.disabled', borderBottom: 1, borderColor: 'divider', py: 0.9 }}>
      <Box sx={{ boxSizing: 'border-box', flex: '0 0 104px', pl: 1.8 }}>主机</Box>
      <Box sx={{ flex: 1, minWidth: 0, display: 'grid', gridTemplateColumns: COLS, gap: 2, px: 1.8 }}>
        <span>显卡</span><span>实验</span><span>进度</span><span></span><span>{last}</span>
      </Box>
    </Box>
  )
}

function Section({ title, count, right, children }: { title: string; count: number; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Box sx={{ mb: 2.5 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, px: 0.3 }}>
        <Typography sx={{ fontSize: 14.5, fontWeight: 700 }}>{title}</Typography>
        <Typography sx={{ fontSize: 13, color: 'text.secondary' }}>{count}</Typography>
        <Box sx={{ flex: 1 }} />{right}
      </Box>
      {children}
    </Box>
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
  const dark = useTheme().palette.mode === 'dark'
  const [items, setItems] = useState<Exp[]>([])
  const [hosts, setHosts] = useState<Hosts>({})
  const [hf, setHf] = useState<HFilter>('all')
  const [busy, setBusy] = useState(false)
  const [last, setLast] = useState(0)
  const [now, setNow] = useState(Math.floor(Date.now() / 1000))
  const [logFor, setLogFor] = useState<Exp | null>(null)
  const set = (s: any) => { setItems(s.items || []); setHosts(s.hosts || {}); setLast(s.last_poll || 0); setBusy(!!s.busy) }

  useEffect(() => { api.exp_state().then(set) }, [])
  useEffect(() => { if (active) { setBusy(true); api.exp_refresh() } }, [active])
  useEffect(() => { const t = setInterval(() => setNow(Math.floor(Date.now() / 1000)), 20000); return () => clearInterval(t) }, [])
  useEvent('exp:update', (s) => { set(s); setNow(Math.floor(Date.now() / 1000)) })

  const running = useMemo(() => items.filter((x) => x.status === 'running'), [items])
  const groups = useMemo(() => {
    const g: Record<string, Exp[]> = {}
    running.forEach((x) => (g[x.alias] ||= []).push(x))
    Object.values(g).forEach((l) => l.sort((a, b) => (a.gpus[0] ?? 99) - (b.gpus[0] ?? 99) || a.start - b.start))
    return Object.entries(g).sort((a, b) => a[0].localeCompare(b[0]))
  }, [running])
  const history = useMemo(() => {
    const f = items.filter((x) => x.status !== 'running' && (hf === 'all' || (hf === 'done' && x.status === 'done') || (hf === 'bad' && x.status !== 'done')))
    return f.sort((a, b) => (b.end || b.updated) - (a.end || a.updated))
  }, [items, hf])
  const finishedCount = items.length - running.length
  // 没有任务的主机：一行带过（有显卡、连得上、当前没有任务）
  const idle = useMemo(() => Object.keys(hosts).filter((a) => !groups.some(([g]) => g === a)).sort(), [hosts, groups])
  const hname = (a: string) => { const g = hosts[a]?.gpus; return g?.length ? `${g.length} × ${shortName(g[0].name)}` : '' }
  const freeText = (alias: string, exps: Exp[]) => {
    const h = hosts[alias]
    if (!h || exps.some((x) => !x.gpus.length)) return ''
    const used = new Set(exps.flatMap((x) => x.gpus))
    const free = h.gpus.filter((g) => !used.has(g.index)).map((g) => g.index)
    return free.length ? `空闲 ${free.map((i) => 'GPU' + i).join(' ')}` : ''
  }

  const chip = (k: HFilter, text: string) => (
    <Chip size="small" label={text} onClick={() => setHf(k)} color={hf === k ? 'primary' : 'default'} variant={hf === k ? 'filled' : 'outlined'} />
  )
  const wrap = { bgcolor: dark ? '#282A36' : '#fff', borderRadius: 2, overflow: 'hidden' }
  const rail = { boxSizing: 'border-box' as const, flex: '0 0 104px', px: 1.8, py: 1.3, bgcolor: dark ? 'rgba(255,255,255,.04)' : 'rgba(0,0,0,.035)', borderRight: 1, borderColor: 'divider' }
  return (
    <BasePage title="实验" info="自动发现各台已连接的 Linux 服务器上正在占用显存的 Python 训练任务，读日志算进度和预计结束时间，跑完自动归档。不调用任何模型。后台每分钟扫一次；只记录深度学习训练，Jupyter 等不算。"
      header={
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {last > 0 && <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>{busy ? '正在扫描…' : `${fmtDur(now - last)}前扫描`}</Typography>}
          <Tooltip title="立即扫描"><span><IconButton size="small" disabled={busy} onClick={() => { setBusy(true); api.exp_refresh() }}>{busy ? <CircularProgress size={18} /> : <RefreshRounded />}</IconButton></span></Tooltip>
        </Box>
      }>
      <Box sx={{ p: 0.5 }}>
        <Section title="正在运行" count={running.length}>
          {groups.length === 0 ? (
            <Box sx={{ ...wrap, py: 5, textAlign: 'center', color: 'text.disabled', fontSize: 13.5 }}>
              {items.length || Object.keys(hosts).length ? '现在没有实验在跑' : '还没发现实验。在「主机」里连上服务器后，占着显存的 Python 训练任务（跑满 2 分钟）会自动出现在这里'}
            </Box>
          ) : (
            <Box sx={wrap}>
              <ColHead last="已训练 / 预计共" />
              {groups.map(([alias, exps], gi) => {
                const free = freeText(alias, exps)
                return (
                  <Box key={alias} sx={{ display: 'flex', borderTop: gi ? 1 : 0, borderColor: 'divider' }}>
                    <Box sx={rail}>
                      <Typography sx={{ fontSize: 14, fontWeight: 700 }}>{alias}</Typography>
                      {hname(alias) && <Typography sx={{ fontSize: 11.5, color: 'text.secondary' }}>{hname(alias)}</Typography>}
                      {free && <Typography sx={{ fontSize: 11.5, color: 'success.main', mt: 0.4 }}>{free}</Typography>}
                    </Box>
                    <Box sx={{ flex: 1, minWidth: 0, '& > :not(:first-of-type)': { borderTop: 1, borderColor: 'divider' } }}>
                      {exps.map((e, i) => <Box key={e.id}><Row e={e} now={now} dark={dark} color={TASK_COLORS[i % TASK_COLORS.length]} onLog={() => setLogFor(e)} onRemove={() => {}} /></Box>)}
                    </Box>
                  </Box>
                )
              })}
              {idle.length > 0 && (
                <Box sx={{ px: 1.8, py: 1, borderTop: 1, borderColor: 'divider', fontSize: 12.5, color: 'text.secondary', display: 'flex', gap: 2.5, flexWrap: 'wrap' }}>
                  {idle.map((a) => <span key={a}><b style={{ fontWeight: 600 }}>{a}</b> 空闲{hname(a) ? ` · ${hname(a)}` : ''}</span>)}
                </Box>
              )}
            </Box>
          )}
        </Section>

        <Section title="历史记录" count={finishedCount}
          right={<Box sx={{ display: 'flex', alignItems: 'center', gap: 0.8 }}>
            {chip('all', '全部')}{chip('done', '已完成')}{chip('bad', '出错 / 中断')}
            <Tooltip title="清空历史记录"><span><IconButton size="small" disabled={!finishedCount} onClick={() => { if (window.confirm('清空所有已结束的实验记录？')) api.exp_clear_finished() }}><DeleteSweepOutlined fontSize="small" /></IconButton></span></Tooltip>
          </Box>}>
          {history.length === 0 ? (
            <Box sx={{ ...wrap, py: 4, textAlign: 'center', color: 'text.disabled', fontSize: 13.5 }}>{finishedCount ? '这个分类下没有记录' : '跑完的实验会自动记在这里'}</Box>
          ) : (
            <Box sx={wrap}>
              <ColHead last="用时 / 起止" />
              {history.map((e, i) => (
                <Box key={e.id} sx={{ display: 'flex', borderTop: i ? 1 : 0, borderColor: 'divider' }}>
                  <Box sx={rail}><Typography sx={{ fontSize: 13.5, fontWeight: 600 }}>{e.alias}</Typography></Box>
                  <Box sx={{ flex: 1, minWidth: 0 }}><Row e={e} now={now} dark={dark} color={TASK_COLORS[0]} history onLog={() => setLogFor(e)} onRemove={() => api.exp_remove(e.id)} /></Box>
                </Box>
              ))}
            </Box>
          )}
        </Section>
      </Box>
      <LogDialog id={logFor?.id ?? null} name={logFor?.name ?? ''} onClose={() => setLogFor(null)} />
    </BasePage>
  )
}
