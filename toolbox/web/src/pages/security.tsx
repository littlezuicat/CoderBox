// 设备安全：检查本机出口 IP 的质量、DNS/WebRTC 泄露、Claude 相关服务可用性、时区和语言是否协调。
// 检测思路取自 ip.net.coffee/claude：网络数据由 Python 后端（majing/core/devsec.py）取，WebRTC 和设备环境在这里（WebView2）里测，
// “通过 / 注意 / 未通过”的判断都在这个文件里。
import CancelRounded from '@mui/icons-material/CancelRounded'
import CheckCircleRounded from '@mui/icons-material/CheckCircleRounded'
import DevicesOutlined from '@mui/icons-material/DevicesOutlined'
import DnsOutlined from '@mui/icons-material/DnsOutlined'
import HelpOutlineRounded from '@mui/icons-material/HelpOutlineRounded'
import PublicRounded from '@mui/icons-material/PublicRounded'
import RefreshRounded from '@mui/icons-material/RefreshRounded'
import RouterOutlined from '@mui/icons-material/RouterOutlined'
import ShieldOutlined from '@mui/icons-material/ShieldOutlined'
import WarningAmberRounded from '@mui/icons-material/WarningAmberRounded'
import { Box, Button, Chip, CircularProgress, IconButton, LinearProgress, Tooltip, Typography } from '@mui/material'
import type { ReactElement } from 'react'
import { useRef, useState } from 'react'

import { api } from '../bridge'
import { BasePage } from '../components/base-page'
import { rounded } from '../components/common'
import { EnhancedCard } from '../components/enhanced-card'

type St = 'idle' | 'run' | 'pass' | 'warn' | 'fail' | 'info' | 'unknown'      // idle = 还没检测（不自动检测，用户点“开始检测”才跑）
type Item = { state: St; text: string; sub?: string }

const GROUPS: { key: 'exit' | 'quality' | 'leak' | 'avail' | 'env'; title: string; icon: ReactElement; ids: string[] }[] = [
  { key: 'exit', title: '出口 IP', icon: <PublicRounded />, ids: ['cn', 'cf', 'claude'] },
  { key: 'quality', title: 'IP 质量（Claude 出口）', icon: <ShieldOutlined />, ids: ['trust', 'region', 'kind', 'vpn', 'proxy', 'tor', 'crawler', 'abuse'] },
  { key: 'leak', title: '泄露检测', icon: <DnsOutlined />, ids: ['dns', 'webrtc'] },
  { key: 'avail', title: '服务可用性', icon: <RouterOutlined />, ids: ['site_claude', 'site_anthropic', 'status'] },
  { key: 'env', title: '设备环境', icon: <DevicesOutlined />, ids: ['tz', 'lang', 'cookie'] },
]
const LABEL: Record<string, string> = {
  cn: '国内出口', cf: 'Cloudflare 出口', claude: 'Claude 出口',
  trust: '信任评分', region: '所在地区', kind: 'IP 类型', vpn: 'VPN', proxy: '代理', tor: 'Tor', crawler: '爬虫标记', abuse: '滥用记录',
  dns: 'DNS 泄露', webrtc: 'WebRTC 泄露',
  site_claude: 'claude.ai', site_anthropic: 'anthropic.com', status: 'Claude 服务状态',
  tz: '时区', lang: '语言', cookie: 'Cookie',
}
const ALL = GROUPS.flatMap((g) => g.ids)
const TOTAL = ALL.length          // 检测项总数（固定）：出口 3 + IP 质量 8 + 泄露 2 + 可用性 3 + 设备环境 3

