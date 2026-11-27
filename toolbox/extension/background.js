// 码境密码 · 后台：和工具箱的原生通信主机（nmhost.py）对话。密码只在需要填充的那一刻取出，不存进扩展。
const HOST = 'cn.zuicat.majing_pw'
let port = null
let seq = 0
const waiting = new Map()

function friendly(err) {
  const e = String(err || '')
  if (/not found/i.test(e)) return '还没有安装连接组件：打开工具箱 →“密码”→“浏览器扩展”→ 安装。'
  if (/forbidden/i.test(e)) return '连接组件不认这个扩展（扩展 ID 不一致），请在工具箱里重新安装连接组件。'
  if (/exited|Native host/i.test(e)) return '连接组件已退出（工具箱的保险库可能打不开），请打开工具箱看看。'
  return '连不上工具箱：' + e
}

function ensurePort() {
  if (port) return port
  port = chrome.runtime.connectNative(HOST)
  port.onMessage.addListener((m) => {
    const w = waiting.get(m.id)
    if (w) { waiting.delete(m.id); clearTimeout(w.t); w.res(m) }
  })
  port.onDisconnect.addListener(() => {
    const err = chrome.runtime.lastError && chrome.runtime.lastError.message
    port = null
    for (const [, w] of waiting) { clearTimeout(w.t); w.res({ ok: false, error: friendly(err), disconnected: true }) }
    waiting.clear()
  })
  return port
}

function call(msg) {
  return new Promise((res) => {
    const id = ++seq
    const t = setTimeout(() => { waiting.delete(id); res({ ok: false, error: '工具箱没有响应' }) }, 10000)
    waiting.set(id, { res, t })
    try { ensurePort().postMessage({ ...msg, id }) } catch (e) { clearTimeout(t); waiting.delete(id); res({ ok: false, error: friendly(e) }) }
  })
}

const isHttp = (u) => /^https?:\/\//i.test(u || '')
const fromExtPage = (s) => !s.tab && s.id === chrome.runtime.id && (s.url || '').startsWith(chrome.runtime.getURL(''))

// ---- 登录提交后“要不要保存”的暂存（只放内存里的 session 存储，2 分钟过期）
async function setPending(tabId, v) { await chrome.storage.session.set({ ['p' + tabId]: v }) }
async function getPending(tabId) {
  const k = 'p' + tabId
  const o = await chrome.storage.session.get(k)
  const v = o[k]
  if (v && Date.now() - v.ts > 120000) { await chrome.storage.session.remove(k); return null }
  return v || null
}
const clearPending = (tabId) => chrome.storage.session.remove('p' + tabId)

async function handle(m, s) {
  const tabUrl = s.tab && s.tab.url
  switch (m.t) {
    // ---- 来自网页里的脚本（网址一律用浏览器告诉我们的标签页地址，不信任页面自己报的）
    case 'match': return isHttp(tabUrl) ? call({ op: 'match', url: tabUrl }) : { ok: true, items: [] }
    case 'fill': return call({ op: 'fill', item: m.id, url: tabUrl, force: false })
    case 'captured': {
      if (!isHttp(tabUrl) || !m.password) return { ok: true }
      const r = await call({ op: 'check', url: tabUrl, username: m.username || '', password: m.password })
      if (r.ok && (r.status === 'new' || r.status === 'update')) await setPending(s.tab.id, { ts: Date.now(), url: tabUrl, username: m.username || '', password: m.password, status: r.status })
      return { ok: true }
    }
    case 'pending': {
      const v = s.tab ? await getPending(s.tab.id) : null
      return { ok: true, pending: v ? { username: v.username, status: v.status, host: new URL(v.url).hostname } : null }
    }
    case 'savePending': {
      const v = await getPending(s.tab.id)
      if (!v) return { ok: false, error: '已过期，请重新登录一次。' }
      const r = await call({ op: 'save', url: v.url, username: v.username, password: v.password })
      await clearPending(s.tab.id)
      return r
    }
    case 'dismiss': await clearPending(s.tab.id); return { ok: true }
    // ---- 来自扩展自己的弹窗（用户明确的操作；只有这里才允许 force）
    case 'p-ping': return fromExtPage(s) ? call({ op: 'ping' }) : { ok: false }
    case 'p-match': return fromExtPage(s) ? call({ op: 'match', url: m.url }) : { ok: false }
    case 'p-search': return fromExtPage(s) ? call({ op: 'search', q: m.q }) : { ok: false }
    case 'p-fill': {
      if (!fromExtPage(s)) return { ok: false }
      const r = await call({ op: 'fill', item: m.id, url: m.url, force: !!m.force })
      if (!r.ok) return r
      try { await chrome.tabs.sendMessage(m.tabId, { t: 'doFill', username: r.username, password: r.password }) } catch (e) { return { ok: false, error: '这个页面还没准备好，刷新后再试。' } }
      return { ok: true }
    }
  }
  return { ok: false, error: '未知请求' }
}

chrome.runtime.onMessage.addListener((m, s, send) => { handle(m, s).then(send, (e) => send({ ok: false, error: String(e) })); return true })

// 快捷键 Ctrl+Shift+L：只有一个匹配就直接填，多个就在页面里弹出选择
chrome.commands.onCommand.addListener((cmd, tab) => { if (cmd === 'fill') fillShortcut(tab) })
async function fillShortcut(tab) {
  if (!tab || !isHttp(tab.url)) return
  const r = await call({ op: 'match', url: tab.url })
  if (!r.ok || !r.items.length) { chrome.tabs.sendMessage(tab.id, { t: 'toast', text: r.ok ? '没有匹配这个网站的密码' : r.error }).catch(() => {}); return }
  if (r.items.length === 1) {
    const f = await call({ op: 'fill', item: r.items[0].id, url: tab.url, force: false })
    chrome.tabs.sendMessage(tab.id, f.ok ? { t: 'doFill', username: f.username, password: f.password } : { t: 'toast', text: f.error }).catch(() => {})
  } else chrome.tabs.sendMessage(tab.id, { t: 'showMenu' }).catch(() => {})
}
