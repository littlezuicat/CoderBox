// 主机的系统信息：感叹号里是 SSH 地址和系统、CPU 型号；一行是 CPU / 内存 / 硬盘 / 数据卷的占用。
// 结果会缓存（切走再切回来不用重新读）；超过 5 分钟才在打开时后台刷新一次，也可以手动点刷新。悬停里的每一行点一下就能复制。
import InfoOutlined from '@mui/icons-material/InfoOutlined'
import { alpha, Box, Tooltip, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'

export type SysInfo = {
  ok: boolean; error?: string; family?: 'linux' | 'windows'; name?: string; arch?: string; at?: number
  cpu?: { model: string; cores: number; usage: number }
  mem?: { total: number; used: number }
  disk?: { model: string; total: number; used: number; avail?: number }
  volumes?: { mount: string; type: string; total: number; used: number; media?: string }[]     // 挂载卷；media: SSD / HDD / NET（网络存储）
}

const FRESH_MS = 5 * 60 * 1000                       // 缓存超过这么久，打开主机时后台刷新一次

const gib = (b: number) => { const x = b / 1073741824; return x >= 10 ? x.toFixed(0) : x.toFixed(1) }
const pct = (used: number, total: number) => (total > 0 ? Math.max(0, Math.min(100, Math.round((used / total) * 100))) : 0)
// 占用百分比：小于 10% 保留一位小数，免得小数值全显示成 0%
const fmtPct = (v: number) => (v < 10 ? v.toFixed(1) : String(Math.round(v)))
const hm = (t: number) => new Date(t).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
const mediaText = (m?: string) => (m === 'SSD' ? 'SSD' : m === 'HDD' ? 'HDD' : m === 'NET' ? '网络存储' : '')

// ---- 缓存：内存里一份，同时存到 localStorage（重启应用也还在）
const memCache = new Map<string, SysInfo>()
const KEY = (alias: string) => `sysinfo:${alias}`
function readCache(alias: string): SysInfo | null {
  const m = memCache.get(alias)
  if (m) return m
  try {
    const raw = localStorage.getItem(KEY(alias))
    if (!raw) return null
    const v = JSON.parse(raw) as SysInfo
    memCache.set(alias, v)
    return v
  } catch { return null }
}
function writeCache(alias: string, info: SysInfo) {
  memCache.set(alias, info)
  try { localStorage.setItem(KEY(alias), JSON.stringify(info)) } catch { /* 存不下就只留内存里 */ }
}

// 淡色占用条：底色很浅，填充用主题色的半透明，不做红黄绿那种强烈的提示
function Gauge({ value }: { value: number }) {
  return (
    <Box sx={{ height: 4, borderRadius: 2, bgcolor: (th) => alpha(th.palette.text.primary, 0.08), overflow: 'hidden', width: 72, flexShrink: 1, minWidth: 24 }}>
      <Box sx={{ height: '100%', width: `${Math.min(100, value)}%`, borderRadius: 2, bgcolor: (th) => alpha(th.palette.primary.main, 0.42), transition: 'width .4s' }} />
    </Box>
  )
}

// 悬停提示里的每一行：点一下复制这一行
function CopyLines({ lines }: { lines: string[] }) {
  const [hit, setHit] = useState(-1)
  return (
    <Box sx={{ fontSize: 12, lineHeight: 1.7, minWidth: 200 }}>
      {lines.map((l, i) => (
        <Box key={i}
          onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(l); setHit(i); setTimeout(() => setHit((h) => (h === i ? -1 : h)), 1200) }}
          sx={{ px: 0.8, py: 0.1, mx: -0.8, borderRadius: 1, cursor: 'copy', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 2, '& .cp': { opacity: 0 }, '&:hover': { bgcolor: 'rgba(255,255,255,0.12)' }, '&:hover .cp': { opacity: 0.7 } }}>
          <span style={{ whiteSpace: 'pre' }}>{l}</span>
          <span className="cp" style={{ flexShrink: 0, fontSize: 11 }}>{hit === i ? '已复制' : '复制'}</span>
        </Box>
      ))}
    </Box>
  )
}

// 一项：名称 + 简短的文字 + 占用条 + 百分比；悬停显示 lines，每行可点复制
function Item({ label, value, sub, lines }: { label: string; value: number; sub: string; lines: string[] }) {
  return (
    <Tooltip title={<CopyLines lines={lines} />} placement="bottom-start">
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.7, minWidth: 0, flex: '0 1 auto', cursor: 'default' }}>
        <Typography noWrap sx={{ fontSize: 11.5, color: 'text.disabled', flexShrink: 0 }}>{label}</Typography>
        <Typography noWrap sx={{ fontSize: 12, color: 'text.secondary', flexShrink: 0 }}>{sub}</Typography>
        <Gauge value={value} />
        <Typography sx={{ fontSize: 11, color: 'text.disabled', flexShrink: 0, width: 38, textAlign: 'right' }}>{fmtPct(value)}%</Typography>
      </Box>
    </Tooltip>
  )
}