// Claude 不开放或严格风控的地区
const RESTRICTED: Record<string, string> = { CN: '中国大陆', HK: '香港', MO: '澳门', RU: '俄罗斯', KP: '朝鲜', IR: '伊朗', SY: '叙利亚', CU: '古巴', BY: '白俄罗斯', VE: '委内瑞拉' }
const CC_TZ: Record<string, string> = {
  CN: 'Asia/Shanghai', TW: 'Asia/Taipei', HK: 'Asia/Hong_Kong', MO: 'Asia/Macau', JP: 'Asia/Tokyo', KR: 'Asia/Seoul', SG: 'Asia/Singapore', MY: 'Asia/Kuala_Lumpur', TH: 'Asia/Bangkok',
  VN: 'Asia/Ho_Chi_Minh', ID: 'Asia/Jakarta', PH: 'Asia/Manila', IN: 'Asia/Kolkata', PK: 'Asia/Karachi', BD: 'Asia/Dhaka', IR: 'Asia/Tehran', IL: 'Asia/Jerusalem', AE: 'Asia/Dubai',
  SA: 'Asia/Riyadh', TR: 'Europe/Istanbul', RU: 'Europe/Moscow', UA: 'Europe/Kyiv', GB: 'Europe/London', IE: 'Europe/Dublin', FR: 'Europe/Paris', DE: 'Europe/Berlin', IT: 'Europe/Rome',
  ES: 'Europe/Madrid', PT: 'Europe/Lisbon', NL: 'Europe/Amsterdam', BE: 'Europe/Brussels', CH: 'Europe/Zurich', AT: 'Europe/Vienna', SE: 'Europe/Stockholm', NO: 'Europe/Oslo',
  DK: 'Europe/Copenhagen', FI: 'Europe/Helsinki', PL: 'Europe/Warsaw', CZ: 'Europe/Prague', GR: 'Europe/Athens', RO: 'Europe/Bucharest', US: 'America/Los_Angeles', CA: 'America/Toronto',
  MX: 'America/Mexico_City', BR: 'America/Sao_Paulo', AR: 'America/Argentina/Buenos_Aires', CL: 'America/Santiago', AU: 'Australia/Sydney', NZ: 'Pacific/Auckland',
  ZA: 'Africa/Johannesburg', EG: 'Africa/Cairo', NG: 'Africa/Lagos', KE: 'Africa/Nairobi',
}
const CC_LANG: Record<string, string[]> = {
  CN: ['zh'], TW: ['zh'], HK: ['zh', 'en'], MO: ['zh', 'en'], JP: ['ja'], KR: ['ko'], TH: ['th'], VN: ['vi'], SG: ['en', 'zh', 'ms', 'ta'], MY: ['ms', 'en', 'zh', 'ta'], ID: ['id', 'en'],
  PH: ['en', 'tl', 'fil'], IN: ['en', 'hi'], PK: ['ur', 'en'], BD: ['bn', 'en'], US: ['en'], GB: ['en'], IE: ['en', 'ga'], AU: ['en'], NZ: ['en', 'mi'], CA: ['en', 'fr'],
  DE: ['de'], AT: ['de'], CH: ['de', 'fr', 'it', 'rm'], BE: ['nl', 'fr', 'de'], FR: ['fr'], IT: ['it'], ES: ['es', 'ca', 'gl', 'eu'], PT: ['pt'], NL: ['nl', 'fy'],
  SE: ['sv'], NO: ['no', 'nb', 'nn'], DK: ['da'], FI: ['fi', 'sv'], PL: ['pl'], CZ: ['cs'], GR: ['el'], RO: ['ro'], RU: ['ru'], UA: ['uk', 'ru'], TR: ['tr'],
  IL: ['he', 'ar', 'en'], SA: ['ar'], AE: ['ar', 'en'], EG: ['ar'], IR: ['fa'], ZA: ['en', 'af', 'zu', 'xh'], KE: ['en', 'sw'], NG: ['en'], BR: ['pt'], AR: ['es'], MX: ['es'], CL: ['es'],
}

// 某个时区“现在”的 UTC 偏移（分钟，已含夏令时）；名字无效返回 null
function offsetMinutes(tz: string): number | null {
  try {
    const p = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'longOffset' }).formatToParts(new Date()).find((x) => x.type === 'timeZoneName')
    if (!p) return null
    if (p.value === 'GMT' || p.value === 'UTC') return 0
    const m = p.value.match(/GMT([+-])(\d{1,2}):?(\d{0,2})/)
    return m ? (m[1] === '+' ? 1 : -1) * (parseInt(m[2], 10) * 60 + parseInt(m[3] || '0', 10)) : null
  } catch { return null }
}
const fmtOff = (m: number) => `UTC${m >= 0 ? '+' : '-'}${Math.floor(Math.abs(m) / 60)}${Math.abs(m) % 60 ? ':' + String(Math.abs(m) % 60).padStart(2, '0') : ''}`

