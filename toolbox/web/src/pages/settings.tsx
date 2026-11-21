import LinkOffOutlined from '@mui/icons-material/LinkOffOutlined'
import PersonOutline from '@mui/icons-material/PersonOutline'
import PaletteOutlined from '@mui/icons-material/PaletteOutlined'
import FolderOutlined from '@mui/icons-material/FolderOutlined'
import InfoOutlined from '@mui/icons-material/InfoOutlined'
import OpenInNew from '@mui/icons-material/OpenInNew'
import { Avatar, Box, Button, CircularProgress, Typography } from '@mui/material'
import { useEffect, useState } from 'react'

import { api } from '../bridge'
import { BasePage } from '../components/base-page'
import { InfoTip, rounded, Row, Segment } from '../components/common'
import { EnhancedCard } from '../components/enhanced-card'
import { useEvent } from '../hooks'

// 码境账号绑定功能先隐藏（后端和授权页都还在），要恢复把它改成 true
const SHOW_ACCOUNT = false

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

export default function SettingsPage({ pref, setPref, version }: { pref: 'light' | 'dark' | 'system'; setPref: (m: 'light' | 'dark' | 'system') => void; version: string }) {
  const [upd, setUpd] = useState('')
  return (
    <BasePage title="设置">
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: SHOW_ACCOUNT ? '1fr 1fr' : 'minmax(0, 560px)' }, gap: 1.5, alignItems: 'start' }}>
        {SHOW_ACCOUNT && <Account />}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <EnhancedCard title="外观" icon={<PaletteOutlined />}>
            <Row label="主题模式"><Segment value={pref === 'dark' ? 1 : pref === 'system' ? 2 : 0} options={['浅色', '深色', '系统']} onChange={(i) => setPref(i === 1 ? 'dark' : i === 2 ? 'system' : 'light')} /></Row>
          </EnhancedCard>
          <DownloadCard />
          <EnhancedCard title="关于" icon={<InfoOutlined />}>
            <Row label="克劳德工具箱"><Typography color="text.secondary">v{version}</Typography></Row>
            <Button variant="outlined" size="small" sx={{ ...rounded, alignSelf: 'flex-start', mt: 0.5 }} onClick={() => { api.update_check(); setUpd('已在检查，结果见左下角。') }}>检查更新</Button>
            {upd && <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>{upd}</Typography>}
          </EnhancedCard>
        </Box>
      </Box>
    </BasePage>
  )
}