// 感叹号：悬停看 SSH 连接信息和系统信息（系统、架构、CPU 型号、更新时间），每行可点复制
export function SysInfoBadge({ info, addr }: { info: SysInfo | null; addr: string }) {
  const lines = [`SSH  ${addr}`]
  if (info?.ok && info.name) {
    lines.push(`系统  ${info.name}${info.arch ? ` · ${info.arch}` : ''}`)
    if (info.cpu?.model) lines.push(`CPU  ${info.cpu.model}`)
    if (info.at) lines.push(`更新于 ${hm(info.at)}`)
  }
  return (
    <Tooltip title={<CopyLines lines={lines} />} placement="bottom-start">
      <InfoOutlined sx={{ fontSize: 15, color: 'text.disabled', cursor: 'default', flexShrink: 0 }} />
    </Tooltip>
  )
}

const NL = String.fromCharCode(10)
// 状态栏（VS Code 底栏）里显示的几项：CPU / 内存 / 硬盘 / 数据卷（短文字 + 悬停说明）
export function statEntries(info: SysInfo | null): { id: string; text: string; tooltip: string }[] {
  if (!info?.ok) return []
  const linux = info.family === 'linux', cores = info.cpu?.cores || 0
  const out: { id: string; text: string; tooltip: string }[] = []
  out.push({ id: 'cpu', text: `$(pulse) CPU ${cores ? cores + (linux ? ' 核' : ' 线程') + ' ' : ''}${fmtPct(info.cpu?.usage || 0)}%`, tooltip: [info.cpu?.model || 'CPU 型号未知', `${cores} ${linux ? '核' : '线程'}`, `占用 ${fmtPct(info.cpu?.usage || 0)}%`].join(NL) })
  const mu = info.mem?.used || 0, mt = info.mem?.total || 0
  out.push({ id: 'mem', text: `内存 ${gib(mu)}/${gib(mt)} GB ${fmtPct(pct(mu, mt))}%`, tooltip: [`总量 ${gib(mt)} GB`, `已用 ${gib(mu)} GB${linux ? '（不含可回收的缓存）' : ''}`].join(NL) })
  const du = info.disk?.used || 0, dt = info.disk?.total || 0
  out.push({ id: 'disk', text: `硬盘 ${gib(du)}/${gib(dt)} GB ${fmtPct(pct(du, dt))}%`, tooltip: (linux
    ? [`总量 ${gib(dt)} GB`, `已用 ${gib(du)} GB`, '容器实例盘（容器删除即回收）', '已用量统计根目录，不含网络盘和只读的公共数据卷']
    : ['系统盘 C:', `型号：${info.disk?.model || '读不到'}`, `总量 ${gib(dt)} GB`, `已用 ${gib(du)} GB`]).join(NL) })
  if (info.volumes?.length) {
    const vols = info.volumes, vt = vols.reduce((a, v) => a + v.total, 0), vu = vols.reduce((a, v) => a + v.used, 0)
    out.push({ id: 'vol', text: `数据卷 ${gib(vu)}/${gib(vt)} GB ${fmtPct(pct(vu, vt))}%`, tooltip: vols.map((v) => [v.mount, mediaText(v.media), `${gib(v.used)}/${gib(v.total)} GB`, `${fmtPct(pct(v.used, v.total))}%`].filter(Boolean).join('  ')).join(NL) })
  }
  return out
}

// 底栏里的一行纯数字：CPU / 内存 / 硬盘 / 数据卷，不画占用条；悬停看详情（点一行可复制）
export function StatStrip({ info }: { info: SysInfo | null }) {
  const es = statEntries(info)
  if (!es.length) return null
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexShrink: 0 }}>
      {es.map((e) => (
        <Tooltip key={e.id} placement="top-end" title={<CopyLines lines={e.tooltip.split(NL)} />}>
          <span style={{ whiteSpace: 'nowrap', cursor: 'default' }}>{e.text.replace(/^\$\([a-z-]+\)\s*/, '')}</span>
        </Tooltip>
      ))}
    </Box>
  )
}

