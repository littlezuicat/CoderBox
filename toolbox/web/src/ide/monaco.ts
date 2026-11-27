// Monaco 编辑器（只用编辑器本体 + 常见语言的语法高亮；没有 VS Code 工作台那一整套）。第一次用到编辑器时才加载（见 ide-pane 里的 lazy）。
import 'monaco-editor/esm/vs/editor/editor.all'
import 'monaco-editor/esm/vs/basic-languages/monaco.contribution'
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'

;(self as any).MonacoEnvironment = { getWorker: () => new EditorWorker() }

export { monaco }

// 文件名 → Monaco 语言 id：先按整个文件名（Dockerfile、Makefile），再按扩展名
let byExt: Map<string, string> | null = null
let byName: Map<string, string> | null = null
const EXTRA: Record<string, string> = { '.sh': 'shell', '.bash': 'shell', '.zsh': 'shell', '.yml': 'yaml', '.yaml': 'yaml', '.toml': 'ini', '.conf': 'ini', '.cfg': 'ini', '.log': 'plaintext', '.txt': 'plaintext', '.jsonl': 'json', '.ipynb': 'json', '.cu': 'cpp', '.cuh': 'cpp', '.h': 'cpp', '.hpp': 'cpp' }
function build() {
  byExt = new Map(); byName = new Map()
  for (const l of monaco.languages.getLanguages()) {
    for (const e of l.extensions || []) if (!byExt.has(e)) byExt.set(e.toLowerCase(), l.id)
    for (const n of l.filenames || []) byName.set(n.toLowerCase(), l.id)
  }
  for (const [k, v] of Object.entries(EXTRA)) byExt.set(k, v)
}
export function langOf(path: string): string {
  if (!byExt) build()
  const name = (path.split('/').pop() || path).toLowerCase()
  const hit = byName!.get(name)
  if (hit) return hit
  const i = name.lastIndexOf('.')
  return (i >= 0 && byExt!.get(name.slice(i))) || 'plaintext'
}
