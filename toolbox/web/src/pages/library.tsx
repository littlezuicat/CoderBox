// 图书馆：输入文章名 → 服务器检索（S2/Crossref）→ 自动判定出版商 → 服务器三通道取 PDF → 落本地
// 后端见 py/majing/core/paperdl.py + 服务端 paperdl-service（worker2）
import AccessTimeRounded from '@mui/icons-material/AccessTimeRounded'
import CloudDownloadRounded from '@mui/icons-material/CloudDownloadRounded'
import FolderOpenRounded from '@mui/icons-material/FolderOpenRounded'
import MenuBookRounded from '@mui/icons-material/MenuBookRounded'
import SearchRounded from '@mui/icons-material/SearchRounded'
import { alpha, Box, Button, Chip, CircularProgress, IconButton, InputAdornment, LinearProgress, TextField, Tooltip, Typography, useTheme } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'
import { BasePage } from '../components/base-page'

type Item = {
  title: string; year?: number; venue?: string; citations?: number
  doi: string; provider: string; is_oa?: boolean; authors?: string[]
}
type Job = { job_id: string; doi: string; title?: string; provider?: string; status: string; bytes?: number; path?: string; error?: string }

const PROVIDER: Record<string, { label: string; color: 'primary' | 'secondary' | 'success' | 'warning' | 'info' | 'error' }> = {
  ieee: { label: 'IEEE', color: 'primary' },
  elsevier: { label: 'Elsevier', color: 'warning' },
  springer: { label: 'Springer', color: 'success' },
  acm: { label: 'ACM', color: 'info' },
  other: { label: '其他', color: 'secondary' },
}

