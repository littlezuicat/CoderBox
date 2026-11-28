// 编辑器：标签页 + Monaco。点开远程文件（经 SFTP 读），Ctrl+S 存回服务器；没保存的标签上有圆点。
import CloseRounded from '@mui/icons-material/CloseRounded'
import CodeRounded from '@mui/icons-material/CodeRounded'
import VisibilityRounded from '@mui/icons-material/VisibilityRounded'
import { Box, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

import { api } from '../bridge'
import { StatStrip, type SysInfo } from '../components/sysinfo-bar'
import FileIcon from './file-icon'
import { langOf, monaco } from './monaco'
import { freePreview, isMarkdown, type Loaded, loadPreview, MdView, PreviewView, type PKind, previewKind } from './preview'

// 文本文件有 Monaco 模型；图片/PDF/表格没有模型，只有 pv（读回来的字节做成的对象地址或工作簿）
type F = { model?: any; kind: 'text' | PKind; pv?: Loaded; enc: string; saved: number; view?: any; saving?: boolean; timer?: number }
// 深色主题：vs-dark 自带的底色是接近纯黑的 #1e1e1e，和界面的深灰蓝（面板色 #282A36）不搭，这里换成面板色
monaco.editor.defineTheme('majing-dark', {
  base: 'vs-dark', inherit: true, rules: [],
  colors: {
    'editor.background': '#282A36', 'editorGutter.background': '#282A36', 'editor.lineHighlightBackground': '#ffffff0c', 'editor.lineHighlightBorder': '#00000000',
    'editorLineNumber.foreground': '#6c7189', 'editorLineNumber.activeForeground': '#c3c7d9', 'editorIndentGuide.background1': '#ffffff14', 'editorIndentGuide.activeBackground1': '#ffffff33',
    'editor.selectionBackground': '#3d5a8a99', 'editor.inactiveSelectionBackground': '#3d5a8a55', 'editorWidget.background': '#2E303D', 'editorSuggestWidget.background': '#2E303D',
  },
})
const themeOf = (dark: boolean) => (dark ? 'majing-dark' : 'vs')
export type OpenReq = { path: string; n: number } | null

const base = (p: string) => p.split('/').pop() || p

export default function EditorPanel({ alias, req, visible, dark, info, onStatus }: { alias: string; req: OpenReq; visible: boolean; dark: boolean; info?: SysInfo | null; onStatus?: (s: string) => void }) {
  const box = useRef<HTMLDivElement>(null)
  const ed = useRef<any>(null)
  const files = useRef<Map<string, F>>(new Map())
  const curRef = useRef('')
  const mdSrcRef = useRef<Set<string>>(new Set())
  const [tabs, setTabs] = useState<{ path: string; dirty: boolean }[]>([])
  const [cur, setCur] = useState('')
  const [msg, setMsg] = useState('')
  const [pos, setPos] = useState('')
  const [meta, setMeta] = useState('')
  const [mdSrc, setMdSrc] = useState<Set<string>>(new Set())      // Markdown 默认看渲染结果；进了这个集合的文件显示源码
  curRef.current = cur
  mdSrcRef.current = mdSrc

  const syncTabs = () => setTabs((t) => t.map((x) => { const f = files.current.get(x.path); return { ...x, dirty: !!f?.model && f.model.getAlternativeVersionId() !== f.saved } }))
  const say = (s: string) => { setMsg(s); onStatus?.(s) }

  const show = (path: string) => {
    const e = ed.current; if (!e) return
    const old = files.current.get(curRef.current); if (old?.model) old.view = e.saveViewState()
    const f = files.current.get(path); if (!f) return
    if (f.model) { e.setModel(f.model); if (f.view) e.restoreViewState(f.view) } else e.setModel(null)
    setMeta(''); setCur(path)
    if (f.model && !(isMarkdown(path) && !mdSrcRef.current.has(path))) e.focus()
  }
  // 保存某个文件。改完停一会儿自动保存（SSH 主机上的文件不弹“没保存”确认），Ctrl+S 立刻保存
  const saveFile = async (path: string): Promise<boolean> => {
    const f = files.current.get(path)
    if (!f || !f.model) return true
    window.clearTimeout(f.timer)
    if (f.saving) return false
    const ver = f.model.getAlternativeVersionId()
    if (ver === f.saved) return true
    f.saving = true; say('正在保存…')
    let r: any
    try { r = await api.ssh_write_file(alias, path, f.model.getValue(), f.enc) } catch (e) { r = { ok: false, error: String(e) } }
    f.saving = false
    if (!r.ok) { say(r.error || '保存失败'); return false }
    f.saved = ver; syncTabs(); say(`已保存 ${base(path)}`)
    if (files.current.get(path) === f && f.model.getAlternativeVersionId() !== f.saved) { f.timer = window.setTimeout(() => saveFile(path), 600) }      // 保存的过程中又改了
    return true
  }
  const autoSave = (path: string) => { const f = files.current.get(path); if (!f) return; window.clearTimeout(f.timer); f.timer = window.setTimeout(() => saveFile(path), 1200) }
  const save = () => saveFile(curRef.current)
  const saveRef = useRef(save); saveRef.current = save

  const close = async (path: string) => {
    const f = files.current.get(path); if (!f) return
    if (f.model && f.model.getAlternativeVersionId() !== f.saved) {
      const ok = await saveFile(path)                 // 先自动保存；保存不了才问一句
      if (!ok && !window.confirm(`${base(path)} 保存失败，确定不保存直接关闭吗？`)) return
    }
    window.clearTimeout(f.timer)
    const order = tabs.map((t) => t.path), i = order.indexOf(path)
    files.current.delete(path); f.model?.dispose(); freePreview(f.pv)
    const rest = order.filter((p) => p !== path)
    setTabs((t) => t.filter((x) => x.path !== path))
    if (curRef.current === path) { if (rest.length) show(rest[Math.min(i, rest.length - 1)]); else { ed.current?.setModel(null); setCur('') } }
  }

  useEffect(() => {
    const e = monaco.editor.create(box.current!, {
      theme: themeOf(dark), automaticLayout: true, fontSize: 15, lineHeight: 24, fontFamily: 'Consolas, "Cascadia Mono", "Microsoft YaHei UI", monospace',
      minimap: { enabled: false }, scrollBeyondLastLine: false, renderWhitespace: 'selection', smoothScrolling: true, padding: { top: 6 },
    })
    ed.current = e
    // Ctrl+S：不能用 e.addCommand——standalone Monaco 里命令是所有编辑器共用的，开过几台主机就有几个编辑器，
    // 同一个快捷键会落到别的主机那个编辑器的保存函数上（它没打开文件，直接什么都不做，表现为“保存没反应”）。改成只挂在这个编辑器自己的按键事件上。
    e.onKeyDown((ev: any) => {
      if ((ev.ctrlKey || ev.metaKey) && !ev.shiftKey && !ev.altKey && ev.keyCode === monaco.KeyCode.KeyS) { ev.preventDefault(); ev.stopPropagation(); saveRef.current() }
    })
    e.onDidChangeCursorPosition((ev: any) => setPos(`行 ${ev.position.lineNumber}，列 ${ev.position.column}`))
    return () => { e.dispose(); files.current.forEach((f) => { f.model?.dispose(); freePreview(f.pv) }); files.current.clear() }
  }, [])
  useEffect(() => { monaco.editor.setTheme(themeOf(dark)) }, [dark])

  // 外面（文件树）要求打开某个文件
  useEffect(() => {
    if (!req) return
    const path = req.path
    if (files.current.has(path)) { show(path); return }
    say(`正在打开 ${base(path)}…`)
    const pk = previewKind(path)
    if (pk) {                                           // 图片 / PDF / 表格：按字节读回来预览
      loadPreview(alias, path, pk).then((r) => {
        if ('error' in r) return say(r.error)
        if (files.current.has(path)) { freePreview(r.pv); return show(path) }
        files.current.set(path, { kind: pk, pv: r.pv, enc: '', saved: 0 })
        setTabs((t) => [...t, { path, dirty: false }])
        show(path); say(base(path))
      })
      return
    }
    api.ssh_read_file(alias, path).then((r: any) => {
      if (!r.ok) return say(r.error || '打不开')
      if (files.current.has(path)) return show(path)
      const model = monaco.editor.createModel(r.text, langOf(path), monaco.Uri.parse(`remote://${alias}${path}`))
      const f: F = { model, kind: 'text', enc: r.encoding, saved: model.getAlternativeVersionId() }
      model.onDidChangeContent(() => { syncTabs(); autoSave(path) })
      files.current.set(path, f)
      setTabs((t) => [...t, { path, dirty: false }])
      show(path); say(`${base(path)} · ${r.encoding}`)
    })
  }, [req])

  useEffect(() => { if (visible) setTimeout(() => ed.current?.layout(), 30) }, [visible])
  const f = files.current.get(cur)
  const md = !!f?.model && isMarkdown(cur)
  const mdPreview = md && !mdSrc.has(cur)
  const textShown = !!f?.model && !mdPreview
  const toggleMd = () => { setMdSrc((s) => { const n = new Set(s); n.has(cur) ? n.delete(cur) : n.add(cur); return n }); setTimeout(() => { ed.current?.layout(); ed.current?.focus() }, 30) }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <Box sx={{ display: 'flex', flex: '0 0 34px', overflowX: 'auto', bgcolor: 'background.default', borderBottom: 1, borderColor: 'divider' }}>
        {tabs.map((t) => (
          <Box key={t.path} onClick={() => show(t.path)} onAuxClick={(e) => { if (e.button === 1) close(t.path) }} title={t.path}
            sx={{ display: 'flex', alignItems: 'center', gap: 0.6, pl: 1.4, pr: 0.6, cursor: 'pointer', whiteSpace: 'nowrap', fontSize: 13, borderRight: 1, borderColor: 'divider', flexShrink: 0,
              bgcolor: t.path === cur ? 'background.paper' : 'transparent', borderTop: 2, borderTopColor: t.path === cur ? 'primary.main' : 'transparent', color: t.path === cur ? 'text.primary' : 'text.secondary',
              '&:hover .x': { visibility: 'visible' } }}>
            <FileIcon name={base(t.path)} dark={dark} mr={0.4} />{base(t.path)}
            <Box className="x" onClick={(e) => { e.stopPropagation(); close(t.path) }}
              sx={{ width: 18, height: 18, borderRadius: 0.8, display: 'flex', alignItems: 'center', justifyContent: 'center', visibility: t.dirty ? 'visible' : 'hidden', '&:hover': { bgcolor: 'action.selected' } }}>
              {t.dirty ? <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'text.primary' }} /> : <CloseRounded sx={{ fontSize: 14 }} />}
            </Box>
          </Box>
        ))}
        <Box sx={{ flex: 1 }} />
        {md && (
          <Box onClick={toggleMd} title={mdPreview ? '看源码（可编辑）' : '看渲染后的效果'}
            sx={{ display: 'flex', alignItems: 'center', gap: 0.5, px: 1.2, cursor: 'pointer', fontSize: 12.5, color: 'text.secondary', flexShrink: 0, '&:hover': { color: 'text.primary', bgcolor: 'action.hover' } }}>
            {mdPreview ? <CodeRounded sx={{ fontSize: 16 }} /> : <VisibilityRounded sx={{ fontSize: 16 }} />}{mdPreview ? '源码' : '预览'}
          </Box>
        )}
      </Box>
      <Box sx={{ flex: 1, minHeight: 0, position: 'relative', bgcolor: (th) => (th.palette.mode === 'light' ? '#ffffff' : 'transparent') }}>
        <div ref={box} style={{ position: 'absolute', inset: 0, visibility: textShown ? 'visible' : 'hidden' }} />
        {mdPreview && <MdView text={f!.model.getValue()} dark={dark} />}
        {f && !f.model && f.pv && <PreviewView key={cur} kind={f.kind as PKind} pv={f.pv} dark={dark} onMeta={setMeta} />}
        {!cur && (
          <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', color: 'text.disabled', userSelect: 'none' }}>
            <Typography sx={{ fontSize: 15 }}>点左边的文件，在这里打开</Typography>
          </Box>
        )}
      </Box>
      <Box sx={{ flex: '0 0 22px', display: 'flex', alignItems: 'center', gap: 2, px: 1.2, fontSize: 11.5, color: 'text.secondary', borderTop: 1, borderColor: 'divider', whiteSpace: 'nowrap', overflow: 'hidden', '& > span': { flexShrink: 0 } }}>
        <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 1 }}>{msg}</span>
        {cur && f?.model && <><span>{pos}</span><span>{f.enc}</span><span>{langOf(cur)}</span></>}
        {cur && f && !f.model && <span>{meta}</span>}
        <StatStrip info={info ?? null} />
      </Box>
    </Box>
  )
}
