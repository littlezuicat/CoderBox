// 密码：本机加密的保险库。日常不上锁（密钥由 Windows 账户保护），密码默认不显示，复制后 15 秒自动清空剪贴板。
import AddRounded from '@mui/icons-material/AddRounded'
import ContentCopyRounded from '@mui/icons-material/ContentCopyRounded'
import DeleteOutline from '@mui/icons-material/DeleteOutline'
import ExtensionOutlined from '@mui/icons-material/ExtensionOutlined'
import CloudSyncOutlined from '@mui/icons-material/CloudSyncOutlined'
import FileDownloadOutlined from '@mui/icons-material/FileDownloadOutlined'
import EditOutlined from '@mui/icons-material/EditOutlined'
import KeyRounded from '@mui/icons-material/KeyRounded'
import OpenInNewRounded from '@mui/icons-material/OpenInNewRounded'
import SearchRounded from '@mui/icons-material/SearchRounded'
import VisibilityOffRounded from '@mui/icons-material/VisibilityOffRounded'
import VisibilityRounded from '@mui/icons-material/VisibilityRounded'
import { alpha, Autocomplete, Box, Button, Checkbox, Chip, CircularProgress, Dialog, FormControlLabel, DialogActions, DialogContent, DialogTitle, IconButton, InputAdornment, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography, useTheme } from '@mui/material'
import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../bridge'
import { useEvent } from '../hooks'
import { BasePage } from '../components/base-page'
import { pageGrid, rounded } from '../components/common'
import { EnhancedCard } from '../components/enhanced-card'