export default function SysInfoBar({ alias, connected, info, setInfo, hidden }: { alias: string; connected: boolean; info: SysInfo | null; setInfo: (i: SysInfo | null) => void; hidden?: boolean }) {
  const [busy, setBusy] = useState(false)
  const aliasRef = useRef(alias)
  aliasRef.current = alias

  // 手动刷新，或者需要时后台刷新。结果只在还停在这台主机上时才显示，但都会写进缓存
  const load = () => {
    if (!connected) return
    const cur = alias
    setBusy(true)
    api.ssh_sysinfo(cur)
      .then((r: SysInfo) => {
        if (r?.ok) {
          const e = { ...r, at: Date.now() }
          writeCache(cur, e)
          if (aliasRef.current === cur) setInfo(e)
        } else if (aliasRef.current === cur && !readCache(cur)?.ok) {
          setInfo(r)                                   // 没有旧数据时才显示错误；有旧数据就保留旧的
        }
      })
      .catch((e: any) => { if (aliasRef.current === cur && !readCache(cur)?.ok) setInfo({ ok: false, error: String(e) }) })
      .finally(() => { if (aliasRef.current === cur) setBusy(false) })
  }

  // 换主机：先用缓存顶上；缓存没有或超过 5 分钟，才在后台读一次
  useEffect(() => {
    const c = readCache(alias)
    setInfo(c ?? null)
    if (!connected) return
    if (!c || !c.at || Date.now() - c.at > FRESH_MS) load()
  }, [alias, connected])

  if (!connected || hidden) return null          // hidden：只负责读取/缓存（结果显示在 VS Code 底栏里）
  const linux = info?.family === 'linux'
  const cores = info?.cpu?.cores || 0
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2.5, minWidth: 0, flex: '0 1 auto', overflow: 'hidden' }}>
      {busy && !info && <Typography sx={{ fontSize: 12, color: 'text.disabled' }}>正在读取系统信息…</Typography>}
      {info && !info.ok && <Typography sx={{ fontSize: 12, color: 'error.main', flex: 1, minWidth: 0 }} noWrap>读取系统信息失败：{info.error}</Typography>}
      {info?.ok && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2.5, minWidth: 0, flex: 1, overflow: 'hidden' }}>
          <Item label="CPU" value={info.cpu?.usage || 0}
            sub={cores ? `${cores} ${linux ? '核' : '线程'}` : '—'}
            lines={[info.cpu?.model || '型号未知', `${cores} ${linux ? '核' : '线程'}`, `占用 ${fmtPct(info.cpu?.usage || 0)}%`]} />
          <Item label="内存" value={pct(info.mem?.used || 0, info.mem?.total || 0)} sub={`${gib(info.mem?.used || 0)}/${gib(info.mem?.total || 0)} GB`}
            lines={[`总量 ${gib(info.mem?.total || 0)} GB`, `已用 ${gib(info.mem?.used || 0)} GB${linux ? '（不含可回收的缓存）' : ''}`]} />
          {linux ? (
            <Item label="硬盘" value={pct(info.disk?.used || 0, info.disk?.total || 0)} sub={`${gib(info.disk?.used || 0)}/${gib(info.disk?.total || 0)} GB`}
              lines={[`总量 ${gib(info.disk?.total || 0)} GB`, `已用 ${gib(info.disk?.used || 0)} GB`, '容器实例盘（容器删除即回收）', '已用量统计根目录，不含网络盘和只读的公共数据卷']} />
          ) : (
            <Item label="硬盘" value={pct(info.disk?.used || 0, info.disk?.total || 0)} sub={`${gib(info.disk?.used || 0)}/${gib(info.disk?.total || 0)} GB`}
              lines={['系统盘 C:', `型号：${info.disk?.model || '读不到'}`, `总量 ${gib(info.disk?.total || 0)} GB`, `已用 ${gib(info.disk?.used || 0)} GB`]} />
          )}
          {!!info.volumes?.length && (() => {
            // 挂载卷合并成一项：总容量；悬停时每个卷占一行（只显示盘类型，不显示文件系统格式）
            const vols = info.volumes!
            const vt = vols.reduce((s, v) => s + v.total, 0), vu = vols.reduce((s, v) => s + v.used, 0)
            const lines = vols.map((v) => [v.mount, mediaText(v.media), `${gib(v.used)}/${gib(v.total)} GB`, `${fmtPct(pct(v.used, v.total))}%`].filter(Boolean).join('  '))
            return <Item label="数据卷" value={pct(vu, vt)} sub={`${gib(vu)}/${gib(vt)} GB`} lines={lines} />
          })()}
        </Box>
      )}
    </Box>
  )
}
