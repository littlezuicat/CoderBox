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

// 扩展名 → VS Code 语言 id（只列 Seti 里有图标的语言；VS Code 本身是由各语言扩展声明的，这里手工抄常见的）
const LANG_EXT: Record<string, string> = {
  py: 'python', pyw: 'python', pyi: 'python', pyx: 'python',
  js: 'javascript', mjs: 'javascript', cjs: 'javascript', jsx: 'javascriptreact', ts: 'typescript', mts: 'typescript', cts: 'typescript', tsx: 'typescriptreact',
  json: 'json', jsonc: 'jsonc', jsonl: 'jsonl', ndjson: 'jsonl', webmanifest: 'json', geojson: 'json',
  md: 'markdown', markdown: 'markdown', mdown: 'markdown',
  sh: 'shellscript', bash: 'shellscript', zsh: 'shellscript', ksh: 'shellscript', fish: 'shellscript', bashrc: 'shellscript', zshrc: 'shellscript', profile: 'shellscript', bash_profile: 'shellscript', bash_logout: 'shellscript', zprofile: 'shellscript', zlogin: 'shellscript',
  yaml: 'yaml', yml: 'yaml',
  xml: 'xml', xsd: 'xml', xsl: 'xml', xslt: 'xml', plist: 'xml', csproj: 'xml', props: 'xml', targets: 'xml',
  html: 'html', htm: 'html', xhtml: 'html', css: 'css', scss: 'scss', less: 'less',
  c: 'c', cpp: 'cpp', cc: 'cpp', cxx: 'cpp', 'c++': 'cpp', hxx: 'cpp', cu: 'cuda-cpp', cs: 'csharp', m: 'objective-c', mm: 'objective-cpp',
  go: 'go', rs: 'rust', java: 'java', rb: 'ruby', php: 'php', lua: 'lua', pl: 'perl', pm: 'perl', r: 'r', jl: 'julia', swift: 'swift', dart: 'dart', groovy: 'groovy', clj: 'clojure', fs: 'fsharp', fsx: 'fsharp',
  sql: 'sql', bat: 'bat', cmd: 'bat', ps1: 'powershell', psm1: 'powershell', tex: 'latex', env: 'dotenv', ini: 'properties', cfg: 'properties', conf: 'properties', properties: 'properties',
  gitignore: 'ignore', dockerignore: 'ignore', mk: 'makefile', mak: 'makefile', hbs: 'handlebars', pug: 'jade', coffee: 'coffeescript',
}
const LANG_NAME: Record<string, string> = {
  dockerfile: 'dockerfile', makefile: 'makefile', gnumakefile: 'makefile', '.bashrc': 'shellscript', '.zshrc': 'shellscript', '.profile': 'shellscript', '.bash_profile': 'shellscript',
  '.gitignore': 'ignore', '.dockerignore': 'ignore', '.env': 'dotenv', 'docker-compose.yml': 'dockercompose', 'docker-compose.yaml': 'dockercompose', 'compose.yaml': 'dockercompose', 'compose.yml': 'dockercompose',
}

// Seti 里只有 zip 等少数几种压缩格式有图标；tgz、tar.gz、7z 这些常见的也统一用压缩包图标
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
  if (!id && ARCHIVE_EXT.has(n.slice(n.lastIndexOf('.') + 1)) && n.includes('.')) id = look(T.fileExtensions, T.light.fileExtensions, 'zip')
  if (!id) {
    let lang = LANG_NAME[n]
    if (!lang) { const i = n.lastIndexOf('.'); if (i >= 0) lang = LANG_EXT[n.slice(i + 1)] }
    if (lang) id = look(T.languageIds, T.light.languageIds, lang)
  }
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
