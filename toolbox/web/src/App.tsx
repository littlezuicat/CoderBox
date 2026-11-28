// 版式取自 clash-verge-rev（GPL-3.0）：pages/_layout.tsx、components/layout/layout-sidebar.tsx、layout-item.tsx
import CloseRounded from '@mui/icons-material/CloseRounded'
import CropSquareRounded from '@mui/icons-material/CropSquareRounded'
import FilterNoneRounded from '@mui/icons-material/FilterNoneRounded'
import HorizontalRuleRounded from '@mui/icons-material/HorizontalRuleRounded'
import CheckCircleOutline from '@mui/icons-material/CheckCircleOutline'
import ErrorOutline from '@mui/icons-material/ErrorOutline'
import SyncRounded from '@mui/icons-material/SyncRounded'
import { alpha, Box, List, ListItem, ListItemButton, ListItemIcon, ListItemText, Paper, ThemeProvider, Typography } from '@mui/material'
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import Logo from './components/logo'
import { api, emitLocal, isReal } from './bridge'
import { NavIcon } from './components/nav-icons'
import { initSettings, useEvent } from './hooks'
import { ShareToast } from './components/share-people'
import ConvertPage from './pages/convert'
import LibraryPage from './pages/library'
import OnlinePage from './pages/online'
import PptPage from './pages/ppt'
import { Installer, Uninstaller } from './pages/installer'
import SecurityPage from './pages/security'
import SettingsPage from './pages/settings'
import VaultPage from './pages/vault'
import ExperimentsPage from './pages/experiments'
import SshPage from './pages/ssh'
import { buildTheme } from './theme'

// 密码页（本机保险库 + 同步 + 浏览器扩展）先隐藏：后端、页面、扩展都还在，要恢复把它改成 true
const SHOW_VAULT = false

const NAV = [
  { key: 'ssh', label: 'SSH管理', icon: <NavIcon k="ssh" />, Page: memo(SshPage), files: 'files:ssh' },
  { key: 'exp', label: '实验记录', icon: <NavIcon k="exp" />, Page: memo(ExperimentsPage), files: '' },
  { key: 'ppt', label: 'PPT定图', icon: <NavIcon k="ppt" />, Page: memo(PptPage), files: 'files:ppt' },
  { key: 'convert', label: '格式转换', icon: <NavIcon k="convert" />, Page: memo(ConvertPage), files: 'files:convert' },
  { key: 'security', label: '设备安全', icon: <NavIcon k="security" />, Page: memo(SecurityPage), files: '' },
  ...(SHOW_VAULT ? [{ key: 'vault', label: '密码', icon: <NavIcon k="vault" />, Page: memo(VaultPage), files: '' }] : []),
  { key: 'library', label: '图书馆', icon: <NavIcon k="library" />, Page: memo(LibraryPage), files: '' },
  { key: 'online', label: '在线工具', icon: <NavIcon k="online" />, Page: memo(OnlinePage), files: '' },
  { key: 'settings', label: '设置', icon: <NavIcon k="settings" />, Page: memo(SettingsPage), files: '' },
]

