// 浏览器里没有 Python 时的模拟后端：只为了开发和截图，行为尽量贴近真实接口。
import { emitLocal } from './bridge'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
// 浏览器里调界面用的假保险库数据（只在 mock 里，和真实保险库无关）
const MOCK_VAULT: any[] = [
  { id: 'a1', type: 'login', name: 'GitHub', username: 'demo@example.com', password: 'demo-password-1', url: 'https://github.com', notes: '示例', folder: '开发', updated: 1700000000 },
  { id: 'a2', type: 'note', name: '示例笔记', username: '', password: '', url: '', notes: '这是一条安全笔记', folder: '', updated: 1700000100 },
]
const S: any = {
  settings: {}, busy: false, autoKey: true, key: { exists: false },
  hosts: [
    { alias: 'nas', host: '192.168.1.20', user: 'demo', port: 22, identity: '', has_password: true, managed: true },
    { alias: 'workstation', host: '192.168.1.105', user: 'zuicat', port: 22, identity: '~/.ssh/id_ed25519', has_password: false, managed: false },
    { alias: 'cloud-hk', host: 'hk.example.com', user: 'root', port: 2222, identity: '', has_password: true, managed: true },
    { alias: 'a100-lab', host: '10.0.0.8', user: 'lixiang', port: 22, identity: '', has_password: true, managed: true },
    { alias: '4090-box', host: '10.0.0.9', user: 'zuicat', port: 22, identity: '', has_password: false, managed: true },
  ],
}
let remoteState: any = { ev: 'state', id: '799093', has_password: false, allow: false, confirm: true, online: false }


// ---- GPU 假数据
const jit = (v: number, r: number, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, Math.round(v + (Math.random() - 0.5) * r)))
const GB = 1024
function mockSamples(): Record<string, any> {
  const t = Math.floor(Date.now() / 1000)
  const a100 = [0, 1, 2, 3].map((i) => ({ index: i, uuid: 'GPU-a' + i, name: 'NVIDIA A100-SXM4-80GB', util: i < 2 ? jit(94, 8, 70) : i === 2 ? jit(41, 30) : jit(1, 2), mem_used: [74, 70, 31, 0][i] * GB + (i < 3 ? jit(0, 800, 0, 900) : 300), mem_total: 80 * GB, temp: [76, 73, 58, 33][i] }))
  const box = [0, 1].map((i) => ({ index: i, uuid: 'GPU-b' + i, name: 'NVIDIA GeForce RTX 4090', util: i === 0 ? jit(63, 20) : jit(2, 3), mem_used: i === 0 ? 9 * GB : 400, mem_total: 24 * GB, temp: i === 0 ? 61 : 34 }))
  return {
    'a100-lab': { t, state: 'ok', os: 'linux', gpus: a100 },
    '4090-box': { t, state: 'ok', os: 'linux', gpus: box },
    workstation: { t, state: 'nogpu', gpus: [] },
    nas: { t, state: 'nogpu', gpus: [] },
  }
}


