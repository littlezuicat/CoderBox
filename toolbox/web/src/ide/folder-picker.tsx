// 打开文件夹：像 VS Code 的“打开文件夹”快速选择——顶上一个路径输入框，下面列出能接着往下选的子文件夹，
// 边输边过滤；↑↓ 选、Tab 补全进去、Enter（或“确定”）打开。
import FolderRounded from '@mui/icons-material/FolderRounded'
import { alpha, Box, Button, Dialog, InputBase, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'
import { rounded } from '../components/common'

const parentDir = (v: string) => { const i = v.lastIndexOf('/'); return i <= 0 ? '/' : v.slice(0, i + 1) }

export default function FolderPicker({ alias, open, initial, onClose, onPick }: { alias: string; open: boolean; initial: string; onClose: () => void; onPick: (path: string) => void }) {
  const [text, setText] = useState('')
  const [cur, setCur] = useState(0)
  const [err, setErr] = useState('')
  const [lists, setLists] = useState<Record<string, string[] | null>>({})          // 已读过的目录 → 里面的子文件夹名；null = 读不了
  const reading = useRef<Set<string>>(new Set())
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => { if (open) { setText(initial ? (initial.endsWith('/') ? initial : initial + '/') : '/'); setCur(0); setErr(''); setLists({}) } }, [open])

  const dir = parentDir(text)
  useEffect(() => {
    if (!open || dir in lists || reading.current.has(dir)) return
    reading.current.add(dir)
    api.ssh_ls(alias, dir).then((r: any) => {
      reading.current.delete(dir)
      setLists((l) => ({ ...l, [dir]: r?.ok ? (r.entries as any[]).filter((e) => e.dir).map((e) => e.name as string) : null }))
    })
  }, [open, dir, lists])

  const tail = text.slice(dir.length)
  const all = lists[dir]
  const shown = (all || []).filter((n) => n.toLowerCase().startsWith(tail.toLowerCase()) && (tail.startsWith('.') || !n.startsWith('.') || tail === '' ))
  useEffect(() => setCur(0), [dir, tail])

  const complete = (name: string) => { setText(dir + name + '/'); setErr(''); input.current?.focus() }
  const confirm = async (p?: string) => {
    const path = (p ?? text).trim() || '/'
    const r = await api.ssh_ls(alias, path)
    if (!r?.ok) return setErr(r?.error || '打不开这个文件夹')
    onPick(r.path)
  }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setCur((c) => Math.min(c + 1, shown.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setCur((c) => Math.max(c - 1, 0)) }
    else if (e.key === 'Tab') { e.preventDefault(); if (shown[cur]) complete(shown[cur]) }
    else if (e.key === 'Enter') { e.preventDefault(); confirm() }
  }
  useEffect(() => { document.querySelector('[data-fp-cur="1"]')?.scrollIntoView({ block: 'nearest' }) }, [cur, shown.length])

  return (
    // 背后不压灰，改成磨砂玻璃（invisible 遮罩 = 不触发顶栏原生按钮的压暗，页面本身也没变暗）
    <Dialog open={open} onClose={onClose} slotProps={{
      paper: { sx: { position: 'absolute', top: 36, m: 0, width: 'min(620px, 92vw)', borderRadius: 2, overflow: 'hidden' } },
      backdrop: { invisible: true, sx: { backdropFilter: 'blur(12px) saturate(1.1)', WebkitBackdropFilter: 'blur(12px) saturate(1.1)', bgcolor: (th: any) => alpha(th.palette.background.default, 0.18) } } }}
      sx={{ '& .MuiDialog-container': { alignItems: 'flex-start', justifyContent: 'center' } }}>
      <Typography sx={{ textAlign: 'center', fontSize: 13, color: 'text.secondary', pt: 1, pb: 0.8 }}>打开文件夹（{alias}）</Typography>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.2, pb: 1 }}>
        <InputBase autoFocus inputRef={input} value={text} onChange={(e) => { setText(e.target.value); setErr('') }} onKeyDown={onKey} spellCheck={false}
          sx={{ flex: 1, px: 1, height: 32, fontSize: 14, borderRadius: 1, border: 1, borderColor: err ? 'error.main' : 'primary.main', fontFamily: 'Consolas, "Cascadia Mono", monospace' }} />
        <Button variant="contained" size="small" onClick={() => confirm()} sx={{ ...rounded, height: 32, minWidth: 56 }}>确定</Button>
      </Box>
      {err && <Typography sx={{ px: 2, pb: 0.8, fontSize: 12, color: 'error.main' }}>{err}</Typography>}
      <Box sx={{ maxHeight: 340, overflow: 'auto', pb: 0.5 }}>
        {all === undefined && <Typography sx={{ px: 2, py: 1, fontSize: 12.5, color: 'text.secondary' }}>正在读取…</Typography>}
        {all === null && <Typography sx={{ px: 2, py: 1, fontSize: 12.5, color: 'text.secondary' }}>读不了这个目录，可以直接输完整路径再点确定。</Typography>}
        {shown.map((n, i) => (
          <Box key={n} data-fp-cur={i === cur ? '1' : '0'} onMouseMove={() => setCur(i)} onClick={() => complete(n)}
            sx={{ display: 'flex', alignItems: 'center', gap: 0.9, px: 2, height: 28, fontSize: 13.5, cursor: 'pointer', bgcolor: (th) => (i === cur ? alpha(th.palette.primary.main, 0.22) : 'transparent') }}>
            <FolderRounded sx={{ fontSize: 17, color: 'primary.main' }} />{n}
          </Box>
        ))}
        {all && shown.length === 0 && <Typography sx={{ px: 2, py: 1, fontSize: 12.5, color: 'text.secondary' }}>这里没有以“{tail}”开头的子文件夹。</Typography>}
      </Box>
    </Dialog>
  )
}
