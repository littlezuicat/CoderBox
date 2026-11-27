import LinkOffOutlined from '@mui/icons-material/LinkOffOutlined'
import PersonOutline from '@mui/icons-material/PersonOutline'
import PaletteOutlined from '@mui/icons-material/PaletteOutlined'
import DownloadOutlined from '@mui/icons-material/DownloadOutlined'
import FolderOutlined from '@mui/icons-material/FolderOutlined'
import VpnKeyOutlined from '@mui/icons-material/VpnKeyOutlined'
import InfoOutlined from '@mui/icons-material/InfoOutlined'
import OpenInNew from '@mui/icons-material/OpenInNew'
import { Avatar, Box, Button, CircularProgress, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'
import { BasePage } from '../components/base-page'
import { InfoTip, rounded, Row, Segment } from '../components/common'
import { EnhancedCard } from '../components/enhanced-card'
import { useEvent } from '../hooks'

// 码境账号（设置页最上面的卡片）。2026-11-24 起显示；要再隐藏就改成 false
const SHOW_ACCOUNT = true

function Account() {
  const [st, setSt] = useState<any>(null)
  const [wait, setWait] = useState<null | { code: string }>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => { api.account_status().then(setSt) }, [])
  useEvent('account:event', (r: any) => {
    setWait(null); setBusy(false)
    if (r.state === 'ok') { setSt(r.status); setErr('') }
    else if (r.state === 'denied') setErr('你在网页上拒绝了授权。')
    else if (r.state === 'expired') setErr('授权请求已过期，请重新点“用码境账号登录”。')
    else setErr(r.error || '授权失败，请重试。')
  })

  const login = async () => {
    setBusy(true); setErr('')
    const r = await api.account_login()
    if (!r.ok) { setBusy(false); return setErr(r.error || '无法发起授权。') }
    setWait({ code: r.user_code })
  }
  const cancel = () => { api.account_cancel(); setWait(null); setBusy(false) }
  const unbind = async () => { await api.account_unbind(); setSt({ bound: false }); setErr('') }

  const title = <Box sx={{ display: 'flex', alignItems: 'center' }}><Typography variant="h6" sx={{ fontWeight: 'medium', fontSize: 16 }}>码境账号</Typography>
    <InfoTip text="点“用码境账号登录”会打开码境网页，你在网页上点“授权”即可。工具箱不接触你的密码，只保存一条加密的登录凭证；解绑会让它立即作废。" /></Box>

  return (
    <EnhancedCard title={title} icon={<PersonOutline />}>
      {st === null ? null : st.bound ? (
        <Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1.5 }}>
            <Avatar src={st.avatar || undefined} sx={{ width: 48, height: 48, bgcolor: 'primary.main', fontWeight: 700 }}>{(st.name || '码')[0]}</Avatar>
            <Box sx={{ minWidth: 0 }}>
              <Typography sx={{ fontWeight: 700, fontSize: 16 }}>{st.offline ? '已绑定' : st.name}</Typography>
              <Typography variant="caption" color="text.secondary">{st.offline ? '暂时连不上服务器，无法确认账号状态' : st.username}</Typography>
            </Box>
          </Box>
          <Button variant="outlined" color="error" startIcon={<LinkOffOutlined />} sx={{ ...rounded, alignSelf: 'flex-start' }} onClick={unbind}>解除绑定</Button>
        </Box>
      ) : wait ? (
        <Box>
          <Typography variant="caption" color="text.secondary">授权码（和网页上显示的一致才点“授权”）</Typography>
          <Typography sx={{ fontFamily: 'Consolas, monospace', fontWeight: 800, fontSize: 30, letterSpacing: 3, mb: 1, userSelect: 'text' }}>{wait.code}</Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <CircularProgress size={18} /><Typography variant="body2" color="text.secondary">等待你在网页上授权…</Typography>
            <Button size="small" sx={{ ml: 'auto' }} onClick={cancel}>取消</Button>
          </Box>
        </Box>
      ) : (
        <Box>
          {st.expired && <Typography variant="caption" color="warning.main" sx={{ display: 'block', mb: 1 }}>登录已过期，请重新登录。</Typography>}
          <Button variant="contained" size="large" disabled={busy} startIcon={<OpenInNew />} sx={rounded} onClick={login}>用码境账号登录</Button>
        </Box>
      )}
      {err && <Typography variant="caption" color="error.main" sx={{ display: 'block', mt: 1, userSelect: 'text' }}>{err}</Typography>}
    </EnhancedCard>
  )
}

