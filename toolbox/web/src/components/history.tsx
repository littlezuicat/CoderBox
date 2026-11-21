// 转换历史：长期保存（后端写在 %APPDATA%\MajingToolbox\history.json），PPT定图和格式转换各用一份。
import DeleteOutline from '@mui/icons-material/DeleteOutline'
import HistoryRounded from '@mui/icons-material/HistoryRounded'
import { Box, Button, Chip, IconButton, Tooltip, Typography } from '@mui/material'
import { useCallback, useEffect, useState } from 'react'

import { api } from '../bridge'
import { human, useEvent } from '../hooks'
import { EnhancedCard } from './enhanced-card'

type Entry = { id: string; name: string; output: string; ok: boolean; detail: string; size: number; time: number; exists: boolean }
const PAGE = 30

const fmtTime = (t: number) => {
  const d = new Date(t * 1000), p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function HistoryCard({ kind, chip, color }: { kind: 'ppt' | 'convert'; chip: string; color: 'warning' | 'primary' | 'success' | 'info' }) {
  const [list, setList] = useState<Entry[]>([])
  const [shown, setShown] = useState(PAGE)
  const [confirm, setConfirm] = useState(false)
  const load = useCallback(() => { api.history_list(kind).then((l: Entry[]) => setList(l || [])) }, [kind])
  useEffect(load, [load])
  useEvent('history:changed', (d: any) => { if (!d?.kind || d.kind === kind) load() })
  useEffect(() => { if (!confirm) return; const t = setTimeout(() => setConfirm(false), 3000); return () => clearTimeout(t) }, [confirm])

  return (
    <EnhancedCard title="转换历史" icon={<HistoryRounded />} minHeight={100}
      action={list.length ? (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="body2" color="text.secondary">{list.length} 条</Typography>
          <Button size="small" color={confirm ? 'error' : 'inherit'} variant={confirm ? 'contained' : 'text'} disableElevation sx={{ minWidth: 0, fontWeight: 600 }}
            onClick={() => { if (confirm) { setConfirm(false); api.history_clear(kind) } else setConfirm(true) }}>{confirm ? '再点一次确认清空' : '清空'}</Button>
        </Box>
      ) : null}>
      {list.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 2 }}>转换完成的文件会记在这里，长期保存</Typography>}
      {list.slice(0, shown).map((e) => (
        <Box key={e.id} onClick={() => e.exists && api.reveal(e.output)}
          sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 1, borderBottom: 1, borderColor: 'divider', cursor: e.exists ? 'pointer' : 'default', '&:last-of-type': { borderBottom: 0 } }}>
          <Box sx={{ width: 34, height: 34, borderRadius: 1.5, bgcolor: (t) => `${(t.palette as any)[e.ok ? color : 'error'].main}24`, color: `${e.ok ? color : 'error'}.main`, fontWeight: 800, fontSize: 11, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>{chip}</Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography sx={{ fontWeight: 600, fontSize: 14 }} noWrap title={e.name}>{e.name}</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', userSelect: 'text' }} noWrap title={e.output || e.detail}>
              {fmtTime(e.time)} · {e.detail}{e.ok && e.size ? ` · ${human(e.size)}` : ''}{e.ok ? (e.exists ? ' · 点击定位文件' : ' · 文件已不在') : ''}
            </Typography>
          </Box>
          <Chip size="small" label={e.ok ? '完成' : '失败'} color={e.ok ? 'success' : 'error'} sx={{ fontWeight: 700, borderRadius: 1.5 }} />
          <Tooltip title="删除这条记录（不删文件）"><IconButton size="small" onClick={(ev) => { ev.stopPropagation(); api.history_remove(e.id, kind) }}><DeleteOutline fontSize="small" /></IconButton></Tooltip>
        </Box>
      ))}
      {list.length > shown && <Button size="small" sx={{ mt: 1, alignSelf: 'center' }} onClick={() => setShown((n) => n + PAGE)}>显示更多（还有 {list.length - shown} 条）</Button>}
    </EnhancedCard>
  )
}