// WebRTC：用 STUN 收集本机“看到的”地址，返回公网 IPv4
function webrtcIPs(): Promise<string[]> {
  return new Promise((resolve) => {
    const found = new Set<string>()
    let pc: RTCPeerConnection | null = null
    const done = () => { try { pc?.close() } catch { /* */ } resolve([...found]) }
    try {
      pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }, { urls: 'stun:stun.cloudflare.com:3478' }] })
      pc.createDataChannel('')
      const t = setTimeout(done, 5000)
      pc.onicecandidate = (e) => {
        if (!e.candidate) { clearTimeout(t); done(); return }
        const m = e.candidate.candidate.match(/([0-9]{1,3}\.){3}[0-9]{1,3}/)
        if (m) found.add(m[0])
      }
      pc.createOffer().then((o) => pc!.setLocalDescription(o)).catch(done)
    } catch { resolve([]) }
  }).then((all: any) => (all as string[]).filter((ip) => !/^(0\.|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|198\.1[89]\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|169\.254\.)/.test(ip)))
}

const ICON: Record<St, ReactElement> = {
  idle: <HelpOutlineRounded sx={{ fontSize: 20, color: 'text.disabled' }} />,
  run: <CircularProgress size={18} />,
  pass: <CheckCircleRounded sx={{ fontSize: 20, color: 'success.main' }} />,
  warn: <WarningAmberRounded sx={{ fontSize: 20, color: 'warning.main' }} />,
  fail: <CancelRounded sx={{ fontSize: 20, color: 'error.main' }} />,
  info: <PublicRounded sx={{ fontSize: 20, color: 'text.disabled' }} />,
  unknown: <HelpOutlineRounded sx={{ fontSize: 20, color: 'text.disabled' }} />,
}