type Summary = { id: string; type: 'login' | 'note'; name: string; username: string; url: string; folder: string; updated: number; has_password: boolean }
type Item = { id?: string; type: 'login' | 'note'; name: string; username: string; password: string; url: string; notes: string; folder: string }
const EMPTY: Item = { type: 'login', name: '', username: '', password: '', url: '', notes: '', folder: '' }
const host = (u: string) => { try { return new URL(/^https?:\/\//i.test(u) ? u : 'https://' + u).hostname } catch { return u } }

export default function VaultPage({ active }: { active?: boolean }) {
  const theme = useTheme()
  const dark = theme.palette.mode === 'dark'
  const [items, setItems] = useState<Summary[]>([])
  const [folders, setFolders] = useState<string[]>([])
  const [count, setCount] = useState(0)
  const [q, setQ] = useState('')
  const [folder, setFolder] = useState('')
  const [sel, setSel] = useState<string | null>(null)
  const [detail, setDetail] = useState<Item | null>(null)         // 选中的条目（含密码，只在选中时放在内存里）
  const [edit, setEdit] = useState<Item | null>(null)             // 正在编辑/新建
  const [showPw, setShowPw] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [delAsk, setDelAsk] = useState(false)
  const [recovered, setRecovered] = useState(false)
  const msgTimer = useRef<any>(null)
  const seq = useRef(0)

  const flash = (t: string) => { setMsg(t); clearTimeout(msgTimer.current); msgTimer.current = setTimeout(() => setMsg(''), 4000) }
  const load = useCallback(async (query = q, fol = folder) => {
    const r = await api.vault_list(query, fol)
    if (!r.ok) { setErr(r.error || '读取失败'); return }
    setErr(''); setItems(r.items); setFolders(r.folders); setCount(r.count); setRecovered(!!r.recovered)
  }, [q, folder])
  useEffect(() => { if (active) load() }, [active, q, folder])           // 切进页面、搜索、换文件夹都刷新

  const select = async (id: string | null) => {
    const my = ++seq.current
    setSel(id); setShowPw(false); setMsg(''); setDetail(null)
    if (!id) return
    const r = await api.vault_get(id)
    if (my !== seq.current) return
    if (r.ok) setDetail(r.item); else setErr(r.error || '读取失败')
  }
  // 离开页面时把明文从内存里的界面状态清掉
  useEffect(() => { if (!active) { setDetail(null); setEdit(null); setShowPw(false); setImp(null); seq.current++ } }, [active])
  useEffect(() => { if (active && sel) select(sel) }, [active])

  const copy = async (field: 'username' | 'password' | 'url' | 'notes', label: string) => {
    if (!sel) return
    const r = await api.vault_copy(sel, field)
    flash(r.ok ? (r.secs ? `已复制${label}，${r.secs} 秒后自动清空剪贴板` : `已复制${label}`) : r.error || '复制失败')
  }
  const save = async () => {
    if (!edit) return
    const r = await api.vault_save(edit)
    if (!r.ok) { setErr(r.error || '保存失败'); return }
    setErr(''); setEdit(null)
    await load(); await select(r.id)
  }
  // 同步到服务器（码境账号）
  type SyncSt = { account: boolean; enabled: boolean; last_ok: number }
  const [sy, setSy] = useState<SyncSt | null>(null)
  const [syBusy, setSyBusy] = useState(false)            // 后台正在同步
  const [syErr, setSyErr] = useState('')                 // 最近一次后台同步的错误
  const [syDlg, setSyDlg] = useState<null | { exists: boolean | null; pw: string; pw2: string; busy: boolean; err: string; erase: boolean; closing: boolean }>(null)
  const refreshSy = async () => { const r = await api.vault_sync_status(); if (r.ok) setSy(r); return r.ok ? (r as SyncSt) : null }
  useEffect(() => { if (active) { refreshSy(); api.vault_sync_kick() } }, [active])
  useEvent('vault:sync', (d: any) => {
    if (d.state === 'busy') { setSyBusy(true); return }
    setSyBusy(false)
    if (d.state === 'ok') { setSyErr(''); refreshSy(); if (d.changed) { load(); if (sel) select(sel) } } else setSyErr(d.error || '同步失败')
  })
  const openSy = async () => {
    const d = { exists: null as boolean | null, pw: '', pw2: '', busy: false, err: '', erase: false, closing: false }
    setSyDlg(d)
    const s = await refreshSy()
    if (!s || !s.account || s.enabled) return
    const r = await api.vault_sync_probe()
    setSyDlg((x) => x && (r.ok ? { ...x, exists: r.exists } : { ...x, err: r.error || '连不上服务器' }))
  }
  const enableSy = async () => {
    if (!syDlg) return
    setSyDlg({ ...syDlg, busy: true, err: '' })
    const r = await api.vault_sync_enable(syDlg.pw, syDlg.exists ? undefined : syDlg.pw2)
    if (!r.ok) { setSyDlg((x) => x && { ...x, busy: false, err: r.error || '开启失败' }); return }
    setSyDlg(null); setSyErr(''); await refreshSy(); await load(); flash(r.mode === 'joined' ? '已加入同步，服务器上的密码已合并到本机。' : '已开启同步，保险库已加密上传。')
  }
  const syncNow = async () => {
    if (!syDlg) return
    setSyDlg({ ...syDlg, busy: true, err: '' })
    const r = await api.vault_sync_now()
    setSyDlg((x) => x && { ...x, busy: false, err: r.ok ? '' : r.error || '同步失败' })
    if (r.ok) { setSyErr(''); await refreshSy(); if (r.changed) await load() }
  }
  const disableSy = async () => {
    if (!syDlg) return
    setSyDlg({ ...syDlg, busy: true, err: '' })
    const r = await api.vault_sync_disable(syDlg.erase)
    if (!r.ok) { setSyDlg((x) => x && { ...x, busy: false, err: r.error || '关闭失败' }); return }
    setSyDlg(null); setSyErr(''); await refreshSy(); flash(syDlg.erase ? '已关闭同步，并删除了服务器上的副本。' : '已关闭同步（服务器上的副本还在）。')
  }
  const syLabel = !sy?.enabled ? '同步' : syBusy ? '同步中…' : syErr ? '同步失败' : '已同步'

  // 浏览器扩展
  const [ext, setExt] = useState<null | { st: any; err: string; busy: boolean }>(null)
  const openExt = async () => { setExt({ st: null, err: '', busy: false }); const r = await api.ext_status(); setExt({ st: r.ok ? r : null, err: r.ok ? '' : r.error || '读取失败', busy: false }) }
  const extDo = async (fn: () => Promise<any>) => { setExt((x) => x && { ...x, busy: true, err: '' }); const r = await fn(); setExt((x) => x && { st: r.ok && r.ext_dir ? r : x.st, err: r.ok ? '' : r.error || '操作失败', busy: false }) }

  // 导入（Bitwarden / Chrome / Edge / Firefox 的导出文件）
  type Imp = { path: string; pw: string; need: boolean; busy: boolean; err: string; del: boolean; res: { added: number; skipped: number; total: number; source: string; deleted?: boolean; delete_error?: string } | null }
  const [imp, setImp] = useState<Imp | null>(null)
  const openImport = () => setImp({ path: '', pw: '', need: false, busy: false, err: '', del: false, res: null })
  const pickImport = async () => {
    const p = await api.vault_pick_import()
    if (p) setImp((x) => x && { ...x, path: p, pw: '', need: false, err: '' })
  }
  const runImport = async () => {
    if (!imp || !imp.path) return
    setImp({ ...imp, busy: true, err: '' })
    const r = await api.vault_import(imp.path, imp.pw, imp.del)
    if (r.ok) { setImp({ ...imp, busy: false, need: false, pw: '', res: { added: r.added, skipped: r.skipped, total: r.total, source: r.source, deleted: r.deleted, delete_error: r.delete_error } }); await load('', ''); setQ(''); setFolder(''); return }
    setImp({ ...imp, busy: false, need: !!r.need_password || imp.need, err: r.need_password ? '' : r.error || '导入失败' })
  }
  const remove = async () => {
    if (!sel) return
    setDelAsk(false)
    const r = await api.vault_delete(sel)
    if (!r.ok) { setErr(r.error || '删除失败'); return }
    setSel(null); setDetail(null); await load()
  }

  const dot = '••••••••••••'
  const Field = ({ label, children, actions }: { label: string; children: React.ReactNode; actions?: React.ReactNode }) => (
    <Box sx={{ display: 'grid', gridTemplateColumns: '78px minmax(0,1fr) auto', alignItems: 'center', columnGap: 1, py: 0.9, borderBottom: 1, borderColor: 'divider', '&:last-of-type': { borderBottom: 0 } }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography sx={{ fontSize: 14, wordBreak: 'break-all', userSelect: 'text' }}>{children}</Typography>
      <Box sx={{ display: 'flex' }}>{actions}</Box>
    </Box>
  )
  const Act = ({ tip, onClick, children }: { tip: string; onClick: () => void; children: React.ReactNode }) => <Tooltip title={tip}><IconButton size="small" onClick={onClick}>{children}</IconButton></Tooltip>

  return (
    <BasePage contentStyle={{ height: '100%' }} title="密码" info="本机加密保存，Windows 账户就是钥匙：日常打开就能用，不用输主密码。密码默认不显示；复制后 15 秒自动清空剪贴板。保险库文件在 %APPDATA%\MajingToolbox\vault.dat，别人拿到也打不开。"
      header={<Box sx={{ display: 'flex', gap: 1 }}>
        <Tooltip title={syErr || (sy?.enabled ? (sy.last_ok ? '上次同步 ' + new Date(sy.last_ok * 1000).toLocaleString('zh-CN', { hour12: false }) : '') : '用码境账号把加密后的保险库同步到服务器，多台电脑共用')}>
          <Button size="small" variant="outlined" color={syErr ? 'error' : 'primary'} startIcon={syBusy ? <CircularProgress size={14} /> : <CloudSyncOutlined />} sx={{ ...rounded, textTransform: 'none' }} onClick={openSy}>{syLabel}</Button>
        </Tooltip>
        <Button size="small" variant="outlined" startIcon={<ExtensionOutlined />} sx={{ ...rounded, textTransform: 'none' }} onClick={openExt}>浏览器扩展</Button>
        <Button size="small" variant="outlined" startIcon={<FileDownloadOutlined />} sx={{ ...rounded, textTransform: 'none' }} onClick={openImport}>导入</Button>
        <Button variant="contained" size="small" startIcon={<AddRounded />} sx={rounded} onClick={() => setEdit({ ...EMPTY, folder })}>新建</Button>
      </Box>}>
      <Box sx={{ ...pageGrid, gridTemplateColumns: { xs: 'minmax(0,1fr)', md: 'minmax(0, 1fr) minmax(0, 1.25fr)' }, height: '100%', gridTemplateRows: 'minmax(0, 1fr)', alignItems: 'stretch' }}>
        {/* 左：列表 */}
        <EnhancedCard title="全部密码" icon={<KeyRounded />} action={<Typography variant="body2" color="text.secondary">{count} 项</Typography>}>
          <TextField size="small" fullWidth placeholder="搜索名称、用户名、网址、备注" value={q} onChange={(e) => setQ(e.target.value)} sx={{ mb: 1, '& .MuiOutlinedInput-root': { borderRadius: 2 } }}
            InputProps={{ startAdornment: <InputAdornment position="start"><SearchRounded fontSize="small" /></InputAdornment> }} />
          {folders.length > 0 && (
            <Box sx={{ display: 'flex', gap: 0.6, flexWrap: 'wrap', mb: 1 }}>
              <Chip size="small" label="全部" color={folder === '' ? 'primary' : 'default'} variant={folder === '' ? 'filled' : 'outlined'} onClick={() => setFolder('')} />
              {folders.map((f) => <Chip key={f} size="small" label={f} color={folder === f ? 'primary' : 'default'} variant={folder === f ? 'filled' : 'outlined'} onClick={() => setFolder(f)} />)}
            </Box>
          )}
          {recovered && <Typography variant="caption" color="warning.main" sx={{ mb: 1 }}>保险库主文件有问题，已自动用备份恢复。建议检查数据是否完整。</Typography>}
          <Box sx={{ flex: 1, minHeight: 0, overflowY: 'auto', mx: -0.5 }}>
            {items.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 4, lineHeight: 1.9 }}>{count === 0 ? '还没有密码。点右上角“新建”添加第一条。' : '没有符合的结果。'}</Typography>}
            {items.map((it) => (
              <Box key={it.id} onClick={() => select(it.id)} sx={{ display: 'flex', alignItems: 'center', gap: 1.2, px: 1, py: 0.9, borderRadius: 1.5, cursor: 'pointer', bgcolor: sel === it.id ? alpha(theme.palette.primary.main, dark ? 0.22 : 0.12) : 'transparent', '&:hover': { bgcolor: sel === it.id ? undefined : alpha(theme.palette.primary.main, 0.06) } }}>
                <Box sx={{ width: 34, height: 34, borderRadius: 1.5, flexShrink: 0, bgcolor: alpha(theme.palette.primary.main, 0.13), color: 'primary.main', fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{(it.name || '?').slice(0, 1).toUpperCase()}</Box>
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Typography noWrap sx={{ fontWeight: 600, fontSize: 14 }}>{it.name}</Typography>
                  <Typography noWrap variant="caption" color="text.secondary">{it.type === 'note' ? '安全笔记' : it.username || host(it.url) || ' '}</Typography>
                </Box>
              </Box>
            ))}
          </Box>
          {err && <Typography variant="caption" color="error" sx={{ mt: 1 }}>{err}</Typography>}
        </EnhancedCard>

        {/* 右：详情 */}
        <EnhancedCard title={detail ? detail.name : '详情'} icon={<KeyRounded />} action={detail ? (
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            <Button size="small" startIcon={<EditOutlined />} sx={{ fontWeight: 600 }} onClick={() => setEdit({ ...detail })}>编辑</Button>
            <Button size="small" color="error" startIcon={<DeleteOutline />} sx={{ fontWeight: 600 }} onClick={() => setDelAsk(true)}>删除</Button>
          </Box>) : null}>
          {!detail
            ? <Typography variant="body2" color="text.secondary" sx={{ m: 'auto', textAlign: 'center', lineHeight: 1.9 }}>在左边选一条，这里显示详情。</Typography>
            : <>
              {detail.type === 'login' && <>
                <Field label="用户名" actions={detail.username ? <Act tip="复制用户名" onClick={() => copy('username', '用户名')}><ContentCopyRounded fontSize="small" /></Act> : null}>{detail.username || '—'}</Field>
                <Field label="密码" actions={detail.password ? <>
                  <Act tip={showPw ? '隐藏' : '显示'} onClick={() => setShowPw((v) => !v)}>{showPw ? <VisibilityOffRounded fontSize="small" /> : <VisibilityRounded fontSize="small" />}</Act>
                  <Act tip="复制密码" onClick={() => copy('password', '密码')}><ContentCopyRounded fontSize="small" /></Act></> : null}>
                  <span style={{ fontFamily: showPw ? 'Consolas, monospace' : undefined, letterSpacing: showPw ? 0 : 1 }}>{detail.password ? (showPw ? detail.password : dot) : '—'}</span></Field>
                <Field label="网址" actions={detail.url ? <>
                  <Act tip="在浏览器打开" onClick={() => api.open_url(/^https?:\/\//i.test(detail.url) ? detail.url : 'https://' + detail.url)}><OpenInNewRounded fontSize="small" /></Act>
                  <Act tip="复制网址" onClick={() => copy('url', '网址')}><ContentCopyRounded fontSize="small" /></Act></> : null}>{detail.url || '—'}</Field>
              </>}
              {detail.folder && <Field label="文件夹">{detail.folder}</Field>}
              <Field label="备注">{detail.notes ? <span style={{ whiteSpace: 'pre-wrap' }}>{detail.notes}</span> : '—'}</Field>
              {msg && <Typography variant="caption" color="success.main" sx={{ mt: 1.2 }}>{msg}</Typography>}
            </>}
        </EnhancedCard>
      </Box>

      {/* 新建 / 编辑 */}
      <Dialog open={!!edit} onClose={() => setEdit(null)} PaperProps={{ sx: { borderRadius: 3, width: 460 } }}>
        <DialogTitle sx={{ fontWeight: 700 }}>{edit?.id ? '编辑' : '新建'}</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 1.4, pt: '8px !important' }}>
          {edit && <>
            <ToggleButtonGroup size="small" exclusive value={edit.type} onChange={(_, v) => v && setEdit({ ...edit, type: v })} sx={{ alignSelf: 'flex-start' }}>
              <ToggleButton value="login" sx={{ px: 2 }}>登录信息</ToggleButton>
              <ToggleButton value="note" sx={{ px: 2 }}>安全笔记</ToggleButton>
            </ToggleButtonGroup>
            <TextField size="small" label="名称" required autoFocus value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
            {edit.type === 'login' && <>
              <TextField size="small" label="用户名" value={edit.username} onChange={(e) => setEdit({ ...edit, username: e.target.value })} autoComplete="off" />
              <TextField size="small" label="密码" type={showPw ? 'text' : 'password'} value={edit.password} onChange={(e) => setEdit({ ...edit, password: e.target.value })} autoComplete="new-password"
                InputProps={{ endAdornment: <InputAdornment position="end"><IconButton size="small" onClick={() => setShowPw((v) => !v)}>{showPw ? <VisibilityOffRounded fontSize="small" /> : <VisibilityRounded fontSize="small" />}</IconButton></InputAdornment> }} />
              <TextField size="small" label="网址" value={edit.url} onChange={(e) => setEdit({ ...edit, url: e.target.value })} />
            </>}
            <Autocomplete freeSolo size="small" options={folders} inputValue={edit.folder} onInputChange={(_, v) => setEdit((e) => (e ? { ...e, folder: v } : e))} renderInput={(p) => <TextField {...p} label="文件夹（可选）" />} />
            <TextField size="small" label="备注" multiline minRows={edit.type === 'note' ? 6 : 2} maxRows={10} value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} />
            {err && <Typography variant="caption" color="error">{err}</Typography>}
          </>}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={() => setEdit(null)} sx={rounded}>取消</Button><Button variant="contained" sx={rounded} onClick={save}>保存</Button></DialogActions>
      </Dialog>

      {/* 浏览器扩展 */}
      <Dialog open={!!ext} onClose={() => !ext?.busy && setExt(null)} PaperProps={{ sx: { borderRadius: 3, width: 500 } }}>
        <DialogTitle sx={{ fontWeight: 700 }}>浏览器扩展（Chrome / Edge 自动填充）</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 1.4, pt: '8px !important' }}>
          <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.8 }}>登录页上会出现小钥匙，点一下选择账号即可填充；登录后会问你要不要保存。只有网址匹配的条目才会被取用，也可以用快捷键 Ctrl+Shift+L。</Typography>
          {ext?.st && (
            <>
              <Typography sx={{ fontWeight: 700 }}>第 1 步：安装连接组件</Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
                <Typography variant="body2" color={ext.st.chrome || ext.st.edge ? 'success.main' : 'text.secondary'}>{ext.st.chrome || ext.st.edge ? `已安装（${[ext.st.chrome && 'Chrome', ext.st.edge && 'Edge'].filter(Boolean).join('、')}）` : '还没安装'}</Typography>
                <Button size="small" variant="contained" disabled={ext.busy} sx={rounded} onClick={() => extDo(api.ext_install)}>{ext.st.chrome || ext.st.edge ? '重新安装' : '安装'}</Button>
                {(ext.st.chrome || ext.st.edge) && <Button size="small" disabled={ext.busy} sx={rounded} onClick={() => extDo(api.ext_uninstall)}>卸载</Button>}
              </Box>
              <Typography sx={{ fontWeight: 700 }}>第 2 步：把扩展装进浏览器</Typography>
              <Typography variant="body2" sx={{ lineHeight: 1.9 }}>打开浏览器的扩展管理页 → 打开右上角<b>开发者模式</b> → 点<b>加载已解压的扩展程序</b> → 选择下面这个文件夹。</Typography>
              <Typography variant="body2" sx={{ fontFamily: 'Consolas, monospace', wordBreak: 'break-all', userSelect: 'text', bgcolor: alpha(theme.palette.primary.main, 0.08), borderRadius: 1.5, px: 1.2, py: 0.8 }}>{ext.st.ext_dir}</Typography>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                <Button size="small" variant="outlined" sx={{ ...rounded, textTransform: 'none' }} onClick={() => api.open_path(ext.st.ext_dir)}>打开扩展文件夹</Button>
                <Button size="small" variant="outlined" sx={{ ...rounded, textTransform: 'none' }} onClick={() => api.ext_open_browser('chrome')}>打开 Chrome 扩展页</Button>
                <Button size="small" variant="outlined" sx={{ ...rounded, textTransform: 'none' }} onClick={() => api.ext_open_browser('edge')}>打开 Edge 扩展页</Button>
              </Box>
              <Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1.7 }}>目前是开发者模式安装，浏览器可能提示“停用开发者模式扩展”，点保留即可。这个版本的连接组件依赖本机的 Python 环境（源码运行），打包成安装版后会改成独立组件。</Typography>
            </>
          )}
          {ext?.err && <Typography variant="body2" color="error">{ext.err}</Typography>}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}><Button variant="contained" sx={rounded} onClick={() => setExt(null)}>完成</Button></DialogActions>
      </Dialog>

      {/* 同步 */}
      <Dialog open={!!syDlg} onClose={() => !syDlg?.busy && setSyDlg(null)} PaperProps={{ sx: { borderRadius: 3, width: 460 } }}>
        <DialogTitle sx={{ fontWeight: 700 }}>同步到服务器</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 1.4, pt: '8px !important' }}>
          {syDlg && !sy?.account && <Typography sx={{ lineHeight: 1.8 }}>同步用码境账号当身份。请先到左侧“设置”里点“用码境账号登录”，再回来开启。</Typography>}
          {syDlg && sy?.account && !sy.enabled && (
            <>
              <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.8 }}>保险库在本机加密后再上传，服务器和别人都看不到内容。主密码只在“新电脑第一次开启同步”时要输一次，平时不用。</Typography>
              {syDlg.exists === null && !syDlg.err && <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}><CircularProgress size={16} /><Typography variant="body2" color="text.secondary">正在连接服务器…</Typography></Box>}
              {syDlg.exists === true && <Typography variant="body2" sx={{ lineHeight: 1.8 }}>服务器上已有你的保险库：输入当初设置的<b>主密码</b>，就会把它合并到这台电脑。</Typography>}
              {syDlg.exists === false && <Typography variant="body2" color="warning.main" sx={{ lineHeight: 1.8 }}>第一次开启：请设置一个主密码（至少 8 位）。<b>忘了它，新电脑就解不开服务器上的数据</b>，本机不受影响。</Typography>}
              {syDlg.exists !== null && <TextField size="small" fullWidth autoFocus type="password" label="主密码" value={syDlg.pw} onChange={(e) => setSyDlg({ ...syDlg, pw: e.target.value })}
                onKeyDown={(e) => { if (e.key === 'Enter' && syDlg.exists && syDlg.pw) enableSy() }} />}
              {syDlg.exists === false && <TextField size="small" fullWidth type="password" label="再输一次" value={syDlg.pw2} onChange={(e) => setSyDlg({ ...syDlg, pw2: e.target.value })} />}
            </>
          )}
          {syDlg && sy?.account && sy.enabled && (
            <>
              <Typography sx={{ lineHeight: 1.8 }}>同步已开启{sy.last_ok ? <>，上次同步 {new Date(sy.last_ok * 1000).toLocaleString('zh-CN', { hour12: false })}</> : null}。修改密码后几秒内会自动同步，打开这个页面时也会同步一次。</Typography>
              {syErr && <Typography variant="body2" color="error">{syErr}</Typography>}
              {syDlg.closing && (
                <Box>
                  <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.8 }}>关闭后这台电脑不再同步，本机的密码都保留。其他电脑上的同步不受影响。</Typography>
                  <FormControlLabel control={<Checkbox size="small" checked={syDlg.erase} onChange={(e) => setSyDlg({ ...syDlg, erase: e.target.checked })} />} label="同时删除服务器上的副本（其他电脑下次同步会重新上传）" />
                </Box>
              )}
            </>
          )}
          {syDlg?.err && <Typography variant="body2" color="error" sx={{ lineHeight: 1.7 }}>{syDlg.err}</Typography>}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          {syDlg && sy?.account && sy.enabled ? (
            syDlg.closing
              ? <><Button onClick={() => setSyDlg({ ...syDlg, closing: false, err: '' })} disabled={syDlg.busy} sx={rounded}>返回</Button><Button color="error" variant="contained" disabled={syDlg.busy} sx={rounded} onClick={disableSy}>确认关闭</Button></>
              : <><Button color="error" onClick={() => setSyDlg({ ...syDlg, closing: true, err: '' })} sx={rounded}>关闭同步</Button><Box sx={{ flex: 1 }} /><Button onClick={() => setSyDlg(null)} sx={rounded}>完成</Button><Button variant="contained" disabled={syDlg.busy} sx={rounded} onClick={syncNow}>{syDlg.busy ? '同步中…' : '立即同步'}</Button></>
          ) : (
            <><Button onClick={() => setSyDlg(null)} disabled={syDlg?.busy} sx={rounded}>取消</Button>
              {sy?.account && <Button variant="contained" sx={rounded} disabled={syDlg?.busy || syDlg?.exists === null || !syDlg?.pw || (syDlg?.exists === false && !syDlg?.pw2)} onClick={enableSy}>{syDlg?.busy ? '开启中…' : '开启同步'}</Button>}</>
          )}
        </DialogActions>
      </Dialog>

      {/* 导入 */}
      <Dialog open={!!imp} onClose={() => !imp?.busy && setImp(null)} PaperProps={{ sx: { borderRadius: 3, width: 480 } }}>
        <DialogTitle sx={{ fontWeight: 700 }}>导入密码</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 1.4, pt: '8px !important' }}>
          {imp?.res ? (
            <>
              <Typography sx={{ lineHeight: 1.8 }}>读到 <b>{imp.res.total}</b> 条，新增 <b>{imp.res.added}</b> 条{imp.res.skipped > 0 && `，${imp.res.skipped} 条已存在或名称为空，已跳过`}。</Typography>
              {imp.res.deleted && <Typography variant="body2" color="success.main">导出文件已删除。</Typography>}
              {imp.res.delete_error && <Typography variant="body2" color="error">{imp.res.delete_error}</Typography>}
              {!imp.res.deleted && <Typography variant="body2" color="warning.main" sx={{ lineHeight: 1.8 }}>浏览器导出的 CSV 和未加密的 JSON 里是明文密码：确认导入无误后，请把文件删除（并清空回收站）。</Typography>}
              {imp.res.source === 'bitwarden' && <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.8 }}>二步验证密钥、自定义字段、银行卡/身份信息没有单独字段，都放在了各条目的“备注”里。</Typography>}
              {imp.res.source === 'browser' && <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.8 }}>导入后，浏览器里原来存的密码还在；想只用码境密码的话，可以在浏览器里关掉“提示保存密码”并删除旧密码。</Typography>}
            </>
          ) : imp && (
            <>
              {!imp.path && (
                <>
                  <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.8 }}>支持 Bitwarden 导出的 .json（未加密 / 密码保护）和 .csv，以及 Chrome、Edge、Firefox 导出的密码 .csv。全部在本机解析，不联网。</Typography>
                  <Typography sx={{ fontWeight: 700 }}>从 Chrome / Edge 导入</Typography>
                  <Typography variant="body2" sx={{ lineHeight: 1.9 }}>1. 打开浏览器的密码管理页 → <b>设置</b> → <b>导出密码</b>（会要求验证 Windows 登录）→ 保存成 .csv<br />2. 回到这里，点下面的“选择文件”。</Typography>
                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                    <Button size="small" variant="outlined" sx={{ ...rounded, textTransform: 'none' }} onClick={() => api.ext_open_browser('chrome', 'passwords')}>打开 Chrome 密码管理</Button>
                    <Button size="small" variant="outlined" sx={{ ...rounded, textTransform: 'none' }} onClick={() => api.ext_open_browser('edge', 'passwords')}>打开 Edge 密码管理</Button>
                  </Box>
                  <Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1.7 }}>为什么不直接读浏览器的数据？新版 Chrome/Edge 的密码库有“应用绑定加密”，别的程序读不了，只能走它自己的导出。</Typography>
                </>
              )}
              {imp.path && (
                <>
                  <Typography variant="body2" sx={{ wordBreak: 'break-all', userSelect: 'text' }}>{imp.path}</Typography>
                  {imp.need && <TextField size="small" fullWidth autoFocus type="password" label="文件密码" value={imp.pw} onChange={(e) => setImp({ ...imp, pw: e.target.value })}
                    onKeyDown={(e) => { if (e.key === 'Enter' && imp.pw) runImport() }} helperText="导出加密 .json 时设置的密码（不是 Bitwarden 主密码，除非设成一样）" />}
                  <FormControlLabel control={<Checkbox size="small" checked={imp.del} onChange={(e) => setImp({ ...imp, del: e.target.checked })} />} label="导入成功后删除这个导出文件（直接删除，不进回收站）" />
                </>
              )}
              {imp.err && <Typography variant="body2" color="error" sx={{ lineHeight: 1.7 }}>{imp.err}</Typography>}
            </>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          {imp?.res ? <Button variant="contained" sx={rounded} onClick={() => setImp(null)}>完成</Button> : <>
            <Button onClick={() => setImp(null)} disabled={imp?.busy} sx={rounded}>取消</Button>
            <Button variant={imp?.path ? 'outlined' : 'contained'} disabled={imp?.busy} sx={rounded} onClick={pickImport}>{imp?.path ? '换一个文件' : '选择文件'}</Button>
            {imp?.path && <Button variant="contained" sx={rounded} disabled={imp?.busy || (imp?.need && !imp.pw)} onClick={runImport}>{imp?.busy ? '导入中…' : '导入'}</Button>}</>}
        </DialogActions>
      </Dialog>

      <Dialog open={delAsk} onClose={() => setDelAsk(false)} PaperProps={{ sx: { borderRadius: 3, width: 400 } }}>
        <DialogTitle sx={{ fontWeight: 700 }}>删除“{detail?.name}”？</DialogTitle>
        <DialogContent><Typography sx={{ lineHeight: 1.8 }}>删除后<b>不能恢复</b>。</Typography></DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={() => setDelAsk(false)} sx={rounded}>取消</Button><Button color="error" variant="contained" sx={rounded} onClick={remove}>删除</Button></DialogActions>
      </Dialog>
    </BasePage>
  )
}
