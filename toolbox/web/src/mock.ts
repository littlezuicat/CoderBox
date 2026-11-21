// 浏览器里没有 Python 时的模拟后端：只为了开发和截图，行为尽量贴近真实接口。
import { emitLocal } from './bridge'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const S: any = {
  settings: {}, busy: false, autoKey: true, key: { exists: false },
  hosts: [
    { alias: 'nas', host: '192.168.1.20', user: 'demo', port: 22, identity: '', has_password: true, managed: true },
    { alias: 'workstation', host: '192.168.1.105', user: 'zuicat', port: 22, identity: '~/.ssh/id_ed25519', has_password: false, managed: false },
    { alias: 'cloud-hk', host: 'hk.example.com', user: 'root', port: 2222, identity: '', has_password: true, managed: true },
  ],
}
let remoteState: any = { ev: 'state', id: '799093', has_password: false, allow: false, confirm: true, online: false }

export const mock: any = {
  app_info: () => ({ version: '2.0.0', platform: 'win32', settings: S.settings, remote: {}, mode: new URLSearchParams(location.search).get('mode') || 'app', installed: false }),
  installer_state: () => ({ mode: new URLSearchParams(location.search).get('mode') || 'installer', version: '2.0.0', default_dir: 'C:\\Users\\demo\\AppData\\Local\\Programs\\ClaudeToolbox', existing: new URLSearchParams(location.search).get('existing') ? { dir: 'C:\\Users\\demo\\AppData\\Local\\Programs\\ClaudeToolbox', version: '1.4.2' } : null }),
  installer_pick_dir: () => 'D:\\软件\\ClaudeToolbox',
  installer_run: async () => { ;(async () => { for (let k = 1; k <= 10; k++) { await sleep(250); emitLocal('inst:progress', { pct: k * 10, text: k < 9 ? '正在复制程序文件…' : '创建桌面快捷方式…' }) } emitLocal('inst:done', { ok: true, exe: 'C:\\x\\ClaudeToolbox.exe' }) })(); return true },
  uninstall_run: async () => { ;(async () => { for (let k = 1; k <= 5; k++) { await sleep(300); emitLocal('inst:progress', { pct: k * 20, text: '删除程序文件…' }) } emitLocal('inst:done', { ok: true }) })(); return true },
  installer_launch: () => true, installer_exit: () => true,
  settings_set: (k: string, v: any) => { S.settings[k] = v; return true },
  pick_files: () => [],
  pick_folder: () => 'C:\\Users\\demo\\Desktop',
  history_list: (kind: string) => (S.history || (S.history = [
    { id: 'a1', kind: 'ppt', name: '期末答辩.pptx', output: 'C:\\Users\\demo\\Downloads\\期末答辩_定图.pptx', ok: true, detail: '32 页 · 3840×2160', size: 48_300_000, time: 1795270000, exists: true },
    { id: 'a2', kind: 'ppt', name: '损坏的文件.pptx', output: '', ok: false, detail: '无法打开演示文稿', size: 0, time: 1795260000, exists: false },
    { id: 'b1', kind: 'convert', name: '会议录像.mov', output: 'C:\\Users\\demo\\Downloads\\会议录像.mp4', ok: true, detail: '转成 MP4', size: 120_000_000, time: 1795250000, exists: true },
  ])).filter((e: any) => e.kind === kind),
  history_remove: (id: string) => { S.history = (S.history || []).filter((e: any) => e.id !== id); emitLocal('history:changed', {}); return true },
  history_clear: (kind: string) => { S.history = (S.history || []).filter((e: any) => e.kind !== kind); emitLocal('history:changed', {}); return true },
  reveal: () => true, open_url: (u: string) => { window.open(u, '_blank'); return true },
  file_info: (paths: string[], kind: string) => paths.filter((p) => kind === 'any' || (kind === 'ppt' ? /\.(pptx?|ppsx)$/i.test(p) : /\.(mp4|mp3|wav|png|jpg)$/i.test(p))).map((p) => ({ path: p, name: p.split(/[\\/]/).pop(), size: 48_000_000, kind: kind === 'ppt' ? 'ppt' : kind === 'media' ? 'video' : 'file' })),
  busy_text: () => [],
  ppt_detect: () => 'Microsoft PowerPoint',
  ppt_start: async (files: any[]) => {
    ;(async () => {
      for (let i = 0; i < files.length; i++) {
        emitLocal('ppt:file', { idx: i, state: 'run' })
        for (let k = 1; k <= 10; k++) { await sleep(150); emitLocal('ppt:progress', { idx: i, i: k, n: 10 }) }
        emitLocal('ppt:file', { idx: i, state: 'done', output: 'x', pages: 10, w: 3840, h: 2160 })
      }
      emitLocal('ppt:done')
    })()
    return true
  },
  ppt_stop: () => true,
  convert_targets: () => ({
    video: [{ key: 'mp4', label: 'MP4（H.264，兼容最好）' }, { key: 'mp4-h265', label: 'MP4（H.265，体积小）' }, { key: 'webm', label: 'WebM' }, { key: 'mp3', label: '只要声音 · MP3' }],
    audio: [{ key: 'mp3', label: 'MP3' }, { key: 'flac', label: 'FLAC' }, { key: 'wav', label: 'WAV' }],
    image: [{ key: 'jpg', label: 'JPG' }, { key: 'png', label: 'PNG' }, { key: 'webp', label: 'WebP' }],
  }),
  ff_status: () => ({ ready: true }),
  ff_download: () => true,
  convert_start: async (items: any[]) => {
    ;(async () => {
      for (let i = 0; i < items.length; i++) {
        emitLocal('cv:file', { idx: i, state: 'run' })
        for (let k = 1; k <= 8; k++) { await sleep(120); emitLocal('cv:progress', { idx: i, f: k / 8, eta: 8 - k }) }
        emitLocal('cv:file', { idx: i, state: 'done', output: 'x', size: 5_000_000 })
      }
      emitLocal('cv:done')
    })()
    return true
  },
  convert_stop: () => true,
  ssh_hosts: () => ({ ok: true, hosts: S.hosts, key: S.key, auto_key: !!S.autoKey, config: 'C:\\Users\\demo\\.ssh\\config' }),
  ssh_check: async (a: string) => { await sleep(300 + Math.random() * 900); return a === 'cloud-hk' ? { ok: false, error: '连接 hk.example.com:2222 超时，请检查 IP、端口和网络。' } : { ok: true, via: a === 'workstation' || S.key.exists ? 'key' : 'password', ms: 20 + Math.floor(Math.random() * 80) } },
  ssh_test: async (h: any) => { await sleep(500); return h.password === 'bad' ? { ok: false, error: '认证失败：密码或密钥不对。' } : { ok: true, via: h.password ? 'password' : 'key', os: 'Linux' } },
  ssh_save: (h: any, old?: string) => {
    const i = S.hosts.findIndex((x: any) => x.alias === (old || h.alias))
    const n = { alias: h.alias, host: h.host, user: h.user, port: h.port || 22, identity: h.identity || '', has_password: !!h.password || (i >= 0 && S.hosts[i].has_password), managed: true }
    if (i >= 0) S.hosts[i] = n; else S.hosts.push(n)
    return { ok: true, host: n, note: S.autoKey ? '已自动配置密钥。' : '' }
  },
  ssh_delete: (a: string) => { S.hosts = S.hosts.filter((x: any) => x.alias !== a); return true },
  ssh_key_all: async () => {
    for (let i = 0; i < S.hosts.length; i++) { emitLocal('ssh:keyprogress', { i, n: S.hosts.length, alias: S.hosts[i].alias }); await sleep(400) }
    S.key = { exists: true, path: 'C:\\Users\\demo\\.ssh\\claude_toolbox_ed25519', fingerprint: 'SHA256:q3fQ0m8mT2yX1nB7cJz9L4v5R6s8wKpA2dEh0uYtGgI' }
    S.hosts.forEach((h: any) => { h.identity = '~/.ssh/claude_toolbox_ed25519' })
    return { ok: true, key: S.key, results: S.hosts.map((h: any, i: number) => (i === 2 ? { alias: h.alias, ok: false, error: '认证失败：密码或密钥不对。' } : { alias: h.alias, ok: true, error: '' })) }
  },
  ssh_key_export: () => ({ ok: true }),
  download_dir_info: () => ({ path: S.dl || 'C:\\Users\\demo\\Desktop', custom: !!S.dl }),
  download_dir_pick: () => { S.dl = 'D:\\文件\\下载'; return { path: S.dl, custom: true } },
  download_dir_reset: () => { S.dl = ''; return { path: 'C:\\Users\\demo\\Desktop', custom: false } },
  open_path: () => true,
  ssh_auto_key: (on: boolean) => { S.autoKey = on; return true },
  ssh_ls: (alias: string, path: string) => {
    const p = path || '/home/demo'
    return { ok: true, path: p, entries: [
      { name: 'projects', dir: true, size: 4096, mtime: 1762000000 }, { name: 'backup', dir: true, size: 4096, mtime: 1761000000 },
      { name: 'notes.txt', dir: false, size: 1834, mtime: 1762300000 }, { name: 'dataset.tar.gz', dir: false, size: 3_250_000_000, mtime: 1760000000 }, { name: 'run.sh', dir: false, size: 512, mtime: 1759000000 },
    ] }
  },
  ssh_mkdir: () => ({ ok: true }),
  ssh_upload: async (alias: string) => { ;(async () => { for (let k = 1; k <= 8; k++) { await sleep(250); emitLocal('ssh:progress', { kind: 'up', sent: k * 4e6, total: 32e6, speed: 16e6, file: 'demo.mp4' }) } emitLocal('ssh:done', { ok: true, kind: 'up', alias, count: 1, secs: 2 }) })(); return { ok: true } },
  ssh_download: async (alias: string, _items?: any) => { ;(async () => { for (let k = 1; k <= 8; k++) { await sleep(250); emitLocal('ssh:progress', { kind: 'down', sent: k * 4e6, total: 32e6, speed: 16e6, file: 'notes.txt' }) } emitLocal('ssh:done', { ok: true, kind: 'down', alias, count: 1, secs: 2, dest: 'C:\\Users\\demo\\Desktop' }) })(); return { ok: true } },
  share_info: () => S.share || { on: false },
  share_start: async (sec: number) => {
    S.share = { on: true, port: 41873, user: 'zuicat', password: 'k7Vn3hQe9TzXw2Ab', ips: ['192.168.1.103', '10.66.0.7'], expires: sec ? Date.now() / 1000 + sec : 0, started: Date.now() / 1000, sessions: [], log: [{ t: Date.now() / 1000, text: '已开启，端口 41873' }] }
    setTimeout(() => emitLocal('share:state', S.share), 50)
    return { ok: true, ...S.share }
  },
  share_stop: () => { S.share = { on: false }; setTimeout(() => emitLocal('share:state', S.share), 50); return true },
  share_kick: () => true,
  ssh_cancel: () => true,
  term_open: async () => {
    const id = 't' + Math.random().toString(36).slice(2, 6)
    setTimeout(() => emitLocal('term:data', { id, data: 'Welcome to Ubuntu 24.04 LTS (GNU/Linux 6.8.0 x86_64)\r\n\r\nLast login: Sat Nov 21 17:40:12 2026 from 192.168.1.103\r\ndemo@nas:~$ ' }), 200)
    ;(window as any).__tid = id
    return { ok: true, id, via: 'key' }
  },
  term_input: (id: string, d: string) => { emitLocal('term:data', { id, data: d === '\r' ? '\r\ndemo@nas:~$ ' : d }); return true },
  term_resize: () => true,
  term_close: () => true,
  remote_send: async (cmd: any) => {
    await sleep(200)
    if (cmd.cmd === 'set_password') { remoteState = { ...remoteState, has_password: true, password: cmd.password }; setTimeout(() => emitLocal('remote:event', remoteState), 50); return { ok: true } }
    if (cmd.cmd === 'set') { remoteState = { ...remoteState, ...('allow' in cmd ? { allow: cmd.allow, online: cmd.allow } : {}), ...('confirm' in cmd ? { confirm: cmd.confirm } : {}) }; setTimeout(() => emitLocal('remote:event', remoteState), 50); return { ok: true } }
    if (cmd.cmd === 'connect') {
      setTimeout(() => emitLocal('remote:event', { ev: 'sessions', out: [{ target: cmd.target, name: '对方电脑', alias: 'coderland-' + cmd.target, since: Date.now() / 1000 }], in: [{ from: '654321', name: '小王', sid: 's1', since: Date.now() / 1000, conns: 2 }] }), 100)
      return { ok: true, alias: 'coderland-' + cmd.target, name: '对方电脑' }
    }
    return { ok: true }
  },
  open_terminal: () => ({ ok: true }),
  update_check: () => true,
  set_titlebar: () => true,
  account_status: () => (S.acct ? { bound: true, name: '任义', username: 'renyi', avatar: '' } : { bound: false }),
  account_login: () => { setTimeout(() => { S.acct = true; emitLocal('account:event', { state: 'ok', status: { bound: true, name: '任义', username: 'renyi', avatar: '' } }) }, 4000); return { ok: true, user_code: 'K7XM-4P9Q', url: 'https://code.zuicat.cn/toolbox-auth.html?code=K7XM-4P9Q' } },
  account_cancel: () => true,
  account_unbind: () => { S.acct = false; return { ok: true } },
}
setTimeout(() => emitLocal('remote:event', remoteState), 500)
