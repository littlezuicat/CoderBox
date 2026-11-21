// 版式取自 clash-verge-rev（GPL-3.0）：pages/_layout.tsx、components/layout/layout-sidebar.tsx、layout-item.tsx
import CheckCircleOutline from '@mui/icons-material/CheckCircleOutline'
import ErrorOutline from '@mui/icons-material/ErrorOutline'
import SyncRounded from '@mui/icons-material/SyncRounded'
import { alpha, List, ListItem, ListItemButton, ListItemIcon, ListItemText, Paper, ThemeProvider, Typography } from '@mui/material'
import { useEffect, useMemo, useRef, useState } from 'react'

import wordDark from './assets/wordmark-dark.png'
import wordLight from './assets/wordmark-light.png'
import { api, emitLocal } from './bridge'
import { NavIcon } from './components/nav-icons'
import { initSettings, useEvent } from './hooks'
import ConvertPage from './pages/convert'
import OnlinePage from './pages/online'
import PptPage from './pages/ppt'
import { Installer, Uninstaller } from './pages/installer'
import SettingsPage from './pages/settings'
import SshPage from './pages/ssh'
import { buildTheme } from './theme'

const NAV = [
  { key: 'ppt', label: 'PPT定图', icon: <NavIcon k="ppt" />, Page: PptPage, files: 'files:ppt' },
  { key: 'convert', label: '格式转换', icon: <NavIcon k="convert" />, Page: ConvertPage, files: 'files:convert' },
  { key: 'ssh', label: 'SSH管理', icon: <NavIcon k="ssh" />, Page: SshPage, files: 'files:ssh' },
  { key: 'online', label: '在线工具', icon: <NavIcon k="online" />, Page: OnlinePage, files: '' },
  { key: 'settings', label: '设置', icon: <NavIcon k="settings" />, Page: SettingsPage, files: '' },
]

function NavItem({ selected, icon, children, onClick }: any) {
  return (
    <ListItem sx={{ py: 0.5, maxWidth: 250, mx: 'auto', padding: '4px 0px' }}>
      <ListItemButton selected={selected} onClick={onClick}
        sx={[{ borderRadius: 2, marginLeft: 1.25, paddingLeft: 1, paddingRight: 1, marginRight: 1.25, cursor: 'pointer', '& .MuiListItemText-primary': { color: 'text.primary', fontWeight: '700' } },
          ({ palette: { mode, primary } }: any) => {
            const bgcolor = mode === 'light' ? alpha(primary.main, 0.15) : alpha(primary.main, 0.35)
            const color = mode === 'light' ? '#1f1f1f' : '#ffffff'
            return { '&.Mui-selected': { bgcolor }, '&.Mui-selected:hover': { bgcolor }, '&.Mui-selected .MuiListItemText-primary': { color } }
          }]}>
        <ListItemIcon sx={{ color: 'text.primary', marginLeft: '6px', cursor: 'inherit' }}>{icon}</ListItemIcon>
        <ListItemText sx={{ textAlign: 'center', marginLeft: '-35px' }} primary={children} />
      </ListItemButton>
    </ListItem>
  )
}

