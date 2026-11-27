// 主机的系统信息：感叹号里是 SSH 地址和系统、CPU 型号；一行是 CPU / 内存 / 硬盘 / 数据卷的占用。
// 结果会缓存（切走再切回来不用重新读）；超过 5 分钟才在打开时后台刷新一次，也可以手动点刷新。
import CloudOutlined from '@mui/icons-material/CloudOutlined'
import DeveloperBoardRounded from '@mui/icons-material/DeveloperBoardRounded'
import InfoOutlined from '@mui/icons-material/InfoOutlined'
import MemoryRounded from '@mui/icons-material/MemoryRounded'
import StorageRounded from '@mui/icons-material/StorageRounded'
import { Box, Tooltip } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'

export type SysInfo = {
  ok: boolean; error?: string; family?: 'linux' | 'windows'; name?: string; arch?: string; at?: number
  cpu?: { model: string; cores: number; usage: number }
  mem?: { total: number; used: number }
  container?: boolean; gpus?: number
  disks?: { kind: 'system' | 'mount' | 'cloud'; mount: string; total: number; used: number; nominal?: boolean }[]      // system 系统盘；mount 挂载盘（本地盘、/data0 这类）；cloud 云盘
  cloudPath?: string                       // 云盘的挂载目录（有就默认打开它）
}

const FRESH_MS = 5 * 60 * 1000                       // 缓存超过这么久，打开主机时后台刷新一次

const gib = (b: number) => { const x = b / 1073741824; return x >= 10 ? x.toFixed(0) : x.toFixed(1) }
const pct = (used: number, total: number) => (total > 0 ? Math.max(0, Math.min(100, Math.round((used / total) * 100))) : 0)
// 占用百分比：小于 10% 保留一位小数，免得小数值全显示成 0%
const fmtPct = (v: number) => (v < 10 ? v.toFixed(1) : String(Math.round(v)))
const hm = (t: number) => new Date(t).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })

// ---- 缓存：内存里一份，同时存到 localStorage（重启应用也还在）
const memCache = new Map<string, SysInfo>()
const KEY = (alias: string) => `sysinfo:${alias}`
function readCache(alias: string): SysInfo | null {
  const m = memCache.get(alias)
  if (m) return m.ok && !m.disks ? null : m
  try {
    const raw = localStorage.getItem(KEY(alias))
    if (!raw) return null
    const v = JSON.parse(raw) as SysInfo
    if (v.ok && !v.disks) return null            // 旧版缓存里没有分盘信息
    memCache.set(alias, v)
    return v
  } catch { return null }
}
function writeCache(alias: string, info: SysInfo) {
  memCache.set(alias, info)
  try { localStorage.setItem(KEY(alias), JSON.stringify(info)) } catch { /* 存不下就只留内存里 */ }
}

// 悬停提示：一行一行的文字（不带复制）
function CopyLines({ lines, table }: { lines: string[]; table?: string[][] }) {
  return (
    <Box sx={{ fontSize: 12, lineHeight: 1.7 }}>
      {!!table?.length && (
        <Box sx={{ display: 'grid', gridTemplateColumns: 'auto auto auto auto', columnGap: 1.6, mb: lines.length ? 0.4 : 0 }}>
          {table.map((r, i) => r.map((c, j) => <Box key={i + '-' + j} sx={{ whiteSpace: 'pre', textAlign: j >= 2 ? 'right' : 'left', fontVariantNumeric: 'tabular-nums' }}>{c}</Box>))}
        </Box>
      )}
      {lines.map((l, i) => <Box key={i} sx={{ whiteSpace: 'pre' }}>{l}</Box>)}
    </Box>
  )
}

// 感叹号：悬停看 SSH 连接信息和系统信息（系统、架构、CPU 型号、更新时间）
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
type Entry = { id: string; icon: React.ReactNode; label: string; text: string; lines: string[]; table?: string[][] }      // table：悬停里按列对齐的行（名称 / 路径 / 用量 / 百分比）
// 底栏里的几项：CPU / 内存 / 磁盘（系统盘 + 挂载盘） / 云盘。短文字 + 悬停说明
export function statEntries(info: SysInfo | null): Entry[] {
  if (!info?.ok) return []
  const linux = info.family === 'linux', cores = info.cpu?.cores || 0
  const out: Entry[] = []
  const ic = { fontSize: 14, opacity: 0.8, mr: 0.4, verticalAlign: '-2px' }
  out.push({ id: 'cpu', icon: <MemoryRounded sx={ic} />, label: 'CPU', text: `${cores ? cores + (linux ? ' 核 ' : ' 线程 ') : ''}${fmtPct(info.cpu?.usage || 0)}%`, lines: [] })
  const mu = info.mem?.used || 0, mt = info.mem?.total || 0
  out.push({ id: 'mem', icon: <DeveloperBoardRounded sx={ic} />, label: '内存', text: `${gib(mu)}/${gib(mt)} GB ${fmtPct(pct(mu, mt))}%`, lines: [] })
  const ds = info.disks || []
  const local = ds.filter((d) => d.kind !== 'cloud'), cloud = ds.filter((d) => d.kind === 'cloud')
  const row = (d: NonNullable<SysInfo['disks']>[number]) => [d.kind === 'system' ? '系统盘' : d.kind === 'cloud' ? '云盘' : '挂载盘', d.mount, `${gib(d.used)}/${gib(d.total)} GB`, `${fmtPct(pct(d.used, d.total))}%`]
  if (local.length) {
    const lt = local.reduce((a, d) => a + d.total, 0), lu = local.reduce((a, d) => a + d.used, 0)
    out.push({ id: 'disk', icon: <StorageRounded sx={ic} />, label: '磁盘', text: `${gib(lu)}/${gib(lt)} GB ${fmtPct(pct(lu, lt))}%`, lines: info.container ? ['实例销毁后自动回收'] : [], table: local.map(row) })
  }
  if (cloud.length) {
    const ct = cloud.reduce((a, d) => a + d.total, 0), cu = cloud.reduce((a, d) => a + d.used, 0)
    out.push({ id: 'cloud', icon: <CloudOutlined sx={ic} />, label: '云盘', text: `${gib(cu)}/${gib(ct)} GB ${fmtPct(pct(cu, ct))}%`, lines: ['实例销毁后不回收'], table: cloud.map(row) })
  }
  return out
}

// 底栏里的一行：图标 + 名称 + 数字，不画占用条；悬停看详情
export function StatStrip({ info }: { info: SysInfo | null }) {
  const es = statEntries(info)
  if (!es.length) return null
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2.2, flexShrink: 0 }}>
      {es.map((e) => {
        const body = <span style={{ whiteSpace: 'nowrap', cursor: 'default' }}>{e.icon}{e.label} {e.text}</span>
        return e.lines.length || e.table?.length ? <Tooltip key={e.id} placement="top-end" title={<CopyLines lines={e.lines} table={e.table} />}>{body}</Tooltip> : <span key={e.id}>{body}</span>
      })}
    </Box>
  )
}

export default function SysInfoBar({ alias, connected, setInfo }: { alias: string; connected: boolean; info?: SysInfo | null; setInfo: (i: SysInfo | null) => void; hidden?: boolean }) {
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

  return null          // 只负责读取/缓存；显示在资源管理器下面的状态栏里（StatStrip）
}