// 顶部栏（新布局）里每项压成两个字，完整名字放在悬停提示里
const SHORT: Record<string, string> = { exp: '实验', ppt: '定图', convert: '转换', ssh: '主机', security: '安全', vault: '密码', library: '图书馆', online: '工具', settings: '设置' }

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
  const [top, setTop] = useState(true)         // 新布局 demo：功能在顶部，SSH 页是 VS Code 式工作区
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
      setTop(q.get('layout') === 'ide' ? true : q.get('layout') === 'side' ? false : i.settings?.layout_demo !== false)
      const k = NAV.findIndex((n) => n.key === q.get('page')); if (k >= 0) setPage(k)
      setReady(true)
    })
  }, [])
  // 浏览器里第一次 new RTCPeerConnection 要初始化 WebRTC，实测约 700ms 会卡住主线程；设备安全页要用它测 WebRTC 泄露。
  // 启动后趁空闲先热身一次，避免用户第一次点“设备安全”时卡住切页。
  useEffect(() => {
    if (!ready) return
    const t = setTimeout(() => { try { new RTCPeerConnection({}).close() } catch { /* */ } }, 2500)
    return () => clearTimeout(t)
  }, [ready])
  const theme = useMemo(() => buildTheme(mode), [mode])
  // 启动动画（index.html 里的 #splash）：界面就绪后，至少放满 1.1 秒再淡出；先按真实主题校正深浅色。只在启动时出现，从托盘叫回窗口不会重来
  useEffect(() => {
    if (!ready) return
    const el = document.getElementById('splash'); if (!el) return
    document.documentElement.dataset.theme = mode
    // 预加载：动画一直停在起始帧，等界面这一轮渲染提交并画出来、主线程空闲了才开始放（index.html 里 __splashGo），计时从那一刻算起
    let t1: any, t2: any, r1 = 0, r2 = 0, idle: any
    const w = window as any
    const show = appMode === 'app' && !new URLSearchParams(location.search).get('nosplash')
    const finish = () => {
      const t0 = w.__splashT0 ?? performance.now()
      const wait = show ? Math.max(0, 1100 - (performance.now() - t0)) : 0
      t1 = setTimeout(() => el.classList.add('leaving'), wait)
      t2 = setTimeout(() => el.remove(), wait + 340)
    }
    if (show && w.__splashT0 === undefined) {
      const go = () => { w.__splashGo?.(); finish() }
      r1 = requestAnimationFrame(() => { r2 = requestAnimationFrame(() => {
        if ('requestIdleCallback' in window) idle = (window as any).requestIdleCallback(go, { timeout: 400 }); else t1 = setTimeout(go, 60)
      }) })
    } else finish()
    return () => { clearTimeout(t1); clearTimeout(t2); cancelAnimationFrame(r1); cancelAnimationFrame(r2); if (idle) (window as any).cancelIdleCallback?.(idle) }
  }, [ready, appMode, mode])
  useEffect(() => { if (ready && appMode === 'app') api.set_titlebar(mode) }, [mode, ready, appMode])
  // 弹窗（MUI 遮罩）打开时，顶栏里原生的那一块也要压暗：监听遮罩出现/消失，告诉后端。（菜单的遮罩是透明的，不算）
  useEffect(() => {
    if (!ready || appMode !== 'app' || !top || !isReal()) return
    let dim = false
    // 按遮罩当前的真实不透明度判断（关闭时 MUI 会让遮罩留在 DOM 里一小会儿，只是 opacity 变 0），所以 style/class 变化也要看；下一帧合并一次
    const check = () => {
      const on = [...document.querySelectorAll('.MuiBackdrop-root:not(.MuiBackdrop-invisible)')].some((b) => parseFloat(getComputedStyle(b).opacity) > 0.5)
      if (on !== dim) { dim = on; api.win_dim(on) }
    }
    let raf = 0
    const sched = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; check() }) }
    const mo = new MutationObserver(sched)
    mo.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class'] })
    return () => { mo.disconnect(); cancelAnimationFrame(raf); if (dim) api.win_dim(false) }
  }, [ready, appMode, top])
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
    const at = (k: string) => NAV.findIndex((n) => n.key === k)
    if (cur.key === 'ssh') target = at('ssh')
    else if ((await api.file_info(paths, 'ppt')).length) target = at('ppt')
    else if ((await api.file_info(paths, 'media')).length) target = at('convert')
    else if (cur.key === 'convert' || cur.key === 'ppt') target = pageRef.current
    if (target < 0) return
    setPage(target)
    setTimeout(() => emitLocal(NAV[target].files, paths), 0)
  })

  // 新布局用顶部栏当标题栏：去掉系统标题栏（旧布局恢复）；最大化状态要跟着窗口变化，好换最大化/还原图标
  const [zoomed, setZoomed] = useState(false)
  // 原生标题栏按钮（最小化/最大化/关闭由 Windows 画在右上角，悬停最大化有贴靠布局浮层）：后端返回按钮区大小（CSS 像素），这里给它留出位置
  const [cap, setCap] = useState<{ w: number; h: number } | null>(null)
  useEffect(() => { if (ready && appMode === 'app') Promise.resolve(api.win_borderless(top)).then((r: any) => setCap(r && r.w ? r : null)).catch(() => setCap(null)) }, [top, ready, appMode])
  // 顶栏空白处：按下 = 交给 Windows 的标题栏拖动（移动 / 最大化时下拖还原 / 拖到屏幕边缘贴边分屏）；系统拖动会吞掉鼠标松开，所以双击自己用时间间隔判断
  const [nativeDrag, setNativeDrag] = useState(false)
  useEffect(() => { if (ready && appMode === 'app' && isReal()) Promise.resolve(api.win_native_drag()).then((ok: any) => setNativeDrag(!!ok)).catch(() => { /* */ }) }, [ready, appMode])
  // 顶栏空白处（导航和版本号之间）：把它的位置告诉后端，后端把这块从网页控件上挖掉，让 Windows 当真正的标题栏处理（拖动、贴边、顶端布局条、双击最大化）
  const blankRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!cap) return
    const send = () => {
      const el = blankRef.current; if (!el) return
      const r = el.getBoundingClientRect(), k = window.devicePixelRatio || 1
      api.win_blank([Math.round(r.left * k), Math.round(r.top * k), Math.round(r.right * k), Math.round(r.bottom * k)])
    }
    send()
    const ro = new ResizeObserver(send)
    if (blankRef.current) ro.observe(blankRef.current)
    window.addEventListener('resize', send)
    return () => { ro.disconnect(); window.removeEventListener('resize', send) }
  }, [cap, top])
  const lastBarDown = useRef(0)
  const barDown = useCallback((e: { button: number; target: unknown; currentTarget: unknown }) => {
    if (nativeDrag || e.button !== 0 || e.target !== e.currentTarget) return
    const now = Date.now()
    if (now - lastBarDown.current < 450) { lastBarDown.current = 0; api.win_cmd('toggle'); return }
    lastBarDown.current = now
    api.win_drag()
  }, [])
  useEffect(() => {
    let t: any
    const f = () => { clearTimeout(t); t = setTimeout(() => api.win_zoomed().then((z: boolean) => setZoomed(!!z)), 120) }
    window.addEventListener('resize', f); return () => { window.removeEventListener('resize', f); clearTimeout(t) }
  }, [])
  // 先把顶栏原生区域的底色交给后端，再切网页主题，尽量让两边同时变色（不然中间会闪一下旧颜色）
  // 先等后端把顶栏原生区域和窗口底色换好，再切网页主题：这样原生那一块不会先亮着旧颜色
  const changePref = useCallback(async (m: 'light' | 'dark' | 'system') => {
    if (m !== 'system' && isReal()) { try { await api.set_titlebar(m) } catch { /* 失败就直接切 */ } }
    setPref(m); api.settings_set('theme', m)
  }, [])      // 引用要稳定，页面组件才能 memo
  const changeTop = useCallback((v: boolean) => { setTop(v); api.settings_set('layout_demo', v) }, [])
  if (!ready) return null
  if (appMode !== 'app') return <ThemeProvider theme={theme}>{appMode === 'installer' ? <Installer /> : <Uninstaller />}</ThemeProvider>
  if (top) {
    // 新布局（demo）：功能放顶部一行，下面整块给内容；SSH 页是“主机列表 + VS Code 式工作区”
    return (
      <ThemeProvider theme={theme}>
        <Paper square elevation={0} className="windows layout" sx={({ palette }) => ({ bgcolor: palette.background.paper })}>
          <Box onMouseDown={barDown}
            sx={{ flex: '0 0 46px', display: 'flex', alignItems: 'center', gap: 0.3, pl: 1.5, pr: cap ? `${cap.w}px` : isReal() ? 0 : 1.5, borderBottom: 1, borderColor: 'divider', userSelect: 'none', overflow: 'hidden',
              ...(nativeDrag ? { WebkitAppRegion: 'drag', '& > *:not(.btns)': { WebkitAppRegion: 'no-drag' } } : {}) }}>
            <Logo dark={mode === 'dark'} height={17} style={{ display: 'block', marginRight: 12, flexShrink: 0 }} />
            {NAV.map((n, i) => (
              <Box key={n.key} onClick={() => setPage(i)} title={n.label}
                sx={({ palette: { mode: m, primary } }) => ({ display: 'flex', alignItems: 'center', gap: 0.6, px: 1.1, height: 28, borderRadius: 1.5, cursor: 'pointer', flexShrink: 0, whiteSpace: 'nowrap', fontSize: 13, fontWeight: i === page ? 600 : 400, color: i === page ? 'text.primary' : 'text.secondary',
                  '& svg': { fontSize: 15, opacity: i === page ? 1 : 0.8 }, bgcolor: i === page ? alpha(primary.main, m === 'light' ? 0.1 : 0.25) : 'transparent', '&:hover': { bgcolor: i === page ? undefined : 'action.hover', color: 'text.primary' } })}>
                {n.icon}{SHORT[n.key] || n.label}
              </Box>
            ))}
            <Box ref={blankRef} sx={{ flex: 1, alignSelf: 'stretch', ...(nativeDrag ? { WebkitAppRegion: 'drag' } : {}) }} onMouseDown={barDown} />
            {/* 正常（已是最新）时不显示版本号；只在更新中/更新出错时显示一条状态 */}
            {upd.state !== 'ok' && <Box title={upd.text} sx={{ display: 'flex', alignItems: 'center', gap: 0.7, color: 'text.secondary', fontSize: 12, flexShrink: 0, mr: isReal() && !cap ? 1.5 : 0, '@media (max-width: 940px)': { display: 'none' }, ...(nativeDrag ? { WebkitAppRegion: 'drag' } : {}) }}>
              {upd.state === 'busy' ? <SyncRounded sx={{ fontSize: 16 }} color="primary" /> : <ErrorOutline sx={{ fontSize: 16 }} color="error" />}
              {upd.text}
            </Box>}
            {isReal() && !cap && (
              <Box className="btns" sx={{ display: 'flex', alignSelf: 'stretch', flexShrink: 0 }}>
                {[
                  { t: '最小化', f: () => api.win_cmd('min'), i: <HorizontalRuleRounded sx={{ fontSize: 18 }} /> },
                  { t: zoomed ? '还原' : '最大化', f: () => api.win_cmd('toggle'), i: zoomed ? <FilterNoneRounded sx={{ fontSize: 14 }} /> : <CropSquareRounded sx={{ fontSize: 16 }} /> },
                  { t: '关闭', f: () => api.win_cmd('close'), i: <CloseRounded sx={{ fontSize: 17 }} />, close: true },
                ].map((b) => (
                  <Box key={b.t} title={b.t} onClick={b.f}
                    sx={{ width: 46, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'default', color: 'text.secondary',
                      '&:hover': { bgcolor: b.close ? '#e81123' : 'action.hover', color: b.close ? '#fff' : 'text.primary' } }}>{b.i}</Box>
                ))}
              </Box>
            )}
          </Box>
          <Box sx={{ flex: 1, minHeight: 0, position: 'relative' }}>
            {NAV.map((n, i) => <div key={n.key} style={{ display: i === page ? 'block' : 'none', height: '100%' }}><n.Page pref={pref} setPref={changePref} version={version} active={i === page} top={top} setTop={changeTop} ide={n.key === 'ssh'} /></div>)}
          </Box>
        </Paper>
        <ShareToast />
      </ThemeProvider>
    )
  }
  return (
    <ThemeProvider theme={theme}>
      <Paper square elevation={0} className="windows layout" sx={({ palette }) => ({ bgcolor: palette.background.paper })}>
        <div className="layout-content">
          <div className="layout-content__left">
            <div className="the-logo" style={{ margin: '0 10px', padding: '14px 0 0', flex: '0 0 84px', height: 84, alignSelf: 'auto' }}>
              <div style={{ width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 3 }}>
                <Logo dark={mode === 'dark'} height={25} style={{ display: 'block' }} />
                <Typography sx={{ fontSize: 12.5, letterSpacing: '0.35em', mr: '-0.35em', color: 'text.primary', lineHeight: 1.2, userSelect: 'none' }}>码境工具箱</Typography>
              </div>
            </div>
            <div style={{ flex: '0 0 1px', height: 1, margin: '0 26px 6px', background: 'var(--divider-color)' }} />
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
              {NAV.map((n, i) => <div key={n.key} style={{ display: i === page ? 'block' : 'none', height: '100%' }}><n.Page pref={pref} setPref={changePref} version={version} active={i === page} top={top} setTop={changeTop} /></div>)}
            </div>
          </div>
        </div>
      </Paper>
      <ShareToast />
    </ThemeProvider>
  )
}
