import DeleteOutline from '@mui/icons-material/DeleteOutline'
import FolderOpenOutlined from '@mui/icons-material/FolderOpenOutlined'
import FormatListBulletedRounded from '@mui/icons-material/FormatListBulletedRounded'
import PlayArrowRounded from '@mui/icons-material/PlayArrowRounded'
import SettingsOutlined from '@mui/icons-material/SettingsOutlined'
import StopRounded from '@mui/icons-material/StopRounded'
import { Box, Button, Chip, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'
import { BasePage } from '../components/base-page'
import { Switch } from '../components/base-switch'
import { DropZone, FileRow, InfoTip, pageGrid, rounded, Row, Segment, StateChip } from '../components/common'
import { EnhancedCard } from '../components/enhanced-card'
import { HistoryCard } from '../components/history'
import { human, useEvent, useSetting } from '../hooks'

const RES = ['1080P', '2K', '4K', '6K']
const WIDTH = [1920, 2560, 3840, 5760]

type Item = { path: string; name: string; size: number; state: 'wait' | 'run' | 'done' | 'err' | 'cancel'; progress: number | null; meta: string; output?: string }

const chipOf = (s: Item['state'], p: number | null): StateChip =>
  s === 'run' ? { label: p != null ? `转换中 ${Math.round(p)}%` : '转换中', color: 'primary' } : s === 'done' ? { label: '完成', color: 'success' } : s === 'err' ? { label: '失败', color: 'error' } : s === 'cancel' ? { label: '已取消', color: 'default' } : { label: '等待', color: 'default' }

export default function PptPage() {
  const [items, setItems] = useState<Item[]>([])
  const [busy, setBusy] = useState(false)
  const [engine, setEngine] = useState<string | null | undefined>(undefined)
  const [status, setStatus] = useState('')
  const [res, setRes] = useSetting('ppt_res4k', 2)
  const [fmt, setFmt] = useSetting('ppt_fmt', 0)
  const [notes, setNotes] = useSetting('ppt_notes', true)
  const [hidden, setHidden] = useSetting('ppt_hidden', true)
  const last = useRef<string | null>(null)
  const itemsRef = useRef(items); itemsRef.current = items

  useEffect(() => { api.ppt_detect().then((e: any) => setEngine(e)) }, [])

  const patch = (idx: number, p: Partial<Item>) => setItems((a) => a.map((it, i) => (i === idx ? { ...it, ...p } : it)))
  const add = async (paths: string[]) => {
    if (busy) return setStatus('正在转换，等这一批完了再加。')
    const info = await api.file_info(paths, 'ppt')
    if (!info.length) return setStatus('没有可以转换的演示文稿。')
    setItems((a) => {
      const have = new Set(a.map((x) => x.path.toLowerCase()))
      return [...a, ...info.filter((f: any) => !have.has(f.path.toLowerCase())).map((f: any): Item => ({ path: f.path, name: f.name, size: f.size, state: 'wait', progress: null, meta: human(f.size) }))]
    })
  }
  useEvent('files:ppt', (paths: string[]) => add(paths))
  useEvent('ppt:engine', (n: string) => n && setEngine(n))
  useEvent('ppt:file', (d: any) => {
    if (d.state === 'run') patch(d.idx, { state: 'run', progress: 0, meta: '正在转换…' })
    else if (d.state === 'done') { last.current = d.output; patch(d.idx, { state: 'done', progress: null, output: d.output, meta: `${d.pages} 页 · ${d.w}×${d.h}${d.warning ? ' · ' + d.warning : ''} · 点击定位文件` }) }
    else if (d.state === 'err') patch(d.idx, { state: 'err', progress: null, meta: d.error })
    else patch(d.idx, { state: 'cancel', progress: null, meta: '已取消' })
  })
  useEvent('ppt:progress', (d: any) => patch(d.idx, { progress: (d.i * 100) / Math.max(1, d.n), meta: `正在导出第 ${d.i} / ${d.n} 页` }))
  useEvent('ppt:done', () => {
    setBusy(false)
    const list = itemsRef.current
    setStatus(`转换结束：成功 ${list.filter((x) => x.state === 'done').length} 个，共 ${list.length} 个。`)
    const o = [...list].reverse().find((x) => x.output)?.output
    if (o) api.reveal(o)       // 转完自动打开文件所在位置
  })

  const start = async () => {
    if (!items.length) return setStatus('先把 PPT 拖进来。')
    setItems((a) => a.map((x) => ({ ...x, state: 'wait', progress: null, meta: human(x.size), output: undefined })))
    setBusy(true); setStatus('正在转换…')
    await api.ppt_start(items.map((x) => x.path), { width: WIDTH[res], jpeg: fmt === 1, notes, skipHidden: hidden })
  }

  return (
    <BasePage title="PPT定图" info="每页渲染成高清图片再装回 PPT，不缺字体、不错位，备注保留。文件不上传，保存在原文件旁。" header={engine === undefined ? null : <Chip color={engine ? 'success' : 'warning'} variant="outlined" label={engine ? `已检测到 ${engine}` : '没有检测到 PowerPoint 或 WPS'} sx={{ fontWeight: 700 }} />}>
      <Box sx={pageGrid}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, minWidth: 0 }}>
          <DropZone disabled={busy} title="把 PPT 拖到这里" hint="或点击选择 · .pptx .ppt .ppsx" onPick={async () => { const f = await api.pick_files('ppt'); if (f?.length) add(f) }} />
          <EnhancedCard title="转换队列" icon={<FormatListBulletedRounded />} action={items.length ? <Typography variant="body2" color="text.secondary">{items.length} 个文件</Typography> : null} minHeight={140}>
            {items.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 2.5 }}>暂无文件</Typography>}
            {items.map((it, i) => (
              <FileRow key={it.path} chip="PPT" color="warning" name={it.name} meta={it.meta} progress={it.progress} state={chipOf(it.state, it.progress)}
                onRemove={busy ? undefined : () => setItems((a) => a.filter((_, k) => k !== i))} onOpen={() => it.output && api.reveal(it.output)} />
            ))}
            {status && <Typography variant="caption" color="text.secondary" sx={{ mt: 1, userSelect: 'text' }}>{status}</Typography>}
          </EnhancedCard>
          <HistoryCard kind="ppt" chip="PPT" color="warning" />
        </Box>
        <EnhancedCard title="输出设置" icon={<SettingsOutlined />}>
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.6 }}><Typography variant="caption" color="text.secondary">清晰度</Typography><InfoTip text="每页图片的宽度：越大越清晰，文件也越大。" /></Box>
          <Segment disabled={busy} value={res} options={RES} onChange={setRes} />
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5, mb: 0.6 }}>图片格式</Typography>
          <Segment disabled={busy} value={fmt} options={['PNG', 'JPG']} onChange={setFmt} />
          <Box sx={{ mt: 1.5 }}>
            <Row label="保留演讲者备注"><Switch checked={notes} disabled={busy} onChange={(_, v) => setNotes(v)} /></Row>
            <Row label="跳过隐藏页"><Switch checked={hidden} disabled={busy} onChange={(_, v) => setHidden(v)} /></Row>
          </Box>
          <Box sx={{ flex: 1, minHeight: 24 }} />
          {busy
            ? <Button variant="contained" color="error" size="large" startIcon={<StopRounded />} sx={rounded} onClick={() => { api.ppt_stop(); setStatus('正在停止（等当前这页导出完）…') }}>停止</Button>
            : <Button variant="contained" size="large" startIcon={<PlayArrowRounded />} sx={rounded} onClick={start}>开始转换</Button>}
          <Button variant="outlined" disabled={busy} startIcon={<DeleteOutline />} sx={{ ...rounded, mt: 1 }} onClick={() => setItems([])}>清空列表</Button>
          <Button variant="outlined" disabled={!last.current && !items.some((x) => x.output)} startIcon={<FolderOpenOutlined />} sx={{ ...rounded, mt: 1 }} onClick={() => { const o = last.current || items.find((x) => x.output)?.output; o && api.reveal(o) }}>打开输出位置</Button>
        </EnhancedCard>
      </Box>
    </BasePage>
  )
}
