const $ = (id) => document.getElementById(id)
const send = (m) => new Promise((res) => chrome.runtime.sendMessage(m, (r) => res(r || { ok: false, error: '扩展没有响应' })))
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
let tab = null
let matchIds = new Set()

const row = (m, force) => `<div class="it" data-id="${esc(m.id)}" data-force="${force ? 1 : 0}"><b>${esc(m.name || m.url)}</b><small>${esc(m.username || '（无用户名）')}${m.url ? ' · ' + esc(m.url.replace(/^https?:\/\//, '')) : ''}</small></div>`
const msg = (t, err) => { $('list').innerHTML = `<div class="msg${err ? ' err' : ''}">${esc(t)}</div>` }

async function show() {
  const q = $('q').value.trim()
  if (q) {
    const r = await send({ t: 'p-search', q })
    $('list').innerHTML = r.ok ? (r.items.length ? `<div class="sec">搜索结果</div>` + r.items.map((m) => row(m, !matchIds.has(m.id))).join('') : '<div class="msg">没有找到</div>') : `<div class="msg err">${esc(r.error)}</div>`
    return
  }
  if (!/^https?:/i.test(tab && tab.url || '')) return msg('这个页面不能填充密码。')
  const r = await send({ t: 'p-match', url: tab.url })
  if (!r.ok) return msg(r.error || '连不上工具箱', true)
  matchIds = new Set(r.items.map((m) => m.id))
  if (r.insecure) return msg('这个页面不是加密连接（http），为安全起见不自动填充。可以用上面的搜索手动选择。')
  $('list').innerHTML = r.items.length ? `<div class="sec">适用于 ${esc(new URL(tab.url).hostname)}</div>` + r.items.map((m) => row(m, false)).join('') : '<div class="msg">没有匹配这个网站的密码。<br>登录一次后，页面上会问你要不要保存；也可以在上面搜索手动选择。</div>'
}

$('list').addEventListener('click', async (e) => {
  const d = e.target.closest('.it'); if (!d) return
  const force = d.dataset.force === '1'
  if (force && !confirm('这条密码的网址和当前网站不一致。\n只有你确定这个网站就是它时才继续，是否仍然填充？')) return
  const r = await send({ t: 'p-fill', id: d.dataset.id, url: tab.url, tabId: tab.id, force })
  if (r.ok) window.close(); else msg(r.error || '填充失败', true)
})
let t = null
$('q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(show, 200) })

chrome.storage.local.get('autoFill', (o) => { $('auto').checked = !o || o.autoFill !== false })
$('auto').addEventListener('change', () => chrome.storage.local.set({ autoFill: $('auto').checked }))

;(async () => {
  [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  const p = await send({ t: 'p-ping' })
  if (!p.ok) return msg(p.error || '连不上工具箱', true)
  $('st').textContent = p.count + ' 个密码'
  show()
})()
