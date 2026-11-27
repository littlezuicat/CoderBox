// GPU 总览：每台服务器一张卡片，每张显卡一行（利用率条 + 显存条）。打开页面时采样，之后每 8 秒自动采一次（页面关了就停）。
// 同时导出左侧主机列表里用的迷你双条（GpuMini / GpuBars）和状态 hook（useGpu）。
import RefreshRounded from '@mui/icons-material/RefreshRounded'
import { alpha, Box, CircularProgress, IconButton, Tooltip, Typography, useTheme } from '@mui/material'
import { useEffect, useState } from 'react'

import { api } from '../bridge'
import { useEvent } from '../hooks'

export type Gpu = { index: number; uuid: string; name: string; util: number; mem_used: number; mem_total: number; temp: number }
export type Sample = { t: number; state: 'ok' | 'nogpu' | 'error'; os?: string; error?: string; gpus: Gpu[] }

const STALE = 180                                     // 超过这么多秒没更新的采样，淡显并标注
export const barColor = (v: number) => (v < 50 ? 'success.main' : v < 85 ? 'warning.main' : 'error.main')
export const gb = (mb: number) => { const x = mb / 1024; return x >= 100 ? String(Math.round(x)) : x >= 10 ? x.toFixed(0) : x.toFixed(1) }
export const fmtDur = (s: number) => { s = Math.max(0, Math.floor(s)); const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60); return d ? `${d}天${h}小时` : h ? `${h}小时${m}分` : m ? `${m}分钟` : `${s}秒` }
const isIdle = (g: Gpu) => g.util < 10 && g.mem_used < g.mem_total * 0.1
const stale = (s?: Sample) => !!s && Date.now() / 1000 - s.t > STALE

export function Bar({ v, h = 6, dim }: { v: number; h?: number; dim?: boolean }) {
  return (
    <Box sx={{ height: h, borderRadius: h / 2, bgcolor: 'action.hover', overflow: 'hidden', opacity: dim ? 0.45 : 1 }}>
      <Box sx={{ height: '100%', width: `${Math.max(0, Math.min(100, v))}%`, borderRadius: h / 2, bgcolor: barColor(v), transition: 'width .4s, background-color .4s' }} />
    </Box>
  )
}

// ----------------------------------------------------------------------------------- 状态
// 打开时（watch 变成 true）采样一次，之后每 8 秒自动采一次（离开页面就停）；结果到了才更新。
const AUTO_MS = 8 * 1000
export function useGpu(watch: boolean) {
  const [samples, setSamples] = useState<Record<string, Sample>>({})
  useEffect(() => {
    if (!watch) return
    api.gpu_state().then((s: any) => setSamples(s?.samples || {}))
    api.gpu_sample_now()
    const timer = setInterval(() => api.gpu_sample_now(), AUTO_MS)
    return () => clearInterval(timer)
  }, [watch])
  useEvent('gpu:sample', (d: any) => setSamples((c) => ({ ...c, [d.alias]: d.sample })))
  return { samples }
}

// ----------------------------------------------------------------------------------- 左侧主机列表里的迷你双条（上：GPU，下：显存）
export function GpuMini({ sample, fallback }: { sample?: Sample; fallback: string }) {
  if (!sample || sample.state !== 'ok' || !sample.gpus.length) {
    return <Typography noWrap sx={{ fontSize: 12.5, color: 'text.secondary', mt: 0.3 }}>{!sample ? fallback : sample.state === 'nogpu' ? '没有 NVIDIA 显卡' : sample.state === 'error' ? '采样失败' : fallback}</Typography>
  }
  const g = sample.gpus
  const util = Math.round(g.reduce((a, x) => a + x.util, 0) / g.length)
  const used = g.reduce((a, x) => a + x.mem_used, 0), total = g.reduce((a, x) => a + x.mem_total, 0) || 1
  const mem = Math.round((used / total) * 100)
  const dim = stale(sample)
  const tip = g.map((x) => `GPU${x.index}  ${x.util}%  ${gb(x.mem_used)}/${gb(x.mem_total)} GB`).join('\n')
  const line = (label: string, v: number) => (
    <Box sx={{ display: 'grid', gridTemplateColumns: '28px minmax(0,1fr) 30px', alignItems: 'center', gap: 0.6, lineHeight: 1 }}>
      <Typography sx={{ fontSize: 10.5, color: 'text.secondary' }}>{label}</Typography>
      <Bar v={v} h={5} dim={dim} />
      <Typography sx={{ fontSize: 10.5, color: 'text.secondary', textAlign: 'right' }}>{v}%</Typography>
    </Box>
  )
  return (
    <Tooltip title={<span style={{ whiteSpace: 'pre', fontSize: 12 }}>{tip}</span>} placement="right">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, mt: 0.4 }}>{line('GPU', util)}{line('显存', mem)}</Box>
    </Tooltip>
  )
}

