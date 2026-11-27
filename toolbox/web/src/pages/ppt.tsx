import PlayArrowRounded from '@mui/icons-material/PlayArrowRounded'
import SettingsOutlined from '@mui/icons-material/SettingsOutlined'
import StopRounded from '@mui/icons-material/StopRounded'
import { Box, Button, Chip, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'
import { BasePage } from '../components/base-page'
import { Switch } from '../components/base-switch'
import { InfoTip, pageGrid, rounded, Row, Segment, StateChip } from '../components/common'
import { EnhancedCard } from '../components/enhanced-card'
import { FlowArrow, InputBox, OutFile, OutputBox } from '../components/flow'
import { human, useEvent, useSetting } from '../hooks'

const RES = ['1080P', '2K', '4K', '6K']
const WIDTH = [1920, 2560, 3840, 5760]

// 输入队列：转完一个就从队列里清掉一个（成功的移到下面的输出区）；失败/取消的留在队列里，可以再转
type Q = { path: string; name: string; size: number; state: 'idle' | 'wait' | 'run' | 'err' | 'cancel'; progress: number | null; info: string; meta: string }
type R = { key: string; path: string; name: string; meta: string }

const chipOf = (s: Q['state'], p: number | null): StateChip =>
  s === 'run' ? { label: p != null ? `转换中 ${Math.round(p)}%` : '转换中', color: 'primary' } : s === 'err' ? { label: '失败', color: 'error' } : s === 'cancel' ? { label: '已取消', color: 'default' } : { label: '等待', color: 'default' }
const base = (p: string) => p.split(/[\\/]/).pop() || p

export default function PptPage() {
  const [items, setItems] = useState<Q[]>([])
  const [results, setResults] = useState<R[]>([])
  const [busy, setBusy] = useState(false)
  const [batch, setBatch] = useState({ n: 0, done: 0 })
  const [engine, setEngine] = useState<string | null | undefined>(undefined)
  const [status, setStatus] = useState('')
  const [res, setRes] = useSetting('ppt_res4k', 2)
  const [notes, setNotes] = useSetting('ppt_notes', true)
  const batchRef = useRef<string[]>([])         // 这一批的文件路径（后端按序号回报，队列会变，所以按路径找）
  const okRef = useRef(0)
  const lastOut = useRef<string | null>(null)

  useEffect(() => { api.ppt_detect().then((e: any) => setEngine(e)) }, [])

  const patch = (path: string, p: Partial<Q>) => setItems((a) => a.map((it) => (it.path === path ? { ...it, ...p } : it)))
  const add = async (paths: string[]) => {
    if (busy) return setStatus('正在转换，等这一批完了再加。')
    const info = await api.file_info(paths, 'ppt')
    if (!info.length) return setStatus('没有可以转换的演示文稿。')
    setStatus('')
    setItems((a) => {
      const have = new Set(a.map((x) => x.path.toLowerCase()))
      return [...a, ...info.filter((f: any) => !have.has(f.path.toLowerCase())).map((f: any): Q => ({ path: f.path, name: f.name, size: f.size, state: 'idle', progress: null, info: human(f.size), meta: '' }))]
    })
  }
  useEvent('files:ppt', (paths: string[]) => add(paths))
  useEvent('ppt:engine', (n: string) => n && setEngine(n))
  useEvent('ppt:file', (d: any) => {
    const path = batchRef.current[d.idx]; if (!path) return
    if (d.state === 'run') patch(path, { state: 'run', progress: 0, meta: '正在转换…' })
    else if (d.state === 'done') {
      okRef.current += 1; lastOut.current = d.output
      setItems((a) => a.filter((x) => x.path !== path))          // 转完一个，清掉一个
      setResults((r) => [...r, { key: d.output, path: d.output, name: base(d.output), meta: `${d.pages} 页 · ${d.w}×${d.h}${d.warning ? ' · ' + d.warning : ''}` }])
      setBatch((b) => ({ ...b, done: b.done + 1 }))
    } else if (d.state === 'err') { patch(path, { state: 'err', progress: null, meta: d.error }); setBatch((b) => ({ ...b, done: b.done + 1 })) }
    else { patch(path, { state: 'cancel', progress: null, meta: '已取消' }); setBatch((b) => ({ ...b, done: b.done + 1 })) }
  })
  useEvent('ppt:progress', (d: any) => { const path = batchRef.current[d.idx]; if (path) patch(path, { progress: (d.i * 100) / Math.max(1, d.n), meta: `正在导出第 ${d.i} / ${d.n} 页` }) })
  useEvent('ppt:done', () => {
    setBusy(false)
    setItems((a) => a.map((x) => (x.state === 'wait' ? { ...x, state: 'idle', meta: '' } : x)))        // 被停止后没轮到的，回到待转状态
    setStatus(`转换结束：成功 ${okRef.current} 个，共 ${batchRef.current.length} 个。`)
    if (lastOut.current) api.reveal(lastOut.current)       // 转完自动打开文件所在位置
  })

  const start = async () => {
    if (busy || !items.length) return          // 队列是空的就不能转
    batchRef.current = items.map((x) => x.path); okRef.current = 0; lastOut.current = null
    setBatch({ n: items.length, done: 0 })
    setItems((a) => a.map((x) => ({ ...x, state: 'wait', progress: null, meta: '' })))
    setBusy(true); setStatus('')
    await api.ppt_start(batchRef.current, { width: WIDTH[res], jpeg: false, notes, skipHidden: true })
  }

  // 下面的输出区只放转成功的，最新的在最上面（可以拖出去）；转换进度、失败原因都显示在上面的队列里
  const outs: OutFile[] = [...results].reverse().map((r): OutFile => ({ key: r.key, chip: 'PPT', color: 'warning', name: r.name, meta: r.meta, state: { label: '完成', color: 'success' }, path: r.path }))
  const cur = items.find((x) => x.state === 'run')
  const percent = busy && batch.n ? ((batch.done + (cur ? (cur.progress || 0) / 100 : 0)) * 100) / batch.n : null
  const arrowText = busy ? (cur ? `正在转换 ${Math.min(batch.done + 1, batch.n)} / ${batch.n}：${cur.name}` : '准备中…') : status

  return (
    <BasePage contentStyle={{ height: '100%' }} title="PPT定图" info="每页渲染成高清图片再装回 PPT，不缺字体、不错位，备注保留。文件不上传。转完一个，上面就清掉一个，转好的文件在下面，按住可以拖出去保存。" header={engine === undefined ? null : <Chip color={engine ? 'success' : 'warning'} variant="outlined" label={engine ? `已检测到 ${engine}` : '没有检测到 PowerPoint 或 WPS'} sx={{ fontWeight: 700 }} />}>
      <Box sx={{ ...pageGrid, height: '100%', gridTemplateRows: 'minmax(0, 1fr)', alignItems: 'stretch' }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0 }}>
          <InputBox title="把 PPT 拖到这里" hint="或点击选择 · .pptx .ppt .ppsx" disabled={busy} files={items.map((x) => ({ key: x.path, chip: 'PPT', color: 'warning', name: x.name, meta: x.meta || x.info, state: x.state === 'idle' ? undefined : chipOf(x.state, x.progress), progress: x.state === 'run' ? x.progress : null }))}
            onPick={async () => { const f = await api.pick_files('ppt'); if (f?.length) add(f) }} onClear={() => { setItems([]); setStatus('') }} onRemove={(i) => setItems((a) => a.filter((_, k) => k !== i))} />
          <FlowArrow busy={busy} canStart={items.length > 0} onStart={start} text={arrowText} percent={percent} />
          <OutputBox files={outs} disabled={busy} onClear={() => setResults([])} hint="转换好的 PPT 会出现在这里，可以直接拖出去保存" />
        </Box>
        <EnhancedCard title="输出设置" icon={<SettingsOutlined />}>
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.6 }}><Typography variant="caption" color="text.secondary">清晰度</Typography><InfoTip text="每页图片的宽度：越大越清晰，文件也越大。" /></Box>
          <Segment disabled={busy} value={res} options={RES} onChange={setRes} />
          <Box sx={{ mt: 1.5 }}>
            <Row label="保留演讲者备注"><Switch checked={notes} disabled={busy} onChange={(_, v) => setNotes(v)} /></Row>
          </Box>
          <Box sx={{ flex: 1, minHeight: 24 }} />
          {busy
            ? <Button variant="contained" color="error" size="large" startIcon={<StopRounded />} sx={rounded} onClick={() => { api.ppt_stop(); setStatus('正在停止（等当前这页导出完）…') }}>停止</Button>
            : <Button variant="contained" size="large" disabled={!items.length} startIcon={<PlayArrowRounded />} sx={rounded} onClick={start}>开始转换</Button>}
        </EnhancedCard>
      </Box>
    </BasePage>
  )
}
