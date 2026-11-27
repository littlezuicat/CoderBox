// 码境密码 · 页面脚本：点用户名/密码框弹出账号菜单、点选后填充；符合条件时打开页面就自动填充；登录提交后询问是否保存。
// 页面里的脚本拿不到密码：密码只由后台在填充那一刻取出，直接写进输入框。
// 自动填充（打开页面就填）的安全条件：只在顶层页面；网址由主机匹配（http 外网不填）；登录框必须真正可见、没被遮住、没透明/移出屏幕；
// 只有一个匹配账号、或这个网站上次选过某个账号时才填；框里已有内容不动。
(() => {
  if (window.__majingPw) return
  window.__majingPw = true
  const send = (m) => new Promise((res) => { try { chrome.runtime.sendMessage(m, (r) => res(r || { ok: false })) } catch (e) { res({ ok: false }) } })
  const visible = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 8 && r.height > 8 && cs.visibility !== 'hidden' && cs.display !== 'none' }
  const usable = (el) => !el.disabled && !el.readOnly && visible(el)

  // ---- 找登录框
  const pwFields = () => [...document.querySelectorAll('input[type=password]')].filter(usable)
  const userFieldFor = (pw) => {
    const all = [...document.querySelectorAll('input')].filter((i) => /^(text|email|tel|)$/i.test(i.type) && usable(i))
    let best = null
    for (const i of all) { if (i.compareDocumentPosition(pw) & Node.DOCUMENT_POSITION_FOLLOWING) best = i; else break }   // 密码框前面最近的一个文本框
    if (!best) return null
    const f = pw.form
    return (!f || best.form === f) ? best : null
  }
  const setVal = (el, v) => {                              // 不 focus，避免抢走页面焦点（页面加载时自动填充尤其要注意）
    const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')
    d.set.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true }))
  }
  const fill = (c, pwTarget) => {
    const pws = pwFields()
    if (!pws.length) return false
    const pw = (pwTarget && pws.includes(pwTarget)) ? pwTarget : (pws.find((p) => !p.value) || pws[0])
    const u = userFieldFor(pw)
    if (u && c.username) setVal(u, c.username)
    setVal(pw, c.password)
    return true
  }
  const pwOf = (el) => (el.type === 'password' ? el : pwFields().find((p) => userFieldFor(p) === el) || null)

  // ---- 设置（弹窗里的开关）和“每个网站上次选的账号”
  const store = chrome.storage && chrome.storage.local
  let autoOn = true, lu = {}
  const ready = new Promise((res) => { try { store.get(['autoFill', 'lu'], (o) => { autoOn = !o || o.autoFill !== false; lu = (o && o.lu) || {}; res() }) } catch (e) { res() } })
  try { chrome.storage.onChanged.addListener((c) => { if (c.autoFill) autoOn = c.autoFill.newValue !== false }) } catch (e) { /* 扩展刚更新时会抛，忽略 */ }
  const remember = (id) => { lu[location.hostname] = id; try { store.set({ lu }) } catch (e) { /* 忽略 */ } }

  // ---- 界面（放在 shadow DOM 里，页面样式碰不到）
  const host = document.createElement('div')
  host.style.cssText = 'all:initial;position:fixed;z-index:2147483647;top:0;left:0;width:0;height:0'
  const root = host.attachShadow({ mode: 'closed' })
  root.innerHTML = `<style>
    *{box-sizing:border-box;font-family:'Segoe UI','Microsoft YaHei',sans-serif}
    .key{position:fixed;width:22px;height:22px;border-radius:6px;background:#2f5bd8;color:#fff;font-size:13px;display:none;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 1px 4px #0005;user-select:none}
    /* 和 Chrome 自带的账号下拉一样：窄白卡片、小圆角、轻阴影；每行 钥匙图标 + 用户名(14px) + 下面一行圆点(12px)，悬停浅灰 */
    .menu{position:fixed;min-width:200px;max-width:320px;background:#fff;color:#202124;border-radius:8px;box-shadow:0 2px 8px rgba(60,64,67,.3),0 0 0 1px rgba(60,64,67,.08);padding:4px 0;display:none;font-size:14px;overflow:hidden}
    .menu .row{padding:7px 14px 7px 12px;cursor:pointer;display:flex;align-items:center;gap:12px}
    .menu .row:hover,.menu .row.hi{background:#f1f3f4}
    .menu .ico{flex:none;width:18px;height:18px;border-radius:5px;background:#2f5bd8;color:#fff;font-size:11px;display:flex;align-items:center;justify-content:center}
    .menu .tx{display:flex;flex-direction:column;min-width:0;line-height:1.35}
    .menu b{font-weight:400;font-size:14px;color:#202124;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .menu small{color:#5f6368;font-size:12px;letter-spacing:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .menu .foot{padding:7px 12px;border-top:1px solid #e8eaed;color:#5f6368;font-size:12px;display:flex;align-items:center;gap:12px;cursor:default}
    .bar{position:fixed;top:14px;right:14px;width:340px;background:#fff;color:#202124;border-radius:8px;box-shadow:0 2px 10px rgba(60,64,67,.35);padding:14px 16px;display:none;font-size:14px;line-height:1.6}
    .bar p{margin:0 0 10px} .bar button{border:0;border-radius:6px;padding:7px 16px;font-size:14px;cursor:pointer;margin-right:8px}
    .ok{background:#2f5bd8;color:#fff} .no{background:#e9e9ee;color:#202124}
    .toast{position:fixed;top:14px;right:14px;background:#323232;color:#fff;border-radius:6px;padding:9px 16px;font-size:14px;display:none}
  </style><div class="key" title="码境密码">🔑</div><div class="menu"></div><div class="bar"></div><div class="toast"></div>`
  const keyEl = root.querySelector('.key'), menu = root.querySelector('.menu'), bar = root.querySelector('.bar'), toastEl = root.querySelector('.toast')
  // 网页里的模态对话框（<dialog> + showModal，比如 code.zuicat.cn 的登录框）在浏览器“顶层”，挂在页面根上的东西会被它盖住、还点不了。
  // 所以有打开的 <dialog> 时，把我们的界面挂进最上面那个对话框里；没有就挂在页面根上。
  const origin = () => { const r = host.getBoundingClientRect(); return [r.left, r.top] }
  const mount = (el) => {                                  // el：当前要操作的输入框；优先挂进它所在的那个对话框（页面上可能同时开着好几个）
    const own = (e) => (e && e.closest ? e.closest('dialog[open]') : null)
    const open = [...document.querySelectorAll('dialog[open]')]
    const d = own(el) || own(typeof target !== 'undefined' ? target : null) || open[open.length - 1] || null
    const parent = d || document.documentElement
    if (host.parentNode !== parent) parent.appendChild(host)
  }
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
  const toast = (t) => { mount(); toastEl.textContent = t; toastEl.style.display = 'block'; setTimeout(() => (toastEl.style.display = 'none'), 3500) }

  let matches = [], target = null, anchor = null, hi = -1, shown = []
  const place = () => {
    const pw = target && target.isConnected && usable(target) ? target : (pwFields()[0] || null)
    target = pw
    if (!pw || !matches.length) { keyEl.style.display = 'none'; return }
    mount(pw)
    const r = pw.getBoundingClientRect()
    const o = origin()
    keyEl.style.display = 'flex'
    keyEl.style.left = (Math.max(0, Math.min(innerWidth - 26, r.right - 28)) - o[0]) + 'px'
    keyEl.style.top = (r.top + (r.height - 22) / 2 - o[1]) + 'px'
  }
  // 悬停/键盘选中某个账号时，把它“预填”到输入框里（和 Chrome 一样：淡蓝底、不触发页面事件），移开或关闭就还原。
  // 预览只放用户名（本来就在菜单里）；密码框放一串占位圆点，**真实密码只在点击确认那一刻才取**。
  const dots = (m) => '•'.repeat(Math.max(1, Math.min(m && m.plen ? m.plen : 8, 32)))
  let pv = null
  const rawSet = (el, v) => Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v)
  const unpreview = () => {
    if (!pv) return
    for (const f of pv.fields) { if (f.el.isConnected) { rawSet(f.el, f.value); f.el.style.cssText = f.style } }
    pv = null
  }
  const preview = (m) => {
    unpreview()
    const pw = anchor && pwOf(anchor)
    if (!pw || !m) return
    const u = userFieldFor(pw)
    pv = { fields: [] }
    const put = (el, v) => { pv.fields.push({ el, value: el.value, style: el.style.cssText }); rawSet(el, v); el.style.setProperty('background-color', '#e8f0fe', 'important'); el.style.setProperty('color', '#3c4043', 'important') }
    if (u && m.username) put(u, m.username)
    put(pw, dots(m))
  }
  const closeMenu = () => { unpreview(); menu.style.display = 'none'; hi = -1 }
  const menuOpen = () => menu.style.display === 'block'
  // 菜单里列哪些账号：在用户名框里已经输了字就按它过滤；但框里正好是某个已存账号（比如刚填充过）时列全部，方便换号
  const listFor = (field) => {
    const q = field.type === 'password' ? '' : (field.value || '').trim().toLowerCase()
    if (!q || matches.some((m) => (m.username || '').toLowerCase() === q)) return matches
    return matches.filter((m) => (m.username || '').toLowerCase().includes(q))
  }
  const openFor = (field) => {
    unpreview()                                            // 先还原预览，再按真实内容算要列哪些账号
    if (!field || !matches.length) return false
    const list = listFor(field)
    if (!list.length) { closeMenu(); return false }
    unpreview(); mount(field); anchor = field; shown = list; hi = -1
    menu.innerHTML = list.map((m, i) => `<div class="row" data-i="${i}"><span class="ico">🔑</span><span class="tx"><b>${esc(m.username || m.name || m.url)}</b><small>${dots(m)}</small></span></div>`).join('') + '<div class="foot"><span class="ico">🔑</span>码境密码</div>'
    const r = field.getBoundingClientRect()
    menu.style.display = 'block'
    menu.style.minWidth = Math.min(Math.max(200, r.width * 0.6), 300) + 'px'
    const o = origin()
    menu.style.left = (Math.max(4, Math.min(innerWidth - 330, r.left)) - o[0]) + 'px'
    menu.style.top = (Math.min(innerHeight - 80, r.bottom + 2) - o[1]) + 'px'
    return true
  }
  const pick = async (m) => {
    const field = anchor; closeMenu()                          // closeMenu 会先把预览还原，再真正填充
    const r = await send({ t: 'fill', id: m.id })
    if (!r.ok) return toast(r.error || '填充失败')
    fill(r, field ? pwOf(field) : null); remember(m.id)
  }
  menu.addEventListener('mouseover', (e) => { const d = e.target.closest && e.target.closest('.row'); if (d) { hi = +d.dataset.i; [...menu.querySelectorAll('.row')].forEach((c, i) => c.classList.toggle('hi', i === hi)); preview(shown[hi]) } })
  menu.addEventListener('mouseleave', () => { hi = -1; [...menu.querySelectorAll('.row')].forEach((c) => c.classList.remove('hi')); unpreview() })
  menu.addEventListener('mousedown', (e) => e.preventDefault())            // 点菜单不要让输入框失去焦点
  menu.addEventListener('click', (e) => { const d = e.target.closest('[data-i]'); if (d) pick(shown[+d.dataset.i]) })
  keyEl.addEventListener('mousedown', (e) => { e.preventDefault(); e.stopPropagation(); if (menuOpen()) closeMenu(); else refresh(true).then(() => openFor(target)) })
  document.addEventListener('mousedown', (e) => { if (menuOpen() && !e.composedPath().includes(host)) closeMenu() }, true)

  // 点/聚焦用户名框或密码框、或在用户名框里打字 → 弹出账号菜单（和 Chrome 自带的一样）
  const isLoginField = (el) => !!el && el.tagName === 'INPUT' && (el.type === 'password' || (/^(text|email|tel|)$/i.test(el.type) && !!pwOf(el)))
  const onField = (e) => {
    const el = e.target
    if (!isLoginField(el) || !usable(el)) return
    if (!fetched) refresh().then(() => openFor(el))          // 页面加载时登录框还没出现，现在才第一次取账号
    else if (matches.length) openFor(el)
  }
  document.addEventListener('focusin', onField, true)
  document.addEventListener('click', onField, true)
  document.addEventListener('input', (e) => { if (e.isTrusted && e.target.type !== 'password') onField(e) }, true)   // 只响应真人打字；我们自己填充发的事件（不可信）不弹菜单
  document.addEventListener('keydown', (e) => {
    if (e.target !== anchor && !(menuOpen() && isLoginField(e.target))) return
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!menuOpen() && !openFor(e.target)) return
      const n = shown.length
      hi = e.key === 'ArrowDown' ? (hi + 1) % n : (hi - 1 + n) % n
      ;[...menu.querySelectorAll('.row')].forEach((c, i) => c.classList.toggle('hi', i === hi))
      preview(shown[hi])
      e.preventDefault()
    } else if (e.key === 'Enter' && menuOpen() && hi >= 0) { e.preventDefault(); e.stopPropagation(); pick(shown[hi]) }
    else if (e.key === 'Escape' || e.key === 'Tab') closeMenu()
  }, true)

  // ---- 取匹配的账号（一个页面只问一次，之后用缓存；点钥匙时强制重问）
  let inflight = null, fetched = false, lastTry = 0
  const refresh = (force) => inflight || (inflight = doRefresh(force).finally(() => { inflight = null }))   // 正在取的时候再调用，就等同一次结果（点钥匙时不会因为“正在取”而没反应）
  const doRefresh = async (force) => {
    if (!pwFields().length) { matches = []; fetched = false; place(); return }
    if (!fetched || force) {
      if (!force && Date.now() - lastTry < 4000) { place(); return }
      lastTry = Date.now()
      const r = await send({ t: 'match' })
      matches = r.ok ? r.items || [] : []
      fetched = !!r.ok
    }
    if (matches.length) mount()
    place()
    autoFill()
  }

  // ---- 打开页面自动填充
  const done = new WeakSet()
  const trusted = (el) => {                                // 真的看得见、没被盖住、没藏起来才信
    const r = el.getBoundingClientRect()
    if (r.width < 20 || r.height < 12 || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) return false
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) { const cs = getComputedStyle(n); if (+cs.opacity < 0.4 || cs.visibility === 'hidden') return false }
    const hit = document.elementFromPoint(Math.min(innerWidth - 1, Math.max(0, r.left + r.width / 2)), Math.min(innerHeight - 1, Math.max(0, r.top + r.height / 2)))
    return hit === el
  }
  const autoFill = async () => {
    await ready
    if (!autoOn || !matches.length) return
    for (const pw of pwFields()) {
      if (done.has(pw) || pw.value || pw.autocomplete === 'new-password' || !trusted(pw)) continue
      const u = userFieldFor(pw)
      if (u && !trusted(u)) continue
      const m = matches.length === 1 ? matches[0] : matches.find((x) => x.id === lu[location.hostname])
      if (!m) continue
      if (u && u.value && u.value !== m.username) continue   // 网站自己预填了别的用户名：不动
      done.add(pw)
      const r = await send({ t: 'fill', id: m.id })
      if (r.ok) { fill(r, pw); remember(m.id) }
    }
  }

  let timer = null
  const later = () => { clearTimeout(timer); timer = setTimeout(() => refresh(), 400) }
  // 登录框常常一开始就在页面里、只是隐藏着，点“登录”后换个 class/style 才显示（单页应用，比如 code.zuicat.cn）：所以也要监听这些属性变化
  new MutationObserver(later).observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style', 'hidden', 'open', 'aria-hidden'] })
  addEventListener('resize', place); addEventListener('scroll', place, true)
  refresh()

  // ---- 登录提交后问要不要保存
  const snapshot = () => {
    const pw = pwFields().find((p) => p.value)
    if (!pw) return null
    const u = userFieldFor(pw)
    return { username: u ? u.value : '', password: pw.value }
  }
  let sentAt = 0
  const captured = async () => {
    const s = snapshot()
    if (!s || Date.now() - sentAt < 800) return
    sentAt = Date.now()
    await send({ t: 'captured', ...s })
    setTimeout(checkPending, 1200)                       // 单页应用不换页：1 秒多后直接问
  }
  document.addEventListener('submit', captured, true)
  document.addEventListener('click', (e) => { const b = e.target.closest && e.target.closest('button,input[type=submit],[role=button]'); if (b && pwFields().some((p) => p.value) && (b.type === 'submit' || b.form || /登录|登入|sign ?in|log ?in|submit/i.test(b.textContent || b.value || ''))) captured() }, true)
  document.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target && e.target.type === 'password' && !menuOpen()) captured() }, true)

  const checkPending = async () => {
    const r = await send({ t: 'pending' })
    if (!r.ok || !r.pending) return
    const p = r.pending
    mount()
    bar.innerHTML = `<p><b>码境密码</b>：${p.status === 'update' ? '更新' : '保存'} <b>${esc(p.username || '（无用户名）')}</b> 在 ${esc(p.host)} 的登录？</p><button class="ok">${p.status === 'update' ? '更新' : '保存'}</button><button class="no">忽略</button>`
    bar.style.display = 'block'
    const close = () => (bar.style.display = 'none')
    bar.querySelector('.ok').onclick = async () => { close(); const s = await send({ t: 'savePending' }); toast(s.ok ? (s.status === 'added' ? '已保存到码境密码' : '已更新') : s.error || '保存失败') }
    bar.querySelector('.no').onclick = async () => { close(); await send({ t: 'dismiss' }) }
    setTimeout(close, 30000)
  }
  checkPending()

  chrome.runtime.onMessage.addListener((m) => {
    if (m.t === 'doFill') { if (!fill(m)) toast('没找到登录框') }
    else if (m.t === 'toast') toast(m.text)
    else if (m.t === 'showMenu') refresh(true).then(() => { if (!openFor(target)) toast('没有匹配这个网站的密码') })
  })
})()