// “NVIDIA GeForce RTX 4090” → “RTX 4090”；同型号合并成“8 × A100-SXM4-80GB”，混着的用 “ + ” 连起来
const shortName = (n: string) => n.replace(/^NVIDIA\s+/i, '').replace(/^GeForce\s+/i, '').trim()
export function modelSummary(g: Gpu[]) {
  const m = new Map<string, number>()
  g.forEach((x) => m.set(shortName(x.name), (m.get(shortName(x.name)) || 0) + 1))
  return [...m].map(([n, c]) => (c > 1 ? `${c} × ${n}` : n)).join(' + ')
}

// 新布局的主机列表里：两条（GPU 利用率 / 显存），百分比写在条里，右边是已用显存/总显存（多卡求和，悬停看每张卡）
export function GpuBars({ sample, fallback, compact }: { sample?: Sample; fallback: string; compact?: boolean }) {
  const theme = useTheme()
  if (!sample || sample.state !== 'ok' || !sample.gpus.length) {
    return <Typography noWrap variant="caption" color="text.secondary">{!sample ? fallback : sample.state === 'nogpu' ? '没有 NVIDIA 显卡' : sample.state === 'error' ? '采样失败' : fallback}</Typography>
  }
  const g = sample.gpus
  const util = Math.round(g.reduce((a, x) => a + x.util, 0) / g.length)
  const used = g.reduce((a, x) => a + x.mem_used, 0), total = g.reduce((a, x) => a + x.mem_total, 0) || 1
  const mem = Math.round((used / total) * 100)
  const dim = stale(sample)
  const tip = g.map((x) => `GPU${x.index}  利用率 ${x.util}%  显存 ${gb(x.mem_used)}/${gb(x.mem_total)} GB  ${x.temp}°C`).join('\n')
  const line = (label: string, v: number, right: string) => (
    <Box sx={{ display: 'grid', gridTemplateColumns: compact ? '24px minmax(0,1fr) 56px' : '30px minmax(0,1fr) 68px', alignItems: 'center', gap: compact ? 0.5 : 0.7, lineHeight: 1 }}>
      <Typography sx={{ fontSize: compact ? 11 : 11.5, color: 'text.secondary' }}>{label}</Typography>
      <Box sx={{ position: 'relative', height: compact ? 13 : 17, borderRadius: 1, bgcolor: 'action.hover', overflow: 'hidden', opacity: dim ? 0.45 : 1 }}>
        <Box sx={{ height: '100%', width: `${Math.max(0, Math.min(100, v))}%`, bgcolor: alpha(theme.palette[barColor(v).split('.')[0] as 'success'].main, 0.55), transition: 'width .4s, background-color .4s' }} />
        <Typography sx={{ position: 'absolute', left: 6, top: 0, bottom: 0, display: 'flex', alignItems: 'center', fontSize: compact ? 10.5 : 11.5, fontWeight: 700, color: 'text.primary' }}>{v}%</Typography>
      </Box>
      <Typography noWrap sx={{ fontSize: compact ? 10.5 : 11.5, color: 'text.secondary', textAlign: 'right' }}>{right}</Typography>
    </Box>
  )
  return (
    <Tooltip title={<span style={{ whiteSpace: 'pre', fontSize: 12 }}>{tip}</span>} placement="right">
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: compact ? 0.3 : 0.6, mt: compact ? 0.2 : 0.6 }}>
        <Typography noWrap sx={{ fontSize: compact ? 12 : 13, fontWeight: 600, color: 'text.primary', lineHeight: 1.2 }}>{modelSummary(g)}</Typography>
        {line('GPU', util, `${Math.max(...g.map((x) => x.temp))}°C`)}
        {line('显存', mem, `${gb(used)}/${gb(total)} G`)}
      </Box>
    </Tooltip>
  )
}

