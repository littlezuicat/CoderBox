import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles/index.scss'

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)

// 前端报错也交给后端写日志（源码版：toolbox\logs\debug.log）
import { api } from './bridge'
const sendLog = (level: string, msg: string) => { try { api.log_js(level, msg) } catch { /* */ } }
window.addEventListener('error', (e) => sendLog('error', `${e.message} @ ${e.filename}:${e.lineno}`))
window.addEventListener('unhandledrejection', (e) => sendLog('error', `未处理的 Promise 错误：${(e.reason && (e.reason.stack || e.reason.message)) || e.reason}`))
const ce = console.error
console.error = (...a: any[]) => { sendLog('error', a.map((x) => (x instanceof Error ? x.stack : typeof x === 'string' ? x : JSON.stringify(x))).join(' ')); ce(...a) }
