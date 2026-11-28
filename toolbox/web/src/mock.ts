// 浏览器里没有 Python 时的模拟后端：只为了开发和截图，行为尽量贴近真实接口。
import { emitLocal } from './bridge'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const mockExpItems = () => {
  const n = Math.floor(Date.now() / 1000)
  const mk = (o: any) => ({ user: 'zhang', cwd: '/data/zhang/dehaze', cmd: 'python train.py', launcher: '', gpus: [0], mem: 18000, pid: 1234, end: null, status: 'running', frac: null, label: '', stage: '训练中', eta_ts: null, eta_src: null, last_line: '', metrics: {}, log: '/data/x.log', error: '', updated: n - 20, ...o })
  return [
    mk({ id: 'e1', note: '在 RESIDE 数据集上训练 NAFNet 单图像去雾网络', alias: 'msh3', name: 'NAFNet-dehaze', gpus: [0, 1], cmd: 'python basicsr/train.py -opt options/train/NAFNet-dehaze.yml --launcher none', start: n - 3600 * 17, frac: 0.404, label: 'iter 121,200 / 300,000（epoch 12）', eta_ts: n + 3600 * 25, eta_src: 'log', metrics: { psnr: '31.42', ssim: '0.9712', loss: '1.2e-02' } }),
    mk({ id: 'e3', note: '在 OTS 室外去雾数据集上训练 ConvIR 去雾网络', alias: 'msh3', user: 'wang', name: 'ConvIR_ots', gpus: [2], start: n - 600, frac: 0.0123, label: 'iter 1,230 / 100,000', eta_ts: n + 3600 * 9, eta_src: 'elapsed', stage: '验证 / 测试中' }),
    mk({ id: 'e2', note: '训练 DehazeFormer-B 去雾模型，处理真实有雾图像', alias: 'msh4', user: 'li', name: 'dehazeformer-b · train', gpus: [0], start: n - 3600 * 5, frac: 0.2335, label: 'epoch 47 / 200（本轮 68%）', eta_ts: n + 3600 * 15 + 1200, eta_src: 'rate' }),
    mk({ id: 'e4', note: '自定义网络的图像复原实验，暂未识别数据集', alias: 'shang', user: 'chen', name: 'my_new_net', gpus: [], start: n - 7200, frac: null, label: 'epoch 3 · iter 2,000（总数没识别到）', last_line: '<epoch:  3, iter:   2,000, lr:2.000e-04> G_loss: 1.234e-02' }),
    mk({ id: 'e5', note: '在 ITS 室内去雾数据集上训练 FFA-Net 去雾网络', alias: 'msh2', name: 'FFA-Net_its', gpu_model: 'NVIDIA GeForce RTX 4090', gpus: [1], start: n - 86400 * 2, end: n - 3600 * 6, status: 'done', frac: 1, label: 'iter 500,000 / 500,000', stage: '已完成', metrics: { psnr: '36.39', ssim: '0.9886' } }),
    mk({ id: 'e6', note: '用 Restormer 在去雾数据集上训练图像复原网络', alias: '622', name: 'restormer_haze', gpu_model: 'NVIDIA GeForce RTX 2080 Ti', gpus: [0], start: n - 86400, end: n - 3600 * 14, status: 'failed', frac: 0.31, label: 'iter 93,000 / 300,000', stage: '出错退出', error: 'RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB' }),
    mk({ id: 'e7', note: '测试 AECR-Net 对比学习去雾网络的效果', alias: 'worker', name: 'AECR-Net · test', gpu_model: 'NVIDIA GeForce RTX 2060', gpus: [0], start: n - 86400 * 3, end: n - 86400 * 3 + 5400, status: 'stopped', frac: 0.07, label: 'epoch 14 / 200', stage: '已结束（中途退出）' }),
  ]
}
const mockExpHosts = () => {
  const t = Math.floor(Date.now() / 1000)
  const g = (name: string, vals: number[][]) => vals.map((v, i) => ({ index: i, name, util: v[0], mem_used: v[1], mem_total: 24564 }))
  return {
    msh3: { t, gpus: g('NVIDIA GeForce RTX 4090', [[98, 21200], [97, 21100], [91, 18400], [0, 12]]) },
    msh4: { t, gpus: g('NVIDIA GeForce RTX 4090', [[55, 16000], [0, 10]]) },
    shang: { t, gpus: g('NVIDIA RTX A5000', [[63, 9800]]) },
    jiajun: { t, gpus: g('NVIDIA GeForce RTX 5090', [[0, 8]]) },
    msh2: { t, gpus: g('NVIDIA GeForce RTX 4090', [[0, 8], [0, 8]]) },
  }
}
const mockExp = () => ({ items: S.exp || (S.exp = mockExpItems()), hosts: mockExpHosts(), last_poll: Math.floor(Date.now() / 1000) - 12, busy: false, enabled: true, ai: { mode: S.expAi || 'haiku', ok: null, error: '', kind: '' } })

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
  ;[['pics/架构图.png', 120000], ['pics/photo.jpg', 340000], ['report.xlsx', 18000], ['paper.pdf', 2300000]].forEach(([n, z]) => VFS.set('/home/demo/projects/llm-train/' + n, { dir: false, size: z as number, mtime: 1762300000 }))
  d('/home/demo/projects/llm-train/pics')
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
  paperdl_health: async () => ({ ok: true, jobs: 3, pending: 0, s2_key: true }),
  paperdl_search: async (t: string) => ({ ok: true, items: [
    { title: 'DEA-Net: Single Image Dehazing Based on Detail-Enhanced Convolution', year: 2023, venue: 'IEEE Transactions on Image Processing', citations: 960, doi: '10.1109/TIP.2024.3354108', provider: 'ieee', is_oa: false },
    { title: 'Wavelet-based diffusion transformer for image dehazing', year: 2026, venue: 'Pattern Recognition Letters', citations: 2, doi: '10.1016/j.patrec.2026.01.016', provider: 'elsevier', is_oa: false },
    { title: 'A comprehensive survey on image dehazing for different scenes', year: 2023, venue: 'Multimedia Tools and Applications', citations: 41, doi: '10.1007/s11042-023-17292-8', provider: 'springer', is_oa: false },
  ] }),
  paperdl_submit: async (doi: string, title?: string) => ({ ok: true, job_id: 'mock-' + Date.now(), doi, provider: doi.includes('10.1109') ? 'ieee' : doi.includes('10.1016') ? 'elsevier' : 'springer' }),
  paperdl_status: async (id: string) => ({ ok: true, id, status: 'running', bytes: null }),
  paperdl_download: async (id: string) => ({ ok: true, path: 'C:////Users////zuicat////AppData////Roaming////MajingToolbox////papers////' + id + '.pdf' }),
  paperdl_open_folder: async () => ({ ok: true, path: 'papers' }),
  paperdl_open_file: async (p: string) => ({ ok: true, path: p }),
  lit_get: async () => ({ cfg: S.lit || { base_url: 'https://api.deepseek.com', model: 'deepseek-flash', target: 'zh', auto_swap: true, domain: '', hotkey_on: false, hotkey: 'F1', stay: 10 }, has_key: !!S.litKey, hotkey_error: '', langs: [['zh', '中文（简体）'], ['zh-Hant', '中文（繁体）'], ['en', '英语'], ['ja', '日语'], ['ko', '韩语'], ['fr', '法语'], ['de', '德语']] }),
  lit_set: async (d: any) => { const { api_key, ...rest } = d || {}; if (api_key !== undefined) S.litKey = api_key; S.lit = { ...(await mock.lit_get()).cfg, ...rest }; return mock.lit_get() },
  lit_warmup: async () => true,
  lit_test: async () => { await sleep(500); return S.litKey ? { ok: true, ms: 312, text: '你好' } : { ok: false, error: '还没填接口地址和密钥，先到“文献”页的设置里填一下。' } },
  lit_copy: async () => true,
  lit_cancel: async () => true,
  lit_translate: async (id: number, text: string) => {
    ;(async () => {
      await sleep(250)
      if (!S.litKey) { emitLocal('lit:error', { id, message: '还没填接口地址和密钥，先到“文献”页的设置里填一下。' }); return }
      const full = '【模拟译文】' + text
      for (let i = 0; i < full.length; i += 3) { emitLocal('lit:delta', { id, text: full.slice(i, i + 3) }); await sleep(40) }
      emitLocal('lit:done', { id, full, cached: false })
    })()
    return true
  },
  // 实验记录的示例数据（浏览器里调界面用）
  exp_state: () => mockExp(),
  exp_subscribe: async (id: string, on: boolean) => { const it = (S.exp || (S.exp = mockExpItems())).find((x: any) => x.id === id); if (it) it.sub = on; emitLocal('exp:update', mockExp()); return { ok: true, sub: on } },
  exp_ai_set: (m: string) => { S.expAi = m; emitLocal('exp:update', mockExp()); return { ok: true } },
  exp_refresh: () => { setTimeout(() => emitLocal('exp:update', mockExp()), 600); return { ok: true } },
  exp_remove: (id: string) => { S.exp = (S.exp || mockExpItems()).filter((x: any) => x.id !== id); emitLocal('exp:update', mockExp()); return { ok: true } },
  exp_clear_finished: () => { S.exp = (S.exp || mockExpItems()).filter((x: any) => x.status === 'running'); emitLocal('exp:update', mockExp()); return { ok: true } },
  exp_log: async () => ({ ok: true, path: '/data/exp/NAFNet-dehaze/train_NAFNet-dehaze_20261127_231500.log', text: Array.from({ length: 40 }, (_, i) => `2026-11-28 10:${String(i).padStart(2, '0')}:00,123 INFO: [Dehaz..][epoch: 12, iter: ${(121000 + i * 100).toLocaleString()}, lr:(2.000e-04,)] [eta: 1 day, 2:13:45, time (data): 0.412 (0.003)] l_pix: 1.2345e-02`).join('\n') }),
  ssh_sysinfo: async (_a: string) => ({ ok: true, family: 'linux', name: 'Ubuntu 22.04.4 LTS', arch: 'x86_64', container: true, gpus: 2, cloudPath: '/home/demo/projects', cpu: { model: 'AMD EPYC 7763 64-Core Processor', cores: 128, usage: 23 }, mem: { total: 268435456000, used: 98000000000 }, disks: [{ kind: 'system', mount: '/', total: 214748364800, used: 70000000000, nominal: true }, { kind: 'mount', mount: '/data0', total: 210000000000, used: 200000000 }, { kind: 'cloud', mount: '/cloud', total: 1073741824000, used: 457000000000 }] }),
  ssh_read_file: async (_a: string, path: string) => {
    await sleep(150)
    const f = VFS.get(vfsNorm(path))
    if (!f) return { ok: false, error: '文件不存在。' }
    if (f.dir) return { ok: false, error: '这是文件夹。' }
    if (f.text === undefined) return { ok: false, error: '看起来是二进制文件，不能当文本打开。' }
    return { ok: true, text: f.text, encoding: 'utf-8', size: f.text.length, mtime: f.mtime || 0 }
  },
  // 预览用：按扩展名现生成一份字节（PNG 用画布画、PDF 手写最小文件、表格临时用 xlsx 库生成）
  ssh_read_bytes: async (_a: string, path: string) => {
    await sleep(200)
    const p = vfsNorm(path), ext = p.split('.').pop()!.toLowerCase()
    const f = VFS.get(p)
    if (!f) return { ok: false, error: '文件不存在。' }
    const enc = (u: Uint8Array) => { let t = ''; for (let i = 0; i < u.length; i++) t += String.fromCharCode(u[i]); return btoa(t) }
    if (ext === 'png' || ext === 'jpg') {
      const c = document.createElement('canvas'); c.width = 640; c.height = 360
      const g = c.getContext('2d')!; const gr = g.createLinearGradient(0, 0, 640, 360); gr.addColorStop(0, '#4f8cff'); gr.addColorStop(1, '#ff7ac8'); g.fillStyle = gr; g.fillRect(0, 0, 640, 360)
      g.fillStyle = '#fff'; g.font = '48px sans-serif'; g.fillText('预览 ' + p.split('/').pop(), 40, 190)
      return { ok: true, b64: c.toDataURL(ext === 'png' ? 'image/png' : 'image/jpeg').split(',')[1], size: 1, mtime: 0 }
    }
    if (ext === 'xlsx') {
      const X = await import('xlsx')
      const wb = X.utils.book_new()
      X.utils.book_append_sheet(wb, X.utils.aoa_to_sheet([['模型', '参数量', 'Loss', '日期'], ['base', 1.3e9, 0.912, new Date(2026, 10, 1)], ['large', 7e9, 0.731, new Date(2026, 10, 8)], ['xl', 13e9, 0.655, new Date(2026, 10, 15)]], { cellDates: true }), '实验结果')
      X.utils.book_append_sheet(wb, X.utils.aoa_to_sheet([['step', 'lr'], [0, 0.0003], [100, 0.00029]]), '学习率')
      return { ok: true, b64: X.write(wb, { type: 'base64', bookType: 'xlsx' }), size: 1, mtime: 0 }
    }
    if (ext === 'pdf') {
      const NP = 5, objs: string[] = ['<</Type/Catalog/Pages 2 0 R>>', '<</Type/Pages/Kids[' + Array.from({ length: NP }, (_, i) => (3 + i * 2) + ' 0 R').join(' ') + ']/Count ' + NP + '>>']
      for (let i = 0; i < NP; i++) {
        const t = 'BT /F1 24 Tf 40 200 Td (Page ' + (i + 1) + ' Hello PDF) Tj 0 -40 Td (search me ' + (i + 1) + ') Tj ET'
        objs.push('<</Type/Page/Parent 2 0 R/MediaBox[0 0 400 300]/Contents ' + (4 + i * 2) + ' 0 R/Resources<</Font<</F1 ' + (3 + NP * 2) + ' 0 R>>>>>>')
        objs.push('<</Length ' + t.length + '>>stream' + String.fromCharCode(10) + t + String.fromCharCode(10) + 'endstream')
      }
      objs.push('<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>')
      const pdf = '%PDF-1.4' + String.fromCharCode(10) + objs.map((o, i) => (i + 1) + ' 0 obj' + o + 'endobj').join(String.fromCharCode(10)) + String.fromCharCode(10) + 'trailer<</Root 1 0 R/Size ' + (objs.length + 1) + '>>' + String.fromCharCode(10) + '%%EOF'
      return { ok: true, b64: btoa(pdf), size: pdf.length, mtime: 0 }
    }
    return { ok: true, b64: enc(new TextEncoder().encode(f.text || '')), size: 1, mtime: 0 }
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
  ssh_mv_paths: (_a: string, pairs: any[]) => { pairs.forEach(([x, y]: string[]) => { const a = vfsNorm(x), b = vfsNorm(y); for (const [k, v] of [...VFS.entries()]) if (k === a || k.startsWith(a + '/')) { VFS.delete(k); VFS.set(b + k.slice(a.length), v) } }); return { ok: true, count: pairs.length, pairs } },
  ssh_restore: (_a: string, pairs: any[]) => ({ ok: true, count: pairs.length }),
  ssh_rm_paths: (_a: string, p: any[]) => { p.forEach((x: string) => vfsDel(vfsNorm(x))); return { ok: true, count: p.length } },
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
  open_vscode: async (alias: string, _path?: string) => {
    ;(async () => {
      for (const [pct, text] of [[0, '正在检查环境…'], [30, '正在下载 Windows 服务端（x64）…'], [70, '正在上传到主机…'], [100, '环境没问题，正在打开 VS Code…']] as [number, string][]) { emitLocal('vsc:progress', { alias, step: 'x', pct, text }); await sleep(700) }
      emitLocal('vsc:open', { alias, ok: true })
    })()
    return { ok: true, pending: true }
  },
  update_check: () => true,
  set_titlebar: () => true,
  win_dim: () => true,
  account_status: () => (S.acct ? { bound: true, name: '任义', username: 'renyi', avatar: '' } : { bound: false }),
  account_login: () => { setTimeout(() => { S.acct = true; emitLocal('account:event', { state: 'ok', status: { bound: true, name: '任义', username: 'renyi', avatar: '' } }) }, 4000); return { ok: true, user_code: 'K7XM-4P9Q', url: 'https://code.zuicat.cn/toolbox-auth.html?code=K7XM-4P9Q' } },
  account_cancel: () => true,
  account_detail: () => ({ ok: true, username: 'renyi', name: '任义', avatar: '', bio: '', email: S.mail ? 're****yi@qq.com' : '', has_email: !!S.mail, email_verified: !!S.mailOk }),
  account_set_username: async (n: string) => ({ ok: true, username: n }),
  account_set_bio: async (b: string) => ({ ok: true, bio: b }),
  account_avatar_pick: async () => ({ ok: true }),
  account_email_send: async () => { S.mail = true; return { ok: true, expires_in: 300 } },
  account_email_verify: async (c: string) => (c === '123456' ? (S.mailOk = true, { ok: true }) : { ok: false, error: '验证码错误，还可尝试 4 次。' }),
  account_unbind: () => { S.acct = false; return { ok: true } },
}
setTimeout(() => emitLocal('remote:event', remoteState), 500)
