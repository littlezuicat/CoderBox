import DeleteOutline from '@mui/icons-material/DeleteOutline'
import DownloadOutlined from '@mui/icons-material/DownloadOutlined'
import FolderOpenOutlined from '@mui/icons-material/FolderOpenOutlined'
import FormatListBulletedRounded from '@mui/icons-material/FormatListBulletedRounded'
import PlayArrowRounded from '@mui/icons-material/PlayArrowRounded'
import SettingsOutlined from '@mui/icons-material/SettingsOutlined'
import StopRounded from '@mui/icons-material/StopRounded'
import { Box, Button, Chip, MenuItem, TextField, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'
import { BasePage } from '../components/base-page'
import { DropZone, FileRow, InfoTip, pageGrid, rounded, Segment, StateChip } from '../components/common'
import { EnhancedCard } from '../components/enhanced-card'
import { HistoryCard } from '../components/history'
import { human, useEvent, useSetting } from '../hooks'

const KIND: any = { video: ['视频', 'primary'], audio: ['音频', 'success'], image: ['图片', 'secondary'] }
const VSCALE = [['orig', '视频原尺寸'], ['1080', '最大 1080p'], ['720', '最大 720p'], ['480', '最大 480p']]
const ISCALE = [['orig', '图片原尺寸'], ['2048', '长边 2048'], ['1024', '长边 1024'], ['512', '长边 512']]
const QUALITY = ['balanced', 'high', 'small']

type Item = { path: string; name: string; size: number; kind: string; state: 'wait' | 'run' | 'done' | 'err' | 'cancel'; progress: number | null; meta: string; output?: string }
const chipOf = (s: Item['state'], p: number | null): StateChip =>
  s === 'run' ? { label: p != null ? `转换中 ${Math.round(p)}%` : '转换中', color: 'primary' } : s === 'done' ? { label: '完成', color: 'success' } : s === 'err' ? { label: '失败', color: 'error' } : s === 'cancel' ? { label: '已取消', color: 'default' } : { label: '等待', color: 'default' }

const sel = { size: 'small' as const, select: true, fullWidth: true, sx: { mb: 1.2, '& .MuiOutlinedInput-root': { borderRadius: 2 } } }

export default function ConvertPage() {
  const [items, setItems] = useState<Item[]>([])
  const [busy, setBusy] = useState(false)
  const [ff, setFf] = useState<boolean | null>(null)
  const [ffPct, setFfPct] = useState<number | null>(null)
  const [targets, setTargets] = useState<any>({ video: [], audio: [], image: [] })
  const [status, setStatus] = useState('')
  const [tv, setTv] = useSetting('cv_video', 'mp4')
  const [ta, setTa] = useSetting('cv_audio', 'mp3')
  const [ti, setTi] = useSetting('cv_image', 'jpg')
  const [quality, setQuality] = useSetting('cv_quality', 0)
  const [vs, setVs] = useSetting('cv_vscale', 'orig')
  const [is, setIs] = useSetting('cv_iscale', 'orig')
  const last = useRef<string | null>(null)
  const itemsRef = useRef(items); itemsRef.current = items

  useEffect(() => { api.convert_targets().then(setTargets); api.ff_status().then((r: any) => setFf(r.ready)) }, [])
  const installFf = () => { setFfPct(0); api.ff_download() }
  const patch = (idx: number, p: Partial<Item>) => setItems((a) => a.map((it, i) => (i === idx ? { ...it, ...p } : it)))
  const add = async (paths: string[]) => {
    if (busy) return setStatus('正在转换，等这一批完了再加。')
    const info = await api.file_info(paths, 'media')
    if (!info.length) return setStatus('这些文件不是音视频或图片。')
    setItems((a) => {
      const have = new Set(a.map((x) => x.path.toLowerCase()))
      return [...a, ...info.filter((f: any) => !have.has(f.path.toLowerCase())).map((f: any): Item => ({ path: f.path, name: f.name, size: f.size, kind: f.kind, state: 'wait', progress: null, meta: `${KIND[f.kind][0]} · ${human(f.size)}` }))]
    })
  }
  useEvent('files:convert', (paths: string[]) => add(paths))
  useEvent('ff:progress', (d: any) => setFfPct(Math.round((d.got * 100) / Math.max(1, d.total))))
  useEvent('ff:done', (d: any) => { setFfPct(null); if (d.error) setStatus('下载失败：' + d.error); api.ff_status().then((r: any) => setFf(r.ready)) })
  useEvent('cv:file', (d: any) => {
    if (d.state === 'run') patch(d.idx, { state: 'run', progress: 0, meta: '转换中…' })
    else if (d.state === 'done') { last.current = d.output; patch(d.idx, { state: 'done', progress: null, output: d.output, meta: `${human(d.size)} · 已保存为 ${String(d.output).split(/[\\/]/).pop()} · 点击定位文件` }) }
    else if (d.state === 'err') patch(d.idx, { state: 'err', progress: null, meta: d.error })
    else patch(d.idx, { state: 'cancel', progress: null, meta: '已取消' })
  })
  useEvent('cv:progress', (d: any) => patch(d.idx, { progress: d.f * 100, meta: d.eta > 0 ? `剩余约 ${d.eta} 秒` : '转换中…' }))
  useEvent('cv:done', () => { setBusy(false); const l = itemsRef.current; setStatus(`转换结束：成功 ${l.filter((x) => x.state === 'done').length} 个，共 ${l.length} 个。`); const o = [...l].reverse().find((x) => x.output)?.output; if (o) api.reveal(o) })       // 转完自动打开文件所在位置

  const kinds = new Set(items.map((x) => x.kind))
  const show = (k: string) => kinds.has(k)       // 拖进文件后自动识别是视频/音频/图片，只出对应的那一项
  const start = async () => {
    if (!items.length) return setStatus('先把文件拖进来。')
    if (!ff) return setStatus('先点右上角“安装转换组件”。')
    setItems((a) => a.map((x) => ({ ...x, state: 'wait', progress: null, output: undefined })))
    setBusy(true); setStatus('正在转换…')
    const pick = { video: tv, audio: ta, image: ti } as any
    const ok = await api.convert_start(items.map((x) => ({ path: x.path, kind: x.kind, target: pick[x.kind] })), QUALITY[quality], vs, is)
    if (!ok) { setBusy(false); setStatus('没法开始转换。') }
  }

  return (
    <BasePage title="格式转换" info="视频、音频、图片互相转换，在本机进行，文件不上传；编码合适时直接换封装，画质无损。" header={ff === null ? null : ff
      ? <Chip color="success" variant="outlined" label="转换组件已就绪" sx={{ fontWeight: 700 }} />
      : <Chip color="warning" variant="outlined" icon={<DownloadOutlined />} clickable={ffPct == null} onClick={ffPct == null ? installFf : undefined}
          label={ffPct != null ? `正在安装转换组件… ${ffPct}%` : '点击安装转换组件（约 76 MB）'} sx={{ fontWeight: 700, cursor: ffPct == null ? 'pointer' : 'default' }} />}>
      <Box sx={pageGrid}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, minWidth: 0 }}>
          <DropZone disabled={busy} title="把视频、音频或图片拖到这里" hint="或点击选择 · 视频、音频、图片都行" onPick={async () => { const f = await api.pick_files('media'); if (f?.length) add(f) }} />
          <EnhancedCard title="转换队列" icon={<FormatListBulletedRounded />} action={items.length ? <Typography variant="body2" color="text.secondary">{items.length} 个文件</Typography> : null} minHeight={140}>
            {items.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 2.5 }}>暂无文件</Typography>}
            {items.map((it, i) => (
              <FileRow key={it.path} chip={KIND[it.kind][0]} color={KIND[it.kind][1]} name={it.name} meta={it.meta} progress={it.progress} state={chipOf(it.state, it.progress)}
                onRemove={busy ? undefined : () => setItems((a) => a.filter((_, k) => k !== i))} onOpen={() => it.output && api.reveal(it.output)} />
            ))}
            {status && <Typography variant="caption" color="text.secondary" sx={{ mt: 1, userSelect: 'text' }}>{status}</Typography>}
          </EnhancedCard>
          <HistoryCard kind="convert" chip="转换" color="primary" />
        </Box>
        <EnhancedCard title="输出设置" icon={<SettingsOutlined />}>
          {show('video') && <TextField {...sel} label="视频转成" value={tv} onChange={(e) => setTv(e.target.value)} disabled={busy}>{targets.video.map((t: any) => <MenuItem key={t.key} value={t.key}>{t.label}</MenuItem>)}</TextField>}
          {show('audio') && <TextField {...sel} label="音频转成" value={ta} onChange={(e) => setTa(e.target.value)} disabled={busy}>{targets.audio.map((t: any) => <MenuItem key={t.key} value={t.key}>{t.label}</MenuItem>)}</TextField>}
          {show('image') && <TextField {...sel} label="图片转成" value={ti} onChange={(e) => setTi(e.target.value)} disabled={busy}>{targets.image.map((t: any) => <MenuItem key={t.key} value={t.key}>{t.label}</MenuItem>)}</TextField>}
          {items.length === 0 && <Typography color="text.secondary" sx={{ fontSize: 13, lineHeight: 1.8, py: 1 }}>把文件拖进来，会自动识别是视频、音频还是图片，这里只显示对应的输出设置。</Typography>}
          {items.length > 0 && <>
            <Typography variant="caption" color="text.secondary" sx={{ mb: 0.6 }}>质量</Typography>
            <Segment disabled={busy} value={quality} options={['均衡', '高画质', '小体积']} onChange={setQuality} />
          </>}
          {(show('video') || show('image')) && <Box sx={{ mt: 1.5 }}>
            {show('video') && <TextField {...sel} label="视频尺寸" value={vs} onChange={(e) => setVs(e.target.value)} disabled={busy}>{VSCALE.map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}</TextField>}
            {show('image') && <TextField {...sel} label="图片尺寸" value={is} onChange={(e) => setIs(e.target.value)} disabled={busy}>{ISCALE.map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}</TextField>}
          </Box>}
          <Box sx={{ flex: 1, minHeight: 20 }} />
          {busy
            ? <Button variant="contained" color="error" size="large" startIcon={<StopRounded />} sx={rounded} onClick={() => api.convert_stop()}>停止</Button>
            : <Button variant="contained" size="large" startIcon={<PlayArrowRounded />} sx={rounded} onClick={start}>开始转换</Button>}
          <Button variant="outlined" disabled={busy} startIcon={<DeleteOutline />} sx={{ ...rounded, mt: 1 }} onClick={() => setItems([])}>清空列表</Button>
          <Button variant="outlined" disabled={!items.some((x) => x.output)} startIcon={<FolderOpenOutlined />} sx={{ ...rounded, mt: 1 }} onClick={() => { const o = last.current || items.find((x) => x.output)?.output; o && api.reveal(o) }}>打开输出位置</Button>
        </EnhancedCard>
      </Box>
    </BasePage>
  )
}
