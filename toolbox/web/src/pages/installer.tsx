// 安装 / 卸载面板：下载下来的 exe 第一次运行显示它；装好之后从安装目录运行才是正式的程序。
import CheckRounded from '@mui/icons-material/CheckRounded'
import ErrorOutline from '@mui/icons-material/ErrorOutline'
import FolderOpenOutlined from '@mui/icons-material/FolderOpenOutlined'
import { Alert, Box, Button, Checkbox, FormControlLabel, InputAdornment, LinearProgress, TextField, Typography } from '@mui/material'
import { useEffect, useState } from 'react'

import Logo from '../components/logo'
import { api } from '../bridge'
import { rounded } from '../components/common'
import { useEvent } from '../hooks'

const STEPS = ['欢迎', '安装位置', '正在安装', '完成']

function Side({ step, labels, version, uninstall }: { step: number; labels: string[]; version: string; uninstall?: boolean }) {
  return (
    <Box sx={{ width: 236, flexShrink: 0, color: '#fff', background: 'linear-gradient(160deg,#14233f 0%,#1d3a6b 100%)', p: 3.5, display: 'flex', flexDirection: 'column' }}>
      <Logo dark height={26} style={{ alignSelf: 'flex-start', marginBottom: 6 }} />
      <Typography sx={{ fontSize: 13, letterSpacing: '0.2em', opacity: 0.85 }}>码境工具箱</Typography>
      <Box sx={{ mt: 5, display: 'flex', flexDirection: 'column', gap: 2 }}>
        {labels.map((l, i) => (
          <Box key={l} sx={{ display: 'flex', alignItems: 'center', gap: 1.4, opacity: i <= step ? 1 : 0.45 }}>
            <Box sx={{ width: 22, height: 22, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, bgcolor: i < step ? '#3dd68c' : i === step ? '#fff' : 'transparent', color: i === step ? '#14233f' : '#fff', border: i > step ? '1.5px solid rgba(255,255,255,.6)' : 'none' }}>
              {i < step ? <CheckRounded sx={{ fontSize: 15, color: '#14233f' }} /> : i + 1}
            </Box>
            <Typography sx={{ fontSize: 14, fontWeight: i === step ? 700 : 500 }}>{l}</Typography>
          </Box>
        ))}
      </Box>
      <Box sx={{ flex: 1 }} />
      <Typography sx={{ fontSize: 12, opacity: 0.6 }}>{uninstall ? '卸载' : '安装包'} · v{version}</Typography>
    </Box>
  )
}

function Frame({ side, children, actions }: { side: React.ReactNode; children: React.ReactNode; actions: React.ReactNode }) {
  return (
    <Box sx={{ display: 'flex', height: '100vh', bgcolor: '#fff', userSelect: 'none' }}>
      {side}
      <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', p: 4.5, minWidth: 0 }}>
        <Box sx={{ flex: 1, minHeight: 0 }}>{children}</Box>
        <Box sx={{ display: 'flex', gap: 1.2, justifyContent: 'flex-end', pt: 2 }}>{actions}</Box>
      </Box>
    </Box>
  )
}