function DownloadCard() {
  const [d, setD] = useState<{ path: string; custom: boolean } | null>(null)
  useEffect(() => { api.download_dir_info().then(setD) }, [])
  return (
    <EnhancedCard title="文件保存位置" icon={<FolderOutlined />}>
      <Typography sx={{ fontFamily: 'Consolas, monospace', fontSize: 13, wordBreak: 'break-all', userSelect: 'text', mb: 1 }}>{d?.path || ''}</Typography>
      <Box sx={{ display: 'flex', gap: 1 }}>
        <Button size="small" variant="outlined" sx={rounded} onClick={async () => setD(await api.download_dir_pick())}>更改</Button>
        <Button size="small" variant="outlined" sx={rounded} onClick={() => d && api.open_path(d.path)}>打开</Button>
        {d?.custom && <Button size="small" sx={rounded} onClick={async () => setD(await api.download_dir_reset())}>恢复默认</Button>}
      </Box>
    </EnhancedCard>
  )
}

function KeyCard() {
  const [k, setK] = useState<any>(null)
  const [msg, setMsg] = useState('')
  useEffect(() => { api.ssh_key_info().then(setK) }, [])
  const save = async () => { setMsg(''); const r = await api.ssh_key_export(); if (r.ok) setMsg('已保存到文件保存位置。'); else if (!r.cancelled) setMsg(r.error || '保存失败') }
  return (
    <EnhancedCard title={<Box sx={{ display: 'flex', alignItems: 'center' }}><Typography variant="h6" sx={{ fontWeight: 'medium', fontSize: 16 }}>SSH 通用密钥</Typography>
      <InfoTip text="所有主机共用同一对密钥。在 SSH 管理里点主机右边的“+密钥”图标，就会把它配到那台主机上（第一次会自动生成）。" /></Box>} icon={<VpnKeyOutlined />}>
      {k && (k.exists
        ? <>
            <Typography variant="body2" color="text.secondary" sx={{ wordBreak: 'break-all', userSelect: 'text', mb: 1 }}>{k.path}（及 .pub）</Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
              <Button size="small" variant="outlined" startIcon={<DownloadOutlined />} sx={rounded} onClick={save}>下载密钥</Button>
              {msg && <Typography variant="caption" color={msg.startsWith('已') ? 'success.main' : 'error.main'}>{msg}</Typography>}
            </Box>
          </>
        : <Typography variant="body2" color="text.secondary">还没有通用密钥。在 SSH 管理里点主机右边的“+密钥”图标，会自动生成并配上。</Typography>)}
    </EnhancedCard>
  )
}

export default function SettingsPage({ pref, setPref, version, top, setTop }: { pref: 'light' | 'dark' | 'system'; setPref: (m: 'light' | 'dark' | 'system') => void; version: string; top?: boolean; setTop?: (v: boolean) => void }) {
  const [upd, setUpd] = useState('')
  const waiting = useRef(false)
  // 点“检查更新”后，在这里直接给结果：最新就说最新；有新版就说发现新版并自动更新（后台下载、换好后自己重启）
  useEvent('update:state', (d: any) => {
    if (!waiting.current) return
    if (d.state === 'ok') { waiting.current = false; setUpd(String(d.text).startsWith('有新版') ? `发现${String(d.text).slice(2)}（源码版不自动更新）` : '已是最新版本。') }
    else if (d.state === 'busy') setUpd(`发现新版本，正在自动更新…${d.text.includes('%') ? ' ' + d.text.replace('更新中 ', '') : ''}`)
    else { waiting.current = false; setUpd('检查更新失败，稍后再试。') }
  })
  return (
    <BasePage title="设置">
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: SHOW_ACCOUNT ? '1fr 1fr' : 'minmax(0, 560px)' }, gap: 1.5, alignItems: 'start' }}>
        {SHOW_ACCOUNT && <Account />}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <EnhancedCard title="外观" icon={<PaletteOutlined />}>
            <Row label="主题模式"><Segment value={pref === 'dark' ? 1 : pref === 'system' ? 2 : 0} options={['浅色', '深色', '系统']} onChange={(i) => setPref(i === 1 ? 'dark' : i === 2 ? 'system' : 'light')} /></Row>
            <Row label="新布局（试用）"><Segment value={top ? 1 : 0} options={['侧边栏', '顶部栏']} onChange={(i) => setTop?.(i === 1)} /></Row>
          </EnhancedCard>
          <DownloadCard />
          <KeyCard />
          <EnhancedCard title="关于" icon={<InfoOutlined />}>
            <Row label="码境工具箱"><Typography color="text.secondary">v{version}</Typography></Row>
            <Button variant="outlined" size="small" sx={{ ...rounded, alignSelf: 'flex-start', mt: 0.5 }} onClick={() => { waiting.current = true; setUpd('正在检查…'); api.update_check() }}>检查更新</Button>
            {upd && <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>{upd}</Typography>}
          </EnhancedCard>
        </Box>
      </Box>
    </BasePage>
  )
}