// ----------------------------------------------------------------------------------- 主机卡片
function HostCard({ alias, sample, selected, onPick }: { alias: string; sample?: Sample; selected: boolean; onPick: (a: string) => void }) {
  const idle = sample ? sample.gpus.filter(isIdle).length : 0
  const busy = !!sample?.gpus.length && sample!.gpus.every((g) => g.util >= 85)
  const dim = stale(sample)
  return (
    <Box id={`gpu-card-${alias}`} onClick={() => onPick(alias)}
      sx={{ p: 1.5, borderRadius: 2.5, cursor: 'pointer', bgcolor: (th) => alpha(th.palette.text.primary, 0.04), border: 2, borderColor: selected ? 'primary.main' : 'transparent', transition: 'border-color .2s', minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.6 }}>
        <Typography noWrap sx={{ fontWeight: 700, fontSize: 15, flex: 1, minWidth: 0 }}>{alias}</Typography>
        {dim && <Typography sx={{ fontSize: 11.5, color: 'warning.main' }}>{fmtDur(Date.now() / 1000 - sample!.t)}前的数据</Typography>}
        {sample?.state === 'ok' && (busy ? <Typography sx={{ fontSize: 12, fontWeight: 700, color: 'error.main' }}>满载</Typography>
          : idle > 0 ? <Typography sx={{ fontSize: 12, fontWeight: 700, color: 'success.main' }}>{idle} 张空闲</Typography> : null)}
      </Box>
      {!sample && <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 1, color: 'text.secondary' }}><Typography sx={{ fontSize: 13 }}>还没采样，点上方的刷新</Typography></Box>}
      {sample?.state === 'error' && <Typography sx={{ fontSize: 12.5, color: 'error.main', py: 0.5 }}>采样失败：{sample.error}</Typography>}
      {sample?.state === 'ok' && (
        <Box sx={{ opacity: dim ? 0.55 : 1, flex: 1, minHeight: 0 }}>
          <Box sx={{ display: 'grid', gridTemplateColumns: '58px minmax(0,1fr) minmax(0,1fr)', columnGap: 1.2, rowGap: 0.9, alignItems: 'center' }}>
            <span /><Typography sx={{ fontSize: 11, color: 'text.disabled' }}>显存</Typography><Typography sx={{ fontSize: 11, color: 'text.disabled' }}>GPU 利用率</Typography>
            {sample.gpus.map((g) => {
              const pct = Math.round((g.mem_used / (g.mem_total || 1)) * 100)
              return (
                <Box key={g.index} sx={{ display: 'contents' }}>
                  <Tooltip title={g.name} placement="left"><Box sx={{ minWidth: 0 }}>
                    <Typography sx={{ fontSize: 12.5, fontWeight: 700, lineHeight: 1.2 }}>GPU{g.index}</Typography>
                    {isIdle(g) && <Typography sx={{ fontSize: 11, color: 'success.main', lineHeight: 1.2 }}>空闲</Typography>}
                  </Box></Tooltip>
                  <Box><Bar v={pct} h={7} /><Typography sx={{ fontSize: 13.5, fontWeight: 700, mt: 0.2 }}>{gb(g.mem_used)} <Box component="span" sx={{ fontWeight: 400, fontSize: 12, color: 'text.secondary' }}>/ {gb(g.mem_total)} GB</Box></Typography></Box>
                  <Box><Bar v={g.util} /><Typography sx={{ fontSize: 11.5, color: 'text.secondary', mt: 0.2 }}>{g.util}% · {g.temp}°C</Typography></Box>
                </Box>
              )
            })}
          </Box>
          {sample.os === 'windows' && <Typography sx={{ fontSize: 11.5, color: 'text.disabled', mt: 0.8 }}>Windows 主机只显示显卡占用，看不到是谁在用。</Typography>}
        </Box>
      )}
    </Box>
  )
}

