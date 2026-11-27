import { Alert, Snackbar } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'
import { useEvent } from '../hooks'

// 同一个人的多条连接（一个客户端会同时开好几条）合并成一项：公网按码境用户名，其它按来源地址
export function groupSessions(list: any[]) {
  const m = new Map<string, { key: string; label: string; since: number; sids: any[] }>()
  for (const x of list || []) {
    const pub = x.ip === '127.0.0.1'
    const key = pub ? `w:${x.who || ''}` : `i:${x.ip}`
    const g = m.get(key)
    if (g) { g.sids.push(x.sid); g.since = Math.min(g.since, x.since) }
    else m.set(key, { key, label: pub ? (x.who ? `码境用户 ${x.who}` : '公网访客') : x.ip, since: x.since, sids: [x.sid] })
  }
  return [...m.values()]
}

// 有新的人连上共享的电脑就在右上角弹一条提示（挂在 App 最外层，不管当前在哪个页面都能看到）
export function ShareToast() {
  const known = useRef<Set<string> | null>(null)
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const seed = (d: any) => { known.current = new Set(groupSessions(d?.sessions || []).map((g) => g.key)) }
  useEffect(() => { api.share_info().then(seed).catch(() => { known.current = new Set() }) }, [])
  useEvent('share:state', (d: any) => {
    if (!d?.on) { known.current = new Set(); return }
    const groups = groupSessions(d.sessions || [])
    if (known.current) {
      const fresh = groups.filter((g) => !known.current!.has(g.key))
      if (fresh.length) { setText(`${fresh.map((g) => g.label).join('、')} 连上了你的电脑`); setOpen(true) }
    }
    known.current = new Set(groups.map((g) => g.key))
  })
  return (
    <Snackbar open={open} autoHideDuration={6000} onClose={(_, r) => { if (r !== 'clickaway') setOpen(false) }} anchorOrigin={{ vertical: 'top', horizontal: 'right' }} sx={{ top: '64px !important' }}>
      <Alert severity="info" variant="filled" onClose={() => setOpen(false)} sx={{ borderRadius: 2 }}>{text}</Alert>
    </Snackbar>
  )
}
