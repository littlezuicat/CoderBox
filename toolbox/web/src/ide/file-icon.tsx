// 文件图标：用 VS Code 自带的 Seti 图标主题（字体 + 它的映射表，原样取自 VS Code 的 theme-seti 扩展，MIT）。
// 查找顺序和 VS Code 一样：完整文件名 → 扩展名（a.b.c 先试 b.c 再试 c）→ 文件所属“语言”（py/js/json/md/sh 这些主流类型走这一级）→ 默认图标。
// 浅色主题：Seti 自己的浅色版颜色整体再压深一点，默认的浅灰图标在白底上几乎看不见，单独换成深一点的灰。
import { Box } from '@mui/material'

import theme from './seti/vs-seti-icon-theme.json'
import './seti/seti.css'

type Def = { fontCharacter: string; fontColor?: string }
type Map = Record<string, string>
const T = theme as unknown as {
  iconDefinitions: Record<string, Def>; file: string; fileExtensions: Map; fileNames: Map; languageIds: Map
  light: { file: string; fileExtensions: Map; fileNames: Map; languageIds: Map }
}

// 文件 → 语言 id：和 VS Code 一样，来自各扩展在 package.json 里声明的 contributes.languages（扩展名 / 文件名 / 文件名模式）。
// 表是 tools/gen_lang_map.py 从本机 VS Code 的内置扩展 + 已安装扩展里收集生成的（seti/lang-map.json），不再手抄。
import langMap from './seti/lang-map.json'

const LM = langMap as unknown as { ext: Record<string, string>; names: Record<string, string>; patterns: [string, string][] }
const PATTERNS = LM.patterns.map(([g, id]) => [new RegExp('^' + g.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.') + '$'), id] as [RegExp, string])

function languageOf(n: string): string | undefined {
  if (Object.prototype.hasOwnProperty.call(LM.names, n)) return LM.names[n]
  const parts = n.split('.')
  for (let i = 1; i < parts.length; i++) {            // a.b.c：先试 b.c 再试 c（最长的后缀优先）
    const k = parts.slice(i).join('.')
    if (Object.prototype.hasOwnProperty.call(LM.ext, k)) return LM.ext[k]
  }
  for (const [re, id] of PATTERNS) if (re.test(n)) return id
  return undefined
}

// Seti 里只有 zip 一种压缩格式有图标（VS Code 里 tgz、rar、7z 也是默认文件图标）；这里额外把常见压缩包统一用压缩包图标，是和 VS Code 唯一不同的地方
const ARCHIVE_EXT = new Set(['tgz', 'tar', 'gz', 'bz2', 'xz', 'zst', 'lz4', 'tbz', 'tbz2', 'txz', '7z', 'rar', 'z', 'lzma', 'cab', 'iso', 'whl', 'egg', 'jar', 'war', 'apk'])

function resolve(name: string, dark: boolean): { ch: string; color: string } {
  const n = name.toLowerCase()
  const has = (m: Map | undefined, k: string) => (m && Object.prototype.hasOwnProperty.call(m, k) ? m[k] : undefined)
  const look = (m: Map, lm: Map | undefined, k: string) => (!dark ? has(lm, k) : undefined) || has(m, k)
  let id = look(T.fileNames, T.light.fileNames, n)
  if (!id) {
    const parts = n.split('.')
    for (let i = 1; i < parts.length && !id; i++) id = look(T.fileExtensions, T.light.fileExtensions, parts.slice(i).join('.'))
  }
  if (!id) { const lang = languageOf(n); if (lang) id = look(T.languageIds, T.light.languageIds, lang) }
  if (!id && ARCHIVE_EXT.has(n.slice(n.lastIndexOf('.') + 1)) && n.includes('.')) id = look(T.fileExtensions, T.light.fileExtensions, 'zip')
  const isDefault = !id
  if (!id) id = (!dark && T.light.file) || T.file
  const d = T.iconDefinitions[id] || T.iconDefinitions[T.file]
  let color = d.fontColor || '#8a9190'
  if (!dark) color = isDefault ? '#8b9496' : darken(color, 0.86)
  return { ch: String.fromCharCode(parseInt(d.fontCharacter.replace('\\', ''), 16)), color }
}

function darken(hex: string, k: number) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex)
  if (!m) return hex
  const v = parseInt(m[1], 16)
  const c = (s: number) => Math.round(((v >> s) & 255) * k).toString(16).padStart(2, '0')
  return `#${c(16)}${c(8)}${c(0)}`
}

export default function FileIcon({ name, dark, mr = 0.5 }: { name: string; dark: boolean; mr?: number }) {
  const { ch, color } = resolve(name, dark)
  return (
    <Box component="span" aria-hidden sx={{ fontFamily: 'seti', fontSize: 19, lineHeight: 1, width: 22, height: 20, mr, flexShrink: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color, userSelect: 'none', overflow: 'hidden' }}>
      {ch}
    </Box>
  )
}
