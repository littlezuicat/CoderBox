import DownloadOutlined from '@mui/icons-material/DownloadOutlined'
import PlayArrowRounded from '@mui/icons-material/PlayArrowRounded'
import SettingsOutlined from '@mui/icons-material/SettingsOutlined'
import StopRounded from '@mui/icons-material/StopRounded'
import { Box, Button, Chip, MenuItem, TextField, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'
import { BasePage } from '../components/base-page'
import { rounded, Segment, StateChip, pageGrid } from '../components/common'
import { EnhancedCard } from '../components/enhanced-card'
import { FlowArrow, InputBox, OutFile, OutputBox } from '../components/flow'
import { human, useEvent, useSetting } from '../hooks'

const KIND: any = { video: ['视频', 'primary'], audio: ['音频', 'success'], image: ['图片', 'secondary'] }
const VSCALE = [['orig', '视频原尺寸'], ['1080', '最大 1080p'], ['720', '最大 720p'], ['480', '最大 480p']]
const ISCALE = [['orig', '图片原尺寸'], ['2048', '长边 2048'], ['1024', '长边 1024'], ['512', '长边 512']]
const QUALITY = ['balanced', 'high', 'small']

// 输入队列：转完一个就从队列里清掉一个（成功的移到下面的输出区）；失败/取消的留在队列里，可以再转
type Item = { path: string; name: string; size: number; kind: string; state: 'idle' | 'wait' | 'run' | 'err' | 'cancel'; progress: number | null; info: string; meta: string }
type R = { key: string; path: string; name: string; kind: string; meta: string }
const chipOf = (s: Item['state'], p: number | null): StateChip =>
  s === 'run' ? { label: p != null ? `转换中 ${Math.round(p)}%` : '转换中', color: 'primary' } : s === 'err' ? { label: '失败', color: 'error' } : s === 'cancel' ? { label: '已取消', color: 'default' } : { label: '等待', color: 'default' }
const base = (p: string) => p.split(/[\\/]/).pop() || p

const sel = { size: 'small' as const, select: true, fullWidth: true, sx: { mb: 1.2, '& .MuiOutlinedInput-root': { borderRadius: 2 } } }

export default function ConvertPage() {
  const [items, setItems] = useState<Item[]>([])
  const [results, setResults] = useState<R[]>([])
  const [busy, setBusy] = useState(false)
  const [batch, setBatch] = useState({ n: 0, done: 0 })
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
  const itemsRef2 = useRef(items); itemsRef2.current = items
  const batchRef = useRef<string[]>([])         // 这一批的文件路径（后端按序号回报，队列会变，所以按路径找）
  const batchKinds = useRef<string[]>([])
  const okRef = useRef(0)
  const lastOut = useRef<string | null>(null)

  const installFf = () => { setFfPct(0); api.ff_download() }
  // 进入工具箱就检查转换组件；没有就自动下载安装（不用点确认）。下载失败的话页面右上角还能点一下重试，下次打开也会再试
  useEffect(() => { api.convert_targets().then(setTargets); api.ff_status().then((r: any) => { setFf(r.ready); if (!r.ready) installFf() }) }, [])
  const patch = (path: string, p: Partial<Item>) => setItems((a) => a.map((it) => (it.path === path ? { ...it, ...p } : it)))
  const add = async (paths: string[]) => {
    if (busy) return setStatus('正在转换，等这一批完了再加。')
    const info = await api.file_info(paths, 'media')
    if (!info.length) return setStatus('这些文件不是音视频或图片。')
    setStatus('')
    setItems((a) => {
      const have = new Set(a.map((x) => x.path.toLowerCase()))
      return [...a, ...info.filter((f: any) => !have.has(f.path.toLowerCase())).map((f: any): Item => ({ path: f.path, name: f.name, size: f.size, kind: f.kind, state: 'idle', progress: null, info: `${KIND[f.kind][0]} · ${human(f.size)}`, meta: '' }))]
    })
  }
  useEvent('files:convert', (paths: string[]) => add(paths))
  useEvent('ff:progress', (d: any) => setFfPct(Math.round((d.got * 100) / Math.max(1, d.total))))
  useEvent('ff:done', (d: any) => { setFfPct(null); if (d.error) setStatus('下载失败：' + d.error); api.ff_status().then((r: any) => setFf(r.ready)) })
  useEvent('cv:file', (d: any) => {
    const path = batchRef.current[d.idx]; if (!path) return
    if (d.state === 'run') patch(path, { state: 'run', progress: 0, meta: '转换中…' })
    else if (d.state === 'done') {
      okRef.current += 1; lastOut.current = d.output
      const kind = itemsRef2.current.find((x) => x.path === path)?.kind || 'image'
      setItems((a) => a.filter((x) => x.path !== path))          // 转完一个，清掉一个
      setResults((r) => [...r, { key: d.output, path: d.output, name: base(d.output), kind, meta: human(d.size) }])
      setBatch((b) => ({ ...b, done: b.done + 1 }))
    } else if (d.state === 'err') { patch(path, { state: 'err', progress: null, meta: d.error }); setBatch((b) => ({ ...b, done: b.done + 1 })) }
    else { patch(path, { state: 'cancel', progress: null, meta: '已取消' }); setBatch((b) => ({ ...b, done: b.done + 1 })) }
  })
  useEvent('cv:progress', (d: any) => { const path = batchRef.current[d.idx]; if (path) patch(path, { progress: d.f * 100, meta: d.eta > 0 ? `剩余约 ${d.eta} 秒` : '转换中…' }) })
  useEvent('cv:done', () => {
    setBusy(false)
    setItems((a) => a.map((x) => (x.state === 'wait' ? { ...x, state: 'idle', meta: '' } : x)))        // 被停止后没轮到的，回到待转状态
    setStatus(`转换结束：成功 ${okRef.current} 个，共 ${batchRef.current.length} 个。`)
    if (lastOut.current) api.reveal(lastOut.current)       // 转完自动打开文件所在位置
  })

  const kinds = new Set([...items.map((x) => x.kind), ...(busy ? batchKinds.current : [])])      // 转换中队列会一个个清掉，设置项要保持不变
  const show = (k: string) => kinds.has(k)       // 拖进文件后自动识别是视频/音频/图片，只出对应的那一项
  const start = async () => {
    if (busy || !items.length) return          // 队列是空的就不能转
    if (!ff) return setStatus(ffPct != null ? '转换组件正在安装，装好就能转了。' : '转换组件还没装好，点右上角重试。')
    batchRef.current = items.map((x) => x.path); batchKinds.current = items.map((x) => x.kind); okRef.current = 0; lastOut.current = null
    setBatch({ n: items.length, done: 0 })
    setItems((a) => a.map((x) => ({ ...x, state: 'wait', progress: null, meta: '' })))
    setBusy(true); setStatus('')
    const pick = { video: tv, audio: ta, image: ti } as any
    const ok = await api.convert_start(items.map((x) => ({ path: x.path, kind: x.kind, target: pick[x.kind] })), QUALITY[quality], vs, is)
    if (!ok) { setBusy(false); setStatus('没法开始转换。') }
  }

  // 下面的输出区只放转成功的，最新的在最上面（可以拖出去）；转换进度、失败原因都显示在上面的队列里
  const outs: OutFile[] = [...results].reverse().map((r): OutFile => ({ key: r.key, chip: KIND[r.kind][0], color: KIND[r.kind][1], name: r.name, meta: r.meta, state: { label: '完成', color: 'success' }, path: r.path }))
  const cur = items.find((x) => x.state === 'run')
  const percent = busy && batch.n ? ((batch.done + (cur ? (cur.progress || 0) / 100 : 0)) * 100) / batch.n : null
  const arrowText = busy ? (cur ? `正在转换 ${Math.min(batch.done + 1, batch.n)} / ${batch.n}：${cur.name}` : '准备中…') : status

  return (
    <BasePage contentStyle={{ height: '100%' }} title="格式转换" info="视频、音频、图片互相转换，在本机进行，文件不上传；编码合适时直接换封装，画质无损。转换好的文件在下面，按住可以拖出去保存；转完一个，上面就清掉一个。" header={ff === null ? null : ff
      ? <Chip color="success" variant="outlined" label="转换组件已就绪" sx={{ fontWeight: 700 }} />
      : <Chip color="warning" variant="outlined" icon={<DownloadOutlined />} clickable={ffPct == null} onClick={ffPct == null ? installFf : undefined}
          label={ffPct != null ? `正在安装转换组件… ${ffPct}%` : '转换组件没装好，点击重试（约 45 MB）'} sx={{ fontWeight: 700, cursor: ffPct == null ? 'pointer' : 'default' }} />}>
      <Box sx={{ ...pageGrid, height: '100%', gridTemplateRows: 'minmax(0, 1fr)', alignItems: 'stretch' }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0 }}>
          <InputBox title="把视频、音频或图片拖到这里" hint="或点击选择 · 视频、音频、图片都行" disabled={busy} files={items.map((x) => ({ key: x.path, chip: KIND[x.kind][0], color: KIND[x.kind][1], name: x.name, meta: x.meta || x.info, state: x.state === 'idle' ? undefined : chipOf(x.state, x.progress), progress: x.state === 'run' ? x.progress : null }))}
            onPick={async () => { const f = await api.pick_files('media'); if (f?.length) add(f) }} onClear={() => { setItems([]); setStatus('') }} onRemove={(i) => setItems((a) => a.filter((_, k) => k !== i))} />
          <FlowArrow busy={busy} canStart={items.length > 0} onStart={start} text={arrowText} percent={percent} />
          <OutputBox files={outs} disabled={busy} onClear={() => setResults([])} hint="转换好的文件会出现在这里，可以直接拖出去保存" />
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
            : <Button variant="contained" size="large" disabled={!items.length} startIcon={<PlayArrowRounded />} sx={rounded} onClick={start}>开始转换</Button>}
        </EnhancedCard>
      </Box>
    </BasePage>
  )
}