// ----------------------------------------------------------------------------------- 总览页
export function GpuBoard({ aliases, connected, samples, sel, onPick, active }: { aliases: string[]; connected: Record<string, boolean>; samples: Record<string, Sample>; sel: string; onPick: (a: string) => void; active: boolean }) {
  const [refreshing, setRefreshing] = useState(false)
  useEffect(() => { if (active && sel) document.getElementById(`gpu-card-${sel}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [sel, active])
  // 手动刷新：采样一次，过几秒再把按钮恢复（结果走 gpu:sample 事件陆续到达）
  const refresh = () => { setRefreshing(true); api.gpu_sample_now(); setTimeout(() => setRefreshing(false), 3000) }

  const ok = aliases.filter((a) => samples[a]?.state === 'ok')
  const pending = aliases.filter((a) => connected[a] && (!samples[a] || samples[a].state === 'error'))
  const noGpu = aliases.filter((a) => samples[a]?.state === 'nogpu')
  const offline = aliases.filter((a) => !connected[a] && !samples[a])
  const idleCount = (a: string) => samples[a].gpus.filter(isIdle).length
  const shown = [...ok].sort((a, b) => idleCount(b) - idleCount(a) || a.localeCompare(b)).concat(pending)
  const all = ok.flatMap((a) => samples[a].gpus)
  const stat = (label: string, v: React.ReactNode, color?: string) => (
    <Box sx={{ px: 1.4, py: 0.6, borderRadius: 2, bgcolor: (th) => alpha(th.palette.text.primary, 0.05) }}>
      <Typography sx={{ fontSize: 11.5, color: 'text.secondary', lineHeight: 1.3 }}>{label}</Typography>
      <Typography sx={{ fontSize: 17, fontWeight: 700, lineHeight: 1.3, color }}>{v}</Typography>
    </Box>
  )
  return (
    <Box sx={{ height: '100%', overflow: 'auto', pr: 0.5 }}>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center', mb: 1.2 }}>
        {stat('显卡', `${all.length} 张`)}
        {stat('空闲', `${all.filter(isIdle).length} 张`, 'success.main')}
        <Box sx={{ ml: 'auto', display: 'flex', alignItems: 'center', gap: 1 }}>
          {refreshing && <CircularProgress size={14} />}
          <Tooltip title="重新采样一次（不会定时刷新）"><span><IconButton size="small" disabled={refreshing || !aliases.length} onClick={refresh}><RefreshRounded sx={{ fontSize: 18 }} /></IconButton></span></Tooltip>
        </Box>
      </Box>
      {!aliases.length && <Typography color="text.secondary" sx={{ textAlign: 'center', pt: 6 }}>还没有主机</Typography>}
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', gridAutoRows: '1fr', gap: 1.2, alignItems: 'stretch' }}>
        {shown.map((a) => <HostCard key={a} alias={a} sample={samples[a]} selected={a === sel} onPick={onPick} />)}
      </Box>
      {(noGpu.length > 0 || offline.length > 0) && (
        <Typography sx={{ fontSize: 12, color: 'text.disabled', mt: 1.5, lineHeight: 1.8 }}>
          {noGpu.length > 0 && <>没有 NVIDIA 显卡：{noGpu.join('、')}。</>}{noGpu.length > 0 && offline.length > 0 && ' '}{offline.length > 0 && <>未连接（不采样）：{offline.join('、')}。</>}
        </Typography>
      )}
    </Box>
  )
}