export function Installer() {
  const [st, setSt] = useState<any>(null)
  const [step, setStep] = useState(0)
  const [dir, setDir] = useState('')
  const [desktop, setDesktop] = useState(true)
  const [menu, setMenu] = useState(true)
  const [prog, setProg] = useState({ pct: 0, text: '' })
  const [err, setErr] = useState('')
  const [exe, setExe] = useState('')
  const [run, setRun] = useState(true)

  useEffect(() => { api.installer_state().then((s: any) => { setSt(s); setDir(s.existing?.dir || s.default_dir) }) }, [])
  useEvent('inst:progress', (d: any) => setProg(d))
  useEvent('inst:done', (r: any) => { if (r.ok) { setExe(r.exe); setStep(3) } else { setErr(r.error || '安装失败'); setStep(1) } })
  if (!st) return null

  const start = async () => { setErr(''); setProg({ pct: 0, text: '准备中…' }); setStep(2); await api.installer_run({ dir, desktop, startmenu: menu }) }
  const finish = async () => { if (run && exe) await api.installer_launch(exe); api.installer_exit() }
  const side = <Side step={step} labels={STEPS} version={st.version} />

  if (step === 0) return (
    <Frame side={side} actions={<><Button onClick={() => api.installer_exit()} sx={rounded}>取消</Button><Button variant="contained" sx={rounded} onClick={() => setStep(1)}>下一步</Button></>}>
      <Typography sx={{ fontSize: 24, fontWeight: 800, mb: 1 }}>欢迎使用码境工具箱</Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>PPT 定图 · 格式转换 · SSH 管理 · 在线工具</Typography>
      {st.existing
        ? <Alert severity="info" sx={{ borderRadius: 2 }}>已安装 v{st.existing.version || '?'}，继续会覆盖安装。你的设置和主机列表会保留。</Alert>
        : <Typography color="text.secondary" sx={{ lineHeight: 1.9 }}>接下来选一个位置，几秒钟就装好。<br />不需要管理员权限，也不会改动系统设置。</Typography>}
    </Frame>
  )

  if (step === 1) return (
    <Frame side={side} actions={<><Button onClick={() => setStep(0)} sx={rounded}>上一步</Button><Button variant="contained" sx={rounded} disabled={!dir.trim()} onClick={start}>{st.existing ? '覆盖安装' : '安装'}</Button></>}>
      <Typography sx={{ fontSize: 22, fontWeight: 800, mb: 2.5 }}>安装位置</Typography>
      <TextField fullWidth size="small" value={dir} onChange={(e) => setDir(e.target.value)} sx={{ '& .MuiOutlinedInput-root': { borderRadius: 2 }, userSelect: 'text' }}
        InputProps={{ endAdornment: <InputAdornment position="end"><Button size="small" startIcon={<FolderOpenOutlined />} onClick={async () => { const d = await api.installer_pick_dir(dir); if (d) setDir(d) }}>浏览</Button></InputAdornment> }} />
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.8 }}>需要约 40 MB。设置和主机列表另存在你的用户数据里，不在这个文件夹。</Typography>
      <Box sx={{ mt: 2.5 }}>
        <FormControlLabel control={<Checkbox checked={desktop} onChange={(_, v) => setDesktop(v)} />} label="创建桌面快捷方式" />
        <FormControlLabel control={<Checkbox checked={menu} onChange={(_, v) => setMenu(v)} />} label="添加到开始菜单" />
      </Box>
      {err && <Alert severity="error" icon={<ErrorOutline />} sx={{ mt: 1.5, borderRadius: 2, userSelect: 'text' }}>{err}</Alert>}
    </Frame>
  )

  if (step === 2) return (
    <Frame side={side} actions={null}>
      <Typography sx={{ fontSize: 22, fontWeight: 800, mb: 3 }}>正在安装…</Typography>
      <LinearProgress variant="determinate" value={prog.pct} sx={{ height: 8, borderRadius: 4 }} />
      <Typography color="text.secondary" sx={{ mt: 1.5 }}>{prog.text}</Typography>
    </Frame>
  )

  return (
    <Frame side={side} actions={<Button variant="contained" sx={rounded} onClick={finish}>完成</Button>}>
      <Box sx={{ width: 56, height: 56, borderRadius: '50%', bgcolor: '#3dd68c', display: 'flex', alignItems: 'center', justifyContent: 'center', mb: 2 }}><CheckRounded sx={{ color: '#fff', fontSize: 34 }} /></Box>
      <Typography sx={{ fontSize: 24, fontWeight: 800, mb: 1 }}>安装完成</Typography>
      <Typography color="text.secondary" sx={{ mb: 2.5, wordBreak: 'break-all' }}>已安装到 {dir}</Typography>
      <FormControlLabel control={<Checkbox checked={run} onChange={(_, v) => setRun(v)} />} label="立即运行码境工具箱" />
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>以后从桌面或开始菜单打开；这个安装包可以删掉了。</Typography>
    </Frame>
  )
}

export function Uninstaller() {
  const [st, setSt] = useState<any>(null)
  const [step, setStep] = useState(0)
  const [data, setData] = useState(false)
  const [prog, setProg] = useState({ pct: 0, text: '' })
  const [err, setErr] = useState('')
  useEffect(() => { api.installer_state().then(setSt) }, [])
  useEvent('inst:progress', (d: any) => setProg(d))
  useEvent('inst:done', (r: any) => { if (r.ok) setStep(2); else { setErr(r.error || '卸载失败'); setStep(0) } })
  if (!st) return null
  const labels = ['确认', '卸载中', '完成']
  const side = <Side step={step} labels={labels} version={st.version} uninstall />

  if (step === 0) return (
    <Frame side={side} actions={<><Button onClick={() => api.installer_exit()} sx={rounded}>取消</Button><Button variant="contained" color="error" sx={rounded} onClick={async () => { setErr(''); setStep(1); await api.uninstall_run({ remove_data: data }) }}>卸载</Button></>}>
      <Typography sx={{ fontSize: 22, fontWeight: 800, mb: 1.5 }}>卸载码境工具箱</Typography>
      <Typography color="text.secondary" sx={{ mb: 2.5, lineHeight: 1.9 }}>将删除程序文件和快捷方式。</Typography>
      <FormControlLabel control={<Checkbox checked={data} onChange={(_, v) => setData(v)} />} label="同时删除我的设置和主机列表" />
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', ml: 4 }}>不勾选的话，以后重装还能接着用。~/.ssh 里的密钥和配置不会被动。</Typography>
      {err && <Alert severity="error" sx={{ mt: 2, borderRadius: 2, userSelect: 'text' }}>{err}</Alert>}
    </Frame>
  )
  if (step === 1) return (
    <Frame side={side} actions={null}>
      <Typography sx={{ fontSize: 22, fontWeight: 800, mb: 3 }}>正在卸载…</Typography>
      <LinearProgress variant="determinate" value={prog.pct} sx={{ height: 8, borderRadius: 4 }} />
      <Typography color="text.secondary" sx={{ mt: 1.5 }}>{prog.text}</Typography>
    </Frame>
  )
  return (
    <Frame side={side} actions={<Button variant="contained" sx={rounded} onClick={() => api.installer_exit()}>关闭</Button>}>
      <Box sx={{ width: 56, height: 56, borderRadius: '50%', bgcolor: '#3dd68c', display: 'flex', alignItems: 'center', justifyContent: 'center', mb: 2 }}><CheckRounded sx={{ color: '#fff', fontSize: 34 }} /></Box>
      <Typography sx={{ fontSize: 24, fontWeight: 800 }}>已卸载</Typography>
    </Frame>
  )
}