export default function App() {
  const [ready, setReady] = useState(false)
  const [pref, setPref] = useState<'light' | 'dark' | 'system'>('light')
  const [sysDark, setSysDark] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false)
  const mode: 'light' | 'dark' = pref === 'system' ? (sysDark ? 'dark' : 'light') : pref
  const [page, setPage] = useState(0)
  const [upd, setUpd] = useState<{ state: string; text: string }>({ state: 'ok', text: '最新' })
  const [version, setVersion] = useState('')
  const [appMode, setAppMode] = useState<'app' | 'installer' | 'uninstaller'>('app')
  const pageRef = useRef(0); pageRef.current = page

  useEffect(() => {
    api.app_info().then((i: any) => {
      initSettings(i.settings); setVersion(i.version); setAppMode(i.mode || 'app')
      const q = new URLSearchParams(location.search)
      const t = i.settings?.theme
      setPref(q.get('dark') ? 'dark' : t === 'dark' || t === 'system' ? t : 'light')
      const k = NAV.findIndex((n) => n.key === q.get('page')); if (k >= 0) setPage(k)
      setReady(true)
    })
  }, [])
  const theme = useMemo(() => buildTheme(mode), [mode])
  useEffect(() => { if (ready && appMode === 'app') api.set_titlebar(mode) }, [mode, ready, appMode])
  // 允许把文件拖进窗口。这里必须是页面自己的轻量监听：pywebview 的 DOM dragover 处理器每次都要把整个事件序列化发给 Python，
  // 拖动时会把页面主线程占满（定时器停摆、框不变色、入队要等几秒），所以 main.py 只登记 drop，dragover 由这里放行。
  useEffect(() => {
    const allow = (e: DragEvent) => { if (Array.from(e.dataTransfer?.types || []).includes('Files')) { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy' } }
    window.addEventListener('dragover', allow, true)
    return () => window.removeEventListener('dragover', allow, true)
  }, [])
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)'); if (!mq) return
    const f = (e: MediaQueryListEvent) => setSysDark(e.matches)
    mq.addEventListener('change', f); return () => mq.removeEventListener('change', f)
  }, [])
  useEvent('update:state', (d: any) => setUpd(d))

  // 拖进窗口的文件：当前页能收就给当前页，否则找第一个能收的页面（演示文稿 → PPT；音视频图片 → 格式转换）
  useEvent('drop:files', async (paths: string[]) => {
    const cur = NAV[pageRef.current]
    let target = -1
    if (cur.key === 'ssh') target = 2
    else if ((await api.file_info(paths, 'ppt')).length) target = 0
    else if ((await api.file_info(paths, 'media')).length) target = 1
    else if (cur.key === 'convert' || cur.key === 'ppt') target = pageRef.current
    if (target < 0) return
    setPage(target)
    setTimeout(() => emitLocal(NAV[target].files, paths), 0)
  })

  if (!ready) return null
  if (appMode !== 'app') return <ThemeProvider theme={theme}>{appMode === 'installer' ? <Installer /> : <Uninstaller />}</ThemeProvider>
  const changePref = (m: 'light' | 'dark' | 'system') => { setPref(m); api.settings_set('theme', m) }
  return (
    <ThemeProvider theme={theme}>
      <Paper square elevation={0} className="windows layout" sx={({ palette }) => ({ bgcolor: palette.background.paper })}>
        <div className="layout-content">
          <div className="layout-content__left">
            <div className="the-logo" style={{ margin: '10px 10px 0', padding: '5px 0 16px' }}>
              <div style={{ width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 3 }}>
                <img src={mode === 'dark' ? wordLight : wordDark} alt="码境" title="克劳德工具箱" style={{ height: 21, width: 'auto', display: 'block' }} />
                <Typography sx={{ fontSize: 11, letterSpacing: '0.35em', mr: '-0.35em', color: 'text.primary', lineHeight: 1.2, userSelect: 'none' }}>克劳德工具箱</Typography>
              </div>
            </div>
            <List className="the-menu">
              {NAV.map((n, i) => <NavItem key={n.key} selected={i === page} icon={n.icon} onClick={() => setPage(i)}>{n.label}</NavItem>)}
            </List>
            <div className="the-traffic">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderRadius: 12, background: mode === 'dark' ? '#282a36' : '#fff' }} title={upd.text}>
                {upd.state === 'busy' ? <SyncRounded fontSize="small" color="primary" /> : upd.state === 'err' ? <ErrorOutline fontSize="small" color="error" /> : <CheckCircleOutline fontSize="small" color="success" />}
                <Typography variant="body2" sx={{ fontSize: 12.5, lineHeight: 1.3 }}>{upd.state === 'ok' ? `v${version} · ${upd.text}` : upd.text}</Typography>
              </div>
            </div>
          </div>
          <div className="layout-content__right">
            <div className="the-bar"></div>
            <div className="the-content">
              {NAV.map((n, i) => <div key={n.key} style={{ display: i === page ? 'block' : 'none', height: '100%' }}><n.Page pref={pref} setPref={changePref} version={version} active={i === page} /></div>)}
            </div>
          </div>
        </div>
      </Paper>
    </ThemeProvider>
  )
}
