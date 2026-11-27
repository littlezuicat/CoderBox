// 文献翻译：输入即译的工作台 + 在线 API 设置 + 全局划词热键。
// 移植自开源项目 FlashTrans（https://github.com/chai1220/FlashTrans ，MIT，作者 chai1220）的在线 API 路径，后端见 py/majing/core/litrans.py。
import ArrowBackRounded from '@mui/icons-material/ArrowBackRounded'
import ContentCopyOutlined from '@mui/icons-material/ContentCopyOutlined'
import MenuBookRounded from '@mui/icons-material/MenuBookRounded'
import SettingsOutlined from '@mui/icons-material/SettingsOutlined'
import TranslateRounded from '@mui/icons-material/TranslateRounded'
import { Box, Button, Checkbox, CircularProgress, FormControlLabel, IconButton, MenuItem, Switch, TextField, Tooltip, Typography, useTheme } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'
import { EnhancedCard } from '../components/enhanced-card'
import { useEvent } from '../hooks'

type Cfg = { base_url: string; model: string; target: string; auto_swap: boolean; domain: string; hotkey_on: boolean; hotkey: string; stay: number }

export default function LiteraturePage({ onBack }: { onBack: () => void }) {
  const dark = useTheme().palette.mode === 'dark'
  const [cfg, setCfg] = useState<Cfg | null>(null)
  const [langs, setLangs] = useState<string[][]>([])
  const [hasKey, setHasKey] = useState(false)
  const [hkErr, setHkErr] = useState('')
  const [form, setForm] = useState({ base_url: '', model: '', domain: '', hotkey: 'F1', stay: '10', key: '' })
  const [src, setSrc] = useState('')
  const [out, setOut] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [test, setTest] = useState<{ busy?: boolean; ok?: boolean; text: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const rid = useRef(0)

  const apply = (r: any) => {
    setCfg(r.cfg); setLangs(r.langs); setHasKey(r.has_key); setHkErr(r.hotkey_error || '')
    setForm((f) => ({ ...f, base_url: r.cfg.base_url, model: r.cfg.model, domain: r.cfg.domain, hotkey: r.cfg.hotkey, stay: String(r.cfg.stay) }))
  }
  useEffect(() => { api.lit_get().then(apply); api.lit_warmup() }, [])
  const save = async (patch: Record<string, any>) => { const r = await api.lit_set(patch); setCfg(r.cfg); setHasKey(r.has_key); setHkErr(r.hotkey_error || ''); return r }

  // 输入即译：停手 250ms 后发请求；新的请求会作废旧的
  useEffect(() => {
    const t = setTimeout(() => {
      const id = ++rid.current
      if (!src.trim()) { setOut(''); setBusy(false); setErr(''); return }
      setBusy(true); setErr(''); setOut('')
      api.lit_translate(id, src)
    }, 250)
    return () => clearTimeout(t)
  }, [src, cfg?.target, cfg?.auto_swap, cfg?.domain, cfg?.model, cfg?.base_url])
  useEvent('lit:delta', (d) => { if (d.id === rid.current) setOut((o) => o + d.text) })
  useEvent('lit:done', (d) => { if (d.id === rid.current) { setBusy(false); setOut(d.full) } })
  useEvent('lit:error', (d) => { if (d.id === rid.current) { setBusy(false); setErr(d.message) } })

  const saveAndTest = async () => {
    setTest({ busy: true, text: '' })
    await save({ base_url: form.base_url.trim(), model: form.model.trim(), domain: form.domain, ...(form.key ? { api_key: form.key } : {}) })
    setForm((f) => ({ ...f, key: '' }))
    const r = await api.lit_test()
    setTest(r.ok ? { ok: true, text: `连通，${r.ms} 毫秒` } : { ok: false, text: r.error || '连不上' })
  }
  const copy = async () => { await api.lit_copy(out); setCopied(true); setTimeout(() => setCopied(false), 1200) }
  const card = dark ? '#282a36' : '#ffffff'
  const area = { '& .MuiOutlinedInput-root': { alignItems: 'flex-start', fontSize: 14.5, lineHeight: 1.7, bgcolor: dark ? '#1f212c' : '#f7f8fa' }, '& fieldset': { border: 'none' } }

  if (!cfg) return <Box sx={{ p: 4, textAlign: 'center' }}><CircularProgress size={22} /></Box>
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, pb: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Tooltip title="返回"><IconButton size="small" onClick={onBack}><ArrowBackRounded fontSize="small" /></IconButton></Tooltip>
        <Typography variant="caption" color="text.secondary">输入即译；开了划词热键后，在任何程序里选中文字按热键，译文弹在鼠标旁边</Typography>
      </Box>

      <EnhancedCard title="翻译" icon={<TranslateRounded />} minHeight={120}
        action={<Box sx={{ display: 'flex', alignItems: 'center', gap: 1.2 }}>
          <FormControlLabel sx={{ m: 0 }} control={<Checkbox size="small" checked={cfg.auto_swap} onChange={(_, v) => save({ auto_swap: v })} />}
            label={<Typography variant="caption">原文是目标语言时反向翻译</Typography>} />
          <TextField select size="small" value={cfg.target} onChange={(e) => save({ target: e.target.value })} sx={{ minWidth: 150, '& .MuiSelect-select': { py: 0.6, fontSize: 13 } }}>
            {langs.map(([c, n]) => <MenuItem key={c} value={c} dense>译为 {n}</MenuItem>)}
          </TextField>
        </Box>}>
        <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 1.5 }}>
          <TextField fullWidth multiline minRows={9} maxRows={16} placeholder="粘贴或输入要翻译的文字…" value={src} onChange={(e) => setSrc(e.target.value)} sx={area} />
          <Box sx={{ position: 'relative', minWidth: 0 }}>
            <TextField fullWidth multiline minRows={9} maxRows={16} value={out} placeholder={busy ? '' : '译文显示在这里'} slotProps={{ input: { readOnly: true } }} sx={area} />
            <Box sx={{ position: 'absolute', right: 6, top: 6, display: 'flex', alignItems: 'center', gap: 0.5 }}>
              {busy && <CircularProgress size={14} />}
              <Tooltip title={copied ? '已复制' : '复制译文'}><span><IconButton size="small" disabled={!out} onClick={copy}><ContentCopyOutlined sx={{ fontSize: 17 }} /></IconButton></span></Tooltip>
            </Box>
          </Box>
        </Box>
        {err && <Typography sx={{ mt: 1, fontSize: 12.5, color: 'error.main' }}>{err}</Typography>}
      </EnhancedCard>

      <EnhancedCard title="接口与热键" icon={<SettingsOutlined />} minHeight={120}>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 1.5 }}>
          <TextField fullWidth size="small" label="接口地址" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://api.deepseek.com" helperText="任何 OpenAI 兼容接口（DeepSeek、Kimi、硅基流动等），会自动补 /chat/completions" />
          <TextField fullWidth size="small" label="模型" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="deepseek-flash" helperText="按服务商文档填模型名" />
          <TextField fullWidth size="small" type="password" label="密钥（API Key）" value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} placeholder={hasKey ? '已保存（不显示），要换的话在这里重新填' : 'sk-…'} autoComplete="off"
            helperText="用 Windows 账户加密后保存在本机，不会上传" />
          <TextField fullWidth size="small" label="额外要求（可选）" value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} placeholder="例如：计算机视觉论文，专业术语保留英文" helperText="领域、术语、风格，会加进翻译提示词" />
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 1.5 }}>
          <Button variant="contained" size="small" disabled={test?.busy} onClick={saveAndTest} sx={{ borderRadius: 2 }}>保存并测试连接</Button>
          {test?.busy && <CircularProgress size={16} />}
          {test && !test.busy && <Typography sx={{ fontSize: 12.5, color: test.ok ? 'success.main' : 'error.main', minWidth: 0, wordBreak: 'break-all' }}>{test.text}</Typography>}
        </Box>

        <Box sx={{ mt: 2, pt: 1.5, borderTop: 1, borderColor: 'divider', display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
          <FormControlLabel sx={{ m: 0 }} control={<Switch size="small" checked={cfg.hotkey_on} onChange={(_, v) => save({ hotkey_on: v, hotkey: form.hotkey })} />}
            label={<Typography sx={{ fontSize: 13.5, fontWeight: 600 }}>划词翻译热键</Typography>} />
          <TextField size="small" value={form.hotkey} onChange={(e) => setForm({ ...form, hotkey: e.target.value })} onBlur={() => form.hotkey !== cfg.hotkey && save({ hotkey: form.hotkey })} sx={{ width: 150 }} placeholder="F1" />
          <TextField size="small" value={form.stay} onChange={(e) => setForm({ ...form, stay: e.target.value.replace(/\D/g, '') })} onBlur={() => save({ stay: Number(form.stay || 0) })} sx={{ width: 118 }}
            slotProps={{ input: { endAdornment: <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>秒后收起</Typography> } }} />
          <Typography variant="caption" color="text.secondary">写法：F1、Alt+Q、Ctrl+Shift+T。收起时间填 0 = 不自动收起。</Typography>
        </Box>
        {hkErr && <Typography sx={{ mt: 1, fontSize: 12.5, color: 'error.main' }}>{hkErr}</Typography>}
        {cfg.hotkey_on && !hkErr && <Typography sx={{ mt: 1, fontSize: 12.5, color: 'success.main' }}>热键 {cfg.hotkey} 已生效（工具箱缩到托盘时也有效）。</Typography>}
      </EnhancedCard>

      <Typography variant="caption" color="text.secondary" sx={{ px: 0.5 }}>
        翻译部分移植自开源项目 FlashTrans（作者 chai1220，MIT 许可证）：复用连接、关闭 DeepSeek 思考、译文缓存、划词取词。本地模型和截图 OCR 没有移植。
      </Typography>
    </Box>
  )
}

export const LiteratureIcon = MenuBookRounded