// ---- 虚拟文件系统：路径 → {dir, text?}
type VNode = { dir: boolean; text?: string; size?: number; mtime?: number }
const VFS = new Map<string, VNode>()
const vfsNorm = (p: string) => { const r = '/' + p.split('/').filter((x) => x && x !== '.').join('/'); return r }
const vfsDel = (p: string) => { for (const k of [...VFS.keys()]) if (k === p || k.startsWith(p + '/')) VFS.delete(k) }
;(() => {
  const d = (p: string) => VFS.set(p, { dir: true })
  const f = (p: string, text: string) => VFS.set(p, { dir: false, text, mtime: 1762300000 })
  ;['/', '/home', '/home/demo', '/home/demo/projects', '/home/demo/projects/llm-train', '/home/demo/projects/llm-train/configs', '/home/demo/projects/llm-train/logs', '/home/demo/backup'].forEach(d)
  f('/home/demo/notes.txt', '本周计划\n- 把 baseline 在 4090 上复现\n- A100 上跑 7B 的长上下文实验\n- 周五前把结果整理成表\n')
  f('/home/demo/run.sh', '#!/bin/bash\ncd ~/projects/llm-train\nCUDA_VISIBLE_DEVICES=0,1 torchrun --nproc_per_node=2 train.py --config configs/base.yaml\n')
  VFS.set('/home/demo/dataset.tar.gz', { dir: false, size: 3_250_000_000, mtime: 1760000000 })
  f('/home/demo/projects/llm-train/train.py', 'import argparse\nimport torch\nimport yaml\n\n\ndef main():\n    ap = argparse.ArgumentParser()\n    ap.add_argument("--config", required=True)\n    args = ap.parse_args()\n    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))\n    print("lr =", cfg["lr"], "batch =", cfg["batch_size"])\n    model = torch.nn.Linear(cfg["dim"], cfg["dim"]).cuda()\n    opt = torch.optim.AdamW(model.parameters(), lr=cfg["lr"])\n    for step in range(cfg["steps"]):\n        x = torch.randn(cfg["batch_size"], cfg["dim"], device="cuda")\n        loss = (model(x) - x).pow(2).mean()\n        loss.backward(); opt.step(); opt.zero_grad()\n        if step % 100 == 0:\n            print(f"step {step} loss {loss.item():.4f}")\n\n\nif __name__ == "__main__":\n    main()\n')
  f('/home/demo/projects/llm-train/configs/base.yaml', 'lr: 0.0003\nbatch_size: 64\ndim: 4096\nsteps: 20000\nwarmup: 500\nseed: 42\n')
  f('/home/demo/projects/llm-train/README.md', '# llm-train\n\n小规模语言模型训练实验。\n\n```bash\ntorchrun --nproc_per_node=2 train.py --config configs/base.yaml\n```\n')
  f('/home/demo/projects/llm-train/logs/train.log', 'step 0 loss 1.9321\nstep 100 loss 1.2204\nstep 200 loss 0.8873\nstep 300 loss 0.6412\n')
})()

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
  reveal: () => true, start_drag: () => true,
  vault_list: (q = '', folder = '') => {
    const all = MOCK_VAULT.filter((i) => (!folder || i.folder === folder) && (!q || [i.name, i.username, i.url, i.folder, i.notes].some((s) => String(s).toLowerCase().includes(q.toLowerCase()))))
    return { ok: true, items: all.map(({ password, notes, ...r }) => ({ ...r, has_password: !!password, has_notes: !!notes })), count: MOCK_VAULT.length, folders: [...new Set(MOCK_VAULT.map((i) => i.folder).filter(Boolean))], exists: true, recovered: false }
  },
  vault_get: (id: string) => { const i = MOCK_VAULT.find((x) => x.id === id); return i ? { ok: true, item: { ...i } } : { ok: false, error: '没有这个条目。' } },
  vault_save: (it: any) => { if (!it.name) return { ok: false, error: '名称不能为空。' }; if (it.id) { Object.assign(MOCK_VAULT.find((x) => x.id === it.id)!, it, { updated: Date.now() / 1000 }); return { ok: true, id: it.id } } const id = Math.random().toString(16).slice(2); MOCK_VAULT.push({ ...it, id, updated: Date.now() / 1000 }); return { ok: true, id } },
  vault_delete: (id: string) => { const k = MOCK_VAULT.findIndex((x) => x.id === id); if (k >= 0) MOCK_VAULT.splice(k, 1); return { ok: true } },
  ext_status: () => ({ ok: true, ext_dir: 'C:\\Users\\demo\\toolbox\\extension', ext_id: 'fckanncbkfgihdooginknddjhgkigjnd', files: !!(S as any).ext, chrome: !!(S as any).ext, edge: !!(S as any).ext }),
  ext_install: () => { (S as any).ext = true; return { ok: true, ext_dir: 'C:\\Users\\demo\\toolbox\\extension', ext_id: 'fckanncbkfgihdooginknddjhgkigjnd', files: true, chrome: true, edge: true } },
  ext_uninstall: () => { (S as any).ext = false; return { ok: true, files: false, chrome: false, edge: false } },
  ext_open_browser: () => ({ ok: true }),
  vault_sync_status: () => ({ ok: true, account: !!S.acct, enabled: !!(S as any).vsync, user: '7', last_ok: (S as any).vsync ? Math.floor(Date.now() / 1000) : 0, url: '' }),
  vault_sync_kick: () => ({ ok: true }),
  vault_sync_probe: () => ({ ok: true, exists: false, user: '7' }),
  vault_sync_enable: (pw: string, confirm?: string) => (pw.length < 8 ? { ok: false, error: '主密码至少 8 位。' } : confirm !== undefined && confirm !== pw ? { ok: false, error: '两次输入的主密码不一样。' } : ((S as any).vsync = true, { ok: true, mode: 'created', changed: false, pushed: true })),
  vault_sync_now: () => ({ ok: true, changed: false, pushed: true }),
  vault_sync_disable: () => { (S as any).vsync = false; return { ok: true } },
  vault_pick_import: () => 'C:\\Users\\demo\\Downloads\\bitwarden_export.json',
  vault_import: (_p: string, pw = '', del = false) => (!pw ? { ok: false, need_password: true, error: '这个导出文件有密码，请输入导出时设置的文件密码。' } : pw === 'bad' ? { ok: false, error: '文件密码不对。' } : { ok: true, added: 12, skipped: 3, total: 15, source: 'browser', deleted: del }),
  vault_copy: (_id: string, field: string) => ({ ok: true, secs: field === 'password' ? 15 : 0 }), open_url: (u: string) => { window.open(u, '_blank'); return true },
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
  ssh_extract: async (_a: string, parent: string, names: string[], here: boolean) => { await sleep(1200); return { ok: true, count: names.length, created: here ? [] : names.map((n) => parent + '/' + n.replace(/\.(zip|tar\.gz|tgz|7z|rar)$/i, '')) } },
  ssh_archive: async (_a: string, parent: string, names: string[], kind: string) => { await sleep(1200); VFS.set(vfsNorm(parent + '/' + (names.length === 1 ? names[0].replace(/\.[^.]+$/, '') : '压缩包') + (kind === 'zip' ? '.zip' : '.tar.gz')), { dir: false, size: 12345 }); return { ok: true, count: names.length, created: [parent + '/' + (names.length === 1 ? names[0].replace(/\.[^.]+$/, '') : '压缩包') + (kind === 'zip' ? '.zip' : '.tar.gz')] } },
  ssh_check: async (a: string) => { await sleep(300 + Math.random() * 900); return a === 'cloud-hk' ? { ok: false, error: '连接 hk.example.com:2222 超时，请检查 IP、端口和网络。' } : { ok: true, via: a === 'workstation' || S.key.exists ? 'key' : 'password', ms: 20 + Math.floor(Math.random() * 80) } },
  vsc_install: (alias: string) => { ;(async () => { const P = (step: string, pct: number, text: string) => emitLocal('vsc:progress', { alias, step, pct, text }); P('check', 30, '本机 VS Code 1.146.0，正在连接 ' + alias + '…'); await sleep(700)
    for (let k = 0; k <= 10; k++) { P('download', k * 10, `正在下载 ${(k * 5.8).toFixed(1)} MB / 58.0 MB`); await sleep(220) }
    for (let k = 0; k <= 10; k++) { P('upload', k * 10, `正在上传 ${(k * 5.8).toFixed(1)} / 58.0 MB`); await sleep(220) }
    P('extract', 0, '正在服务器上解压…'); await sleep(1200)
    emitLocal('vsc:done', { alias, ok: true, text: `已在 ${alias} 上装好 VS Code Server（1.146.0）。回到 VS Code 重新连接就行。` }) })(); return { ok: true } },
  // ---- GPU 总览（浏览器里调界面用的假数据）：只在打开页面/点刷新时采样一次
  gpu_state: () => ({ samples: mockSamples() }),
  gpu_sample_now: () => { const m = mockSamples(); setTimeout(() => { for (const a of Object.keys(m)) emitLocal('gpu:sample', { alias: a, sample: m[a] }) }, 300); return { ok: true, busy: false } },
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
  ssh_key_info: () => ({ exists: true, path: 'C:\\Users\\demo\\.ssh\\claude_toolbox_ed25519', fingerprint: 'SHA256:demo' }),
  ssh_key_export: () => ({ ok: true }),
  download_dir_info: () => ({ path: S.dl || 'C:\\Users\\demo\\Desktop', custom: !!S.dl }),
  download_dir_pick: () => { S.dl = 'D:\\文件\\下载'; return { path: S.dl, custom: true } },
  download_dir_reset: () => { S.dl = ''; return { path: 'C:\\Users\\demo\\Desktop', custom: false } },
  open_path: () => true,
  ssh_auto_key: (on: boolean) => { S.autoKey = on; return true },
  // 虚拟文件系统（所有主机共用一份，浏览器里调界面用）
  ssh_ls: (_alias: string, path: string) => {
    const p = vfsNorm(path || '/home/demo')
    if (!VFS.has(p) || !VFS.get(p)!.dir) return { ok: false, error: '没有这个文件夹：' + p }
    const pre = p === '/' ? '/' : p + '/'
    const entries = [...VFS.entries()].filter(([k]) => k !== p && k.startsWith(pre) && !k.slice(pre.length).includes('/'))
      .map(([k, v]) => ({ name: k.slice(pre.length), dir: v.dir, size: v.dir ? 4096 : v.size ?? (v.text || '').length, mtime: v.mtime || 1762000000 }))
    return { ok: true, path: p, entries }
  },
  ssh_mkdir: (_a: string, dir: string, name: string) => { VFS.set(vfsNorm(dir + '/' + name), { dir: true }); return { ok: true } },
  ssh_rename: (_a: string, dir: string, from: string, to: string) => {
    const a = vfsNorm(dir + '/' + from), b = vfsNorm(dir + '/' + to)
    for (const [k, v] of [...VFS.entries()]) if (k === a || k.startsWith(a + '/')) { VFS.delete(k); VFS.set(b + k.slice(a.length), v) }
    return { ok: true }
  },
  ssh_trash: (_a: string, dir: string, n: string[]) => { n.forEach((x) => vfsDel(vfsNorm(dir + '/' + x))); return { ok: true, count: n.length, big: false, pairs: n.map((x) => [dir + '/' + x, '/home/u/.local/share/Trash/files/' + x]) } },
  ssh_rm: (_a: string, dir: string, n: string[]) => { n.forEach((x) => vfsDel(vfsNorm(dir + '/' + x))); return { ok: true, count: n.length } },
  ssh_sysinfo: async (_a: string) => ({ ok: true, family: 'linux', name: 'Ubuntu 22.04.4 LTS', arch: 'x86_64', cpu: { model: 'AMD EPYC 7763 64-Core Processor', cores: 128, usage: 23 }, mem: { total: 268435456000, used: 98000000000 }, disk: { model: 'Samsung SSD 980 PRO 1TB', total: 1000000000000, used: 420000000000 } }),
  ssh_read_file: async (_a: string, path: string) => {
    await sleep(150)
    const f = VFS.get(vfsNorm(path))
    if (!f) return { ok: false, error: '文件不存在。' }
    if (f.dir) return { ok: false, error: '这是文件夹。' }
    if (f.text === undefined) return { ok: false, error: '看起来是二进制文件，不能当文本打开。' }
    return { ok: true, text: f.text, encoding: 'utf-8', size: f.text.length, mtime: f.mtime || 0 }
  },
  ssh_write_file: async (_a: string, path: string, text: string) => {
    await sleep(200)
    const p = vfsNorm(path); VFS.set(p, { dir: false, text, mtime: Date.now() / 1000 })
    return { ok: true, size: text.length, mtime: Date.now() / 1000 }
  },
  ssh_key_one: async () => { await sleep(800); return { ok: true } },
  log_js: () => true,
  devsec_exit_ips: async () => { await sleep(500); return { ok: true, data: { cn: { ip: '203.0.113.8', source: 'ip138' }, cf: { ip: '198.51.100.7', loc: 'jp' }, claude: { ip: '198.51.100.7', loc: 'jp', ms: 180 } } } },
  devsec_geoip: async () => { await sleep(300); return { ok: true, data: { country: 'Japan', region: 'Tokyo', city: 'Tokyo', isp: 'Example ISP', country_code: 'jp' } } },
  devsec_risk: async () => { await sleep(900); return { ok: true, data: { countryCode: 'jp', country: 'Japan', region: 'Tokyo', city: 'Tokyo', timezone: 'Asia/Tokyo', trust_score: 72, isResidential: true, is_vpn: false, is_proxy: false, is_tor: false, is_crawler: false, is_abuser: false, asn: 64500, asOrganization: 'Example ISP' } } },
  devsec_fix: async () => { await sleep(1200); return { ok: true, data: { msg: '已修复（演示）。', changed: true } } },
  devsec_dns: async () => { await sleep(2500); return { ok: true, data: { servers: [], resolved: ['198.18.0.5'] } } },
  devsec_avail: async () => { await sleep(1200); return { ok: true, data: { sites: [{ name: 'claude.ai', ok: true, ms: 210 }, { name: 'anthropic.com', ok: true, ms: 320 }], status: 'none' } } },
  ssh_mv_paths: (_a: string, pairs: any[]) => ({ ok: true, count: pairs.length, pairs }),
  ssh_restore: (_a: string, pairs: any[]) => ({ ok: true, count: pairs.length }),
  ssh_rm_paths: (_a: string, p: any[]) => ({ ok: true, count: p.length }),
  ssh_rmdir: () => ({ ok: true }),
  ssh_mv: (_a: string, parent: string, names: string[], dest: string) => {
    names.forEach((x) => { const a = vfsNorm(parent + '/' + x), b = vfsNorm(dest + '/' + x); for (const [k, v] of [...VFS.entries()]) if (k === a || k.startsWith(a + '/')) { VFS.delete(k); VFS.set(b + k.slice(a.length), v) } })
    return { ok: true, count: names.length, pairs: names.map((x) => [parent + '/' + x, dest + '/' + x]) }
  },
  ssh_cp: (_a: string, parent: string, names: string[], dest: string) => {
    names.forEach((x) => { const a = vfsNorm(parent + '/' + x), b = vfsNorm(dest + '/' + x); for (const [k, v] of [...VFS.entries()]) if (k === a || k.startsWith(a + '/')) VFS.set(b + k.slice(a.length), { ...v }) })
    return { ok: true, count: names.length, created: names.map((x) => dest + '/' + x) }
  },
  ssh_drag: async () => ({ ok: true }),
  ssh_clip_copy: async (_alias: string, items?: any[]) => ({ ok: true, count: items?.length || 0 }),
  ssh_upload: async (alias: string) => { ;(async () => { for (let k = 1; k <= 8; k++) { await sleep(250); emitLocal('ssh:progress', { kind: 'up', sent: k * 4e6, total: 32e6, speed: 16e6, file: 'demo.mp4' }) } emitLocal('ssh:done', { ok: true, kind: 'up', alias, count: 1, secs: 2 }) })(); return { ok: true } },
  ssh_download: async (alias: string, _items?: any) => { ;(async () => { for (let k = 1; k <= 8; k++) { await sleep(250); emitLocal('ssh:progress', { kind: 'down', sent: k * 4e6, total: 32e6, speed: 16e6, file: 'notes.txt' }) } emitLocal('ssh:done', { ok: true, kind: 'down', alias, count: 1, secs: 2, dest: 'C:\\Users\\demo\\Desktop' }) })(); return { ok: true } },
  share_info: () => S.share || { on: false },
  share_start: async (sec: number) => {
    S.share = { on: true, port: 41873, user: 'zuicat', password: 'k7Vn3hQe9TzXw2Ab', ips: ['192.168.1.103', '10.66.0.7'], public: { host: 'code.zuicat.cn', port: 41764, user: 'renyi' }, expires: sec ? Date.now() / 1000 + sec : 0, started: Date.now() / 1000, sessions: [], log: [{ t: Date.now() / 1000, text: '已开启，端口 41873' }] }
    setTimeout(() => emitLocal('share:state', S.share), 50)
    setTimeout(() => { if (S.share?.on) { S.share = { ...S.share, sessions: [{ sid: 1, ip: '127.0.0.1', who: 'renyi', since: Date.now() / 1000 }, { sid: 2, ip: '127.0.0.1', who: 'renyi', since: Date.now() / 1000 }] }; emitLocal('share:state', S.share) } }, 3000)
    return { ok: true, ...S.share }
  },
  share_stop: () => { S.share = { on: false }; setTimeout(() => emitLocal('share:state', S.share), 50); return true },
  share_kick: () => true,
  share_reset_password: () => { S.share = { ...S.share, password: Math.random().toString(36).slice(2, 10) + Math.random().toString(36).slice(2, 10), sessions: [] }; setTimeout(() => emitLocal('share:state', S.share), 50); return { ok: true, ...S.share } },
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
  open_vscode: async (_alias: string, _path?: string) => ({ ok: true }),
  update_check: () => true,
  set_titlebar: () => true,
  win_dim: () => true,
  account_status: () => (S.acct ? { bound: true, name: '任义', username: 'renyi', avatar: '' } : { bound: false }),
  account_login: () => { setTimeout(() => { S.acct = true; emitLocal('account:event', { state: 'ok', status: { bound: true, name: '任义', username: 'renyi', avatar: '' } }) }, 4000); return { ok: true, user_code: 'K7XM-4P9Q', url: 'https://code.zuicat.cn/toolbox-auth.html?code=K7XM-4P9Q' } },
  account_cancel: () => true,
  account_unbind: () => { S.acct = false; return { ok: true } },
}
setTimeout(() => emitLocal('remote:event', remoteState), 500)