type GKey = 'exit' | 'quality' | 'leak' | 'avail' | 'env'
const GKEYS: GKey[] = ['exit', 'quality', 'leak', 'avail', 'env']
const QUALITY_IDS = ['trust', 'region', 'kind', 'vpn', 'proxy', 'tor', 'crawler', 'abuse']
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export default function SecurityPage({ active }: { active?: boolean }) {
  const [items, setItems] = useState<Record<string, Item>>(() => Object.fromEntries(ALL.map((k) => [k, { state: 'idle' as St, text: '' }])))
  const [runningKeys, setRunningKeys] = useState<GKey[]>([])
  const [at, setAt] = useState<number | null>(null)
  const [fixing, setFixing] = useState<string | null>(null)
  const [fixMsg, setFixMsg] = useState<Record<string, { ok: boolean; text: string }>>({})
  const runningRef = useRef(new Set<GKey>())
  // 各分组共用的数据：出口 IP、Claude 出口的地区/时区（单项重测时直接用已有的）
  const ctx = useRef<{ ipsP: Promise<any> | null; qP: Promise<any> | null; cc: string; tz: string }>({ ipsP: null, qP: null, cc: '', tz: '' })

  const set = (id: string, state: St, text: string, sub?: string) => setItems((m) => ({ ...m, [id]: { state, text, sub } }))
  const ensureIps = (): Promise<any> => {
    if (!ctx.current.ipsP) ctx.current.ipsP = api.devsec_exit_ips().then((ex: any) => (ex?.ok ? ex.data : {}))
    return ctx.current.ipsP
  }
  const ccOf = (ips: any) => ctx.current.cc || String(ips?.claude?.loc || '').toUpperCase()

  const GROUP_RUN: Record<GKey, () => Promise<void>> = {
    // 出口 IP：能取到 IP 就算通过
    exit: async () => {
      ctx.current.ipsP = null
      const ips = await ensureIps()
      const cnIp = ips.cn?.ip, cfIp = ips.cf?.ip, clIp = ips.claude?.ip
      set('cn', cnIp ? 'pass' : 'unknown', cnIp || '没取到', ips.cn?.source ? `来源 ${ips.cn.source}` : undefined)
      set('cf', cfIp ? 'pass' : 'unknown', cfIp || '没取到')
      set('claude', clIp ? 'pass' : 'fail', clIp || '没取到（连不上 claude.ai）')
      await Promise.all([['cn', cnIp], ['cf', cfIp], ['claude', clIp]].filter(([, ip]) => ip).map(async ([id, ip]) => {
        const g = await api.devsec_geoip(ip as string)
        const d = g?.ok ? g.data : null
        if (d) setItems((m) => ({ ...m, [id as string]: { ...m[id as string], sub: [d.country, d.region, d.city, d.isp].filter(Boolean).join(' ') } }))
      }))
    },
    // IP 质量（Claude 出口）
    quality: () => {
      const p = (async () => {
        const ips = await ensureIps()
        const clIp = ips.claude?.ip
        if (!clIp) { for (const id of QUALITY_IDS) set(id, 'unknown', '没拿到 Claude 出口 IP'); return }
        const rk = await api.devsec_risk(clIp)
        if (!rk?.ok) { for (const id of QUALITY_IDS) set(id, 'unknown', 'IP 信息服务没响应'); return }
        const d = rk.data
        const cc = String(d.countryCode || ips.claude?.loc || '').toUpperCase()
        ctx.current.cc = cc; ctx.current.tz = d.timezone || ''
        const restricted = RESTRICTED[cc]
        const score = typeof d.trust_score === 'number' ? d.trust_score : null
        if (restricted) set('trust', 'fail', '0 分 · 处于不可访问地区')
        else if (score === null) set('trust', 'unknown', '暂无评分数据')
        else set('trust', score >= 50 ? 'pass' : score >= 25 ? 'warn' : 'fail', `${score} 分 · ${score >= 95 ? '极度纯净' : score >= 80 ? '纯净' : score >= 50 ? '良好' : score >= 25 ? '中性' : '可疑'}`)
        set('region', restricted ? 'fail' : cc ? 'pass' : 'unknown', restricted ? `位于${restricted}，Claude 会严格风控` : cc ? `${d.country || cc} · 在支持地区` : '未知', [d.city, d.region].filter(Boolean).join(' '))
        set('kind', d.isResidential === true ? 'pass' : d.isResidential === false ? 'warn' : 'unknown',
          d.isResidential === true ? '家庭住宅 IP' : d.isResidential === false ? `机房 IP${d.company_type ? '（' + d.company_type + '）' : ''}` : '未知', d.asn ? `AS${d.asn} ${d.asOrganization || ''}` : undefined)
        const flag = (id: string, v: any, bad: string, good: string, badState: St = 'fail') => set(id, v === true ? badState : v === false ? 'pass' : 'unknown', v === true ? bad : v === false ? good : '未知')
        flag('vpn', d.is_vpn, '被识别为 VPN', '未检测到'); flag('proxy', d.is_proxy, '被识别为代理', '未检测到'); flag('tor', d.is_tor, 'Tor 出口', '未检测到')
        flag('crawler', d.is_crawler, '被标记为爬虫', '否', 'warn'); flag('abuse', d.is_abuser, `有记录${d.abuser_score ? '（' + d.abuser_score + '）' : ''}`, '无记录', 'warn')
      })()
      ctx.current.qP = p
      return p
    },
    // 泄露检测：DNS + WebRTC
    leak: async () => {
      const pDns = api.devsec_dns(), pRtc = webrtcIPs()
      const ips = await ensureIps()
      const clIp = ips.claude?.ip
      const dns = await pDns
      if (!dns?.ok) set('dns', 'unknown', '检测没成功')
      else {
        const sv: any[] = dns.data.servers || []
        const leakSv = sv.find((s) => s.country_code === 'cn')
        if (!sv.length) set('dns', 'pass', 'DNS 加密或未暴露出口', dns.data.resolved?.length ? `解析到 ${dns.data.resolved[0]}` : undefined)
        else if (leakSv && ccOf(ips) !== 'CN') set('dns', 'fail', `可能泄露：中国 DNS ${leakSv.ip}`, leakSv.isp)
        else set('dns', 'pass', `未检测到泄露 · ${sv[0].ip}`, sv[0].isp)
      }
      const rtc = await pRtc
      if (!rtc.length) set('webrtc', 'pass', 'WebRTC 已禁用或无泄露')
      else if (!clIp) set('webrtc', 'unknown', `看到 ${rtc[0]}，但没有 Claude 出口 IP 可对比`)
      else { const lk = rtc.find((ip) => ip !== clIp); set('webrtc', lk ? 'fail' : 'pass', lk ? `可能泄露：${lk} 与 Claude 出口不同` : '未检测到泄露', `UDP 出口 ${rtc.join('、')}`) }
    },
    // 服务可用性：能访问就算通过（慢一点也算）
    avail: async () => {
      const av = await api.devsec_avail()
      if (!av?.ok) { set('site_claude', 'unknown', '检测没成功'); set('site_anthropic', 'unknown', '检测没成功'); set('status', 'unknown', '未知'); return }
      for (const s of av.data.sites as any[]) {
        const id = s.name === 'claude.ai' ? 'site_claude' : 'site_anthropic'
        if (!s.ok) set(id, 'fail', '不可访问')
        else set(id, 'pass', `可访问 · ${s.ms} ms${s.ms >= 500 ? '（较慢）' : ''}`)
      }
      const st = av.data.status
      const T: Record<string, [St, string]> = { none: ['pass', '全部服务正常'], minor: ['warn', '轻微故障'], major: ['fail', '重大故障'], critical: ['fail', '严重故障'], maintenance: ['warn', '维护中'] }
      set('status', st ? (T[st]?.[0] || 'warn') : 'unknown', st ? (T[st]?.[1] || '服务异常') : '未知')
    },
    // 设备环境：时区 / 语言 / Cookie
    env: async () => {
      if (ctx.current.qP) await ctx.current.qP.catch(() => { /* */ })
      const ips = await ensureIps()
      const cc = ccOf(ips)
      const localTz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''
      const localOff = -new Date().getTimezoneOffset()
      const clTz = ctx.current.tz || CC_TZ[cc] || ''
      const clOff = clTz ? offsetMinutes(clTz) : null
      const sub = clOff != null ? `本地 ${localTz}（${fmtOff(localOff)}）· Claude 出口 ${clTz}${ctx.current.tz ? '' : '（按地区估算）'}（${fmtOff(clOff)}）` : `本地 ${localTz}（${fmtOff(localOff)}）`
      if (localTz === 'Asia/Shanghai' || localTz === 'Asia/Urumqi') set('tz', 'warn', '不推荐使用中国大陆时区', sub)
      else if (clOff == null) set('tz', 'unknown', `${localTz}（${fmtOff(localOff)}）`)
      else set('tz', Math.abs(clOff - localOff) <= 60 ? 'pass' : 'warn', Math.abs(clOff - localOff) <= 60 ? '时区一致' : '时区不一致', sub)
      const langs = navigator.languages?.length ? [...navigator.languages] : [navigator.language]
      const primary = (langs[0] || '').split('-')[0].toLowerCase()
      const want = CC_LANG[cc] || []
      if (primary && want.length) set('lang', want.includes(primary) ? 'pass' : 'warn', want.includes(primary) ? '语言一致' : '语言不一致', `本地 ${langs.join(', ')} · 出口地区常用 ${want.join(' / ')}`)
      else set('lang', 'unknown', langs.join(', '))
      set('cookie', navigator.cookieEnabled ? 'pass' : 'warn', navigator.cookieEnabled ? '已启用' : '已禁用')
    },
  }

  const syncRunning = () => setRunningKeys([...runningRef.current])
  // 跑一个分组（单项重测和整体检测共用）
  const runGroup = async (key: GKey) => {
    if (runningRef.current.has(key)) return
    runningRef.current.add(key); syncRunning()
    const g = GROUPS.find((x) => x.key === key)!
    setItems((m) => ({ ...m, ...Object.fromEntries(g.ids.map((id) => [id, { state: 'run' as St, text: '' }])) }))
    try { await GROUP_RUN[key]() } catch (e: any) {
      api.log_js('error', `设备安全检测出错（${key}）：` + (e?.stack || e))
      setItems((m) => ({ ...m, ...Object.fromEntries(g.ids.filter((id) => m[id].state === 'run').map((id) => [id, { state: 'unknown' as St, text: '检测出错' }])) }))
    } finally { runningRef.current.delete(key); syncRunning(); setAt(Date.now()) }
  }
  const runAll = async () => {
    if (runningRef.current.size) return
    ctx.current = { ipsP: null, qP: null, cc: '', tz: '' }
    setFixMsg({})
    await Promise.all(GKEYS.map(runGroup))
  }
  const fix = async (id: 'dns' | 'webrtc') => {
    setFixing(id)
    const r = await api.devsec_fix(id)
    setFixing(null)
    setFixMsg((m) => ({ ...m, [id]: { ok: !!r?.ok, text: r?.ok ? r.data?.msg || '已修复' : r?.error || '修复没成功' } }))
    if (r?.ok) { await sleep(id === 'dns' ? 3500 : 2500); runGroup('leak') }
  }

  // 不自动检测：检测会把出口 IP 发给第三方站点，等用户自己点“开始检测”（或某一项右上角的刷新）
  const running = runningKeys.length > 0
  const vals = ALL.map((id) => items[id])
  const idleAll = vals.every((v) => v.state === 'idle')
  const count = (s: St) => vals.filter((v) => v.state === s).length
  const pass = count('pass'), warn = count('warn'), fail = count('fail')
  const allPass = pass === TOTAL
  const tone = allPass ? 'success.main' : fail ? 'error.main' : warn ? 'warning.main' : 'text.primary'

  return (
    <BasePage title="设备安全" info="检查这台电脑当前的出口 IP 质量、DNS / WebRTC 泄露、Claude 相关服务能否访问，以及时区、语言是否协调。数据来自 ip.net.coffee：检测时会把出口 IP 发给该站点。"
      header={<Button variant="outlined" size="small" startIcon={<RefreshRounded />} sx={rounded} disabled={running} onClick={runAll}>{running ? '检测中…' : idleAll && !at ? '开始检测' : '重新检测'}</Button>}>
      <EnhancedCard title="检测结果" icon={allPass ? <CheckCircleRounded color="success" /> : <ShieldOutlined />} action={at && !running ? <Typography variant="caption" color="text.secondary">{new Date(at).toLocaleTimeString('zh-CN', { hour12: false })} 完成</Typography> : null}>
        <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1.5, flexWrap: 'wrap' }}>
          {idleAll && !running
            ? <Typography sx={{ fontSize: 22, fontWeight: 700, color: 'text.secondary', lineHeight: 1.6 }}>尚未检测 · 点右上角“开始检测”</Typography>
            : <Typography sx={{ fontSize: 30, fontWeight: 800, color: tone, lineHeight: 1.2 }}>已通过 {pass} / {TOTAL}</Typography>}
          {allPass && <Typography sx={{ fontWeight: 700, color: 'success.main' }}>全部通过</Typography>}
          {warn > 0 && <Chip size="small" color="warning" variant="outlined" label={`${warn} 项注意`} sx={{ fontWeight: 700 }} />}
          {fail > 0 && <Chip size="small" color="error" variant="outlined" label={`${fail} 项未通过`} sx={{ fontWeight: 700 }} />}
        </Box>
        {running && <LinearProgress variant="determinate" value={Math.max(4, (vals.filter((v) => v.state !== 'run').length * 100) / TOTAL)} sx={{ mt: 1.2, borderRadius: 2, '& .MuiLinearProgress-bar': { transition: 'transform .3s' } }} />}
      </EnhancedCard>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0,1fr)', md: 'repeat(2, minmax(0,1fr))' }, gap: 1.5, mt: 1.5, alignItems: 'start' }}>
        {GROUPS.map((g) => {
          const gRun = runningKeys.includes(g.key)
          return (
            <EnhancedCard key={g.key} title={g.title} icon={g.icon}
              action={<Tooltip title="重新检测这一项"><span><IconButton size="small" disabled={gRun} onClick={() => runGroup(g.key)}><RefreshRounded fontSize="small" /></IconButton></span></Tooltip>}>
              {g.ids.map((id, i) => {
                const it = items[id]
                const canFix = (id === 'dns' || id === 'webrtc') && it.state === 'fail'
                const fm = fixMsg[id]
                return (
                  <Box key={id} sx={{ display: 'grid', gridTemplateColumns: '26px 124px minmax(0,1fr)', alignItems: 'start', columnGap: 0.5, py: 0.9, borderTop: i ? 1 : 0, borderColor: 'divider' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', height: 22, width: 26, contain: 'strict' }}>{ICON[it.state]}</Box>
                    <Typography sx={{ fontSize: 13.5, fontWeight: 600, lineHeight: '22px' }} noWrap>{LABEL[id]}</Typography>
                    <Box sx={{ minWidth: 0 }}>
                      <Typography sx={{ fontSize: 13.5, lineHeight: '22px', userSelect: 'text', wordBreak: 'break-all' }} color={it.state === 'fail' ? 'error.main' : it.state === 'warn' ? 'warning.main' : it.state === 'idle' ? 'text.disabled' : 'text.primary'}>{it.state === 'run' ? '检测中…' : it.state === 'idle' ? '未检测' : it.text}</Typography>
                      {it.sub && it.state !== 'run' && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.5, userSelect: 'text', wordBreak: 'break-all' }}>{it.sub}</Typography>}
                      {canFix && <Button size="small" variant="contained" disableElevation sx={{ ...rounded, mt: 0.6 }} disabled={fixing === id} onClick={() => fix(id as 'dns' | 'webrtc')}>{fixing === id ? '修复中…' : '一键修复'}</Button>}
                      {fm && it.state !== 'run' && <Typography variant="caption" color={fm.ok ? 'success.main' : 'error.main'} sx={{ display: 'block', lineHeight: 1.5, mt: 0.4, wordBreak: 'break-all' }}>{fm.text}</Typography>}
                    </Box>
                  </Box>
                )
              })}
            </EnhancedCard>
          )
        })}
      </Box>
    </BasePage>
  )
}