export default function LibraryPage() {
  const dark = useTheme().palette.mode === 'dark'
  const [q, setQ] = useState('')
  const [items, setItems] = useState<Item[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [health, setHealth] = useState<any>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const timers = useRef<Record<string, any>>({})

  useEffect(() => {
    api.paperdl_health().then((r: any) => setHealth(r))
    return () => { Object.values(timers.current).forEach(clearInterval) }
  }, [])

  const search = async () => {
    const t = q.trim()
    if (!t || busy) return
    setBusy(true); setErr(''); setItems([])
    try {
      const r = await api.paperdl_search(t, 20)
      if (!r?.ok) setErr(r?.error || '检索失败')
      else if (!r.items?.length) setErr('没有检索到结果')
      else setItems(r.items)
    } catch (e: any) { setErr(String(e?.message || e)) }
    setBusy(false)
  }

  const poll = (job_id: string, doi: string) => {
    if (timers.current[job_id]) return
    timers.current[job_id] = setInterval(async () => {
      const st = await api.paperdl_status(job_id)
      setJobs((js) => js.map((j) => (j.job_id === job_id ? { ...j, status: st.status, bytes: st.bytes, error: st.reason } : j)))
      if (st.status === 'done') {
        clearInterval(timers.current[job_id]); delete timers.current[job_id]
        const d = await api.paperdl_download(job_id)
        setJobs((js) => js.map((j) => (j.job_id === job_id ? { ...j, status: d.ok ? 'saved' : 'error', path: d.path, error: d.error } : j)))
      } else if (st.status === 'failed') {
        clearInterval(timers.current[job_id]); delete timers.current[job_id]
      }
    }, 3000)
  }

  const download = async (it: Item) => {
    setErr('')
    const r = await api.paperdl_submit(it.doi, it.title)
    if (!r?.ok) { setErr(r?.error || '提交失败'); return }
    const job: Job = { job_id: r.job_id, doi: r.doi, title: it.title, provider: r.provider, status: 'pending' }
    setJobs((js) => [job, ...js.filter((j) => j.job_id !== job.job_id)])
    poll(r.job_id, r.doi)
  }

  const row = (it: Item, i: number) => {
    const p = PROVIDER[it.provider] || PROVIDER.other
    return (
      <Box key={it.doi + i} sx={{
        display: 'flex', gap: 1.5, alignItems: 'flex-start', p: 1.4, borderRadius: 2,
        border: '1px solid', borderColor: dark ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.07)',
        bgcolor: dark ? 'rgba(255,255,255,.02)' : '#fff', '&:hover': { borderColor: 'primary.main' },
      }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontSize: 13.5, fontWeight: 600, lineHeight: 1.35 }} noWrap title={it.title}>{it.title}</Typography>
          <Box sx={{ display: 'flex', gap: 1, mt: .5, flexWrap: 'wrap', alignItems: 'center' }}>
            <Chip size="small" label={p.label} color={p.color} variant={dark ? 'outlined' : 'filled'} sx={{ height: 19, fontSize: 11 }} />
            {it.year && <Typography variant="caption" color="text.secondary">{it.year}</Typography>}
            {it.venue && <Typography variant="caption" color="text.secondary" noWrap sx={{ maxWidth: 260 }} title={it.venue}>{it.venue}</Typography>}
            {typeof it.citations === 'number' && <Typography variant="caption" color="text.secondary">引用 {it.citations}</Typography>}
            {it.is_oa && <Chip size="small" label="OA" sx={{ height: 18, fontSize: 10.5 }} />}
          </Box>
          <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>{it.doi}</Typography>
        </Box>
        <Button size="small" variant="contained" startIcon={<CloudDownloadRounded />} onClick={() => download(it)} sx={{ flex: '0 0 auto', mt: .3 }}>下载</Button>
      </Box>
    )
  }

  const jobRow = (j: Job) => {
    const done = j.status === 'saved'
    const bad = j.status === 'failed' || j.status === 'error'
    const running = j.status === 'running' || j.status === 'pending'
    const text = done ? `${((j.bytes || 0) / 1048576).toFixed(1)} MB 已保存`
      : bad ? (j.error || '失败')
        : j.status === 'running' ? '服务器取件中…' : '排队中…'
    return (
      <Box key={j.job_id} sx={{ p: 1.2, borderRadius: 2, mb: 1, bgcolor: dark ? 'rgba(255,255,255,.03)' : 'rgba(0,0,0,.02)' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {running ? <CircularProgress size={15} /> : done ? <CloudDownloadRounded fontSize="small" color="success" /> : <AccessTimeRounded fontSize="small" color="error" />}
          <Typography sx={{ fontSize: 12.5, flex: 1, minWidth: 0 }} noWrap title={j.title || j.doi}>{j.title || j.doi}</Typography>
          {done && (
            <Tooltip title="在文件夹中显示">
              <IconButton size="small" onClick={() => api.paperdl_open_file(j.path)}><FolderOpenRounded fontSize="small" /></IconButton>
            </Tooltip>
          )}
        </Box>
        {running && <LinearProgress sx={{ mt: .8, height: 3, borderRadius: 2 }} />}
        <Typography variant="caption" color={bad ? 'error' : 'text.secondary'} sx={{ display: 'block', mt: .4, fontSize: 11 }} noWrap>{text}</Typography>
      </Box>
    )
  }

  return (
    <BasePage title="图书馆" info="输入文章名，服务器自动判定 IEEE / Elsevier / Springer 并取回 PDF">
      <Box sx={{ display: 'flex', gap: 1, mb: 1.4 }}>
        <TextField
          fullWidth size="small" value={q} placeholder="输入文章标题，例如：single image dehazing network"
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') search() }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchRounded fontSize="small" /></InputAdornment> }}
        />
        <Button variant="contained" onClick={search} disabled={busy || !q.trim()} sx={{ flex: '0 0 auto', minWidth: 92 }}>
          {busy ? <CircularProgress size={18} color="inherit" /> : '检索'}
        </Button>
        <Tooltip title="打开论文保存目录">
          <IconButton onClick={() => api.paperdl_open_folder()} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
            <FolderOpenRounded />
          </IconButton>
        </Tooltip>
      </Box>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.2 }}>
        <MenuBookRounded fontSize="small" sx={{ color: 'text.secondary' }} />
        <Typography variant="caption" color="text.secondary">
          {health?.ok ? `服务在线 · 队列 ${health.pending ?? 0} 待处理` : health ? '服务离线' : '连接中…'}
        </Typography>
      </Box>

      {err && <Typography variant="caption" color="error" sx={{ display: 'block', mb: 1 }}>{err}</Typography>}

      {jobs.length > 0 && (
        <Box sx={{ mb: 1.6 }}>
          <Typography sx={{ fontSize: 12.5, fontWeight: 700, mb: .8, color: 'text.secondary' }}>下载任务</Typography>
          {jobs.map(jobRow)}
        </Box>
      )}

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        {items.map(row)}
      </Box>

      {!items.length && !busy && !err && (
        <Box sx={{ py: 6, textAlign: 'center', borderRadius: 3, border: '1px dashed', borderColor: 'divider', bgcolor: alpha(dark ? '#fff' : '#000', 0.02) }}>
          <MenuBookRounded sx={{ fontSize: 42, color: 'text.disabled' }} />
          <Typography sx={{ mt: 1, fontSize: 13, color: 'text.secondary' }}>输入文章名开始检索</Typography>
          <Typography variant="caption" color="text.disabled">支持 IEEE · Elsevier · Springer · OA/arXiv</Typography>
        </Box>
      )}
    </BasePage>
  )
}
