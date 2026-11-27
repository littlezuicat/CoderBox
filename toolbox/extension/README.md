# 码境密码 · 浏览器扩展（Chrome / Edge，Manifest V3）

用码境工具箱的本机密码库自动填充登录。扩展本身不存任何密码，只在填充的那一刻向工具箱取。

## 结构
```
manifest.json   固定了 key → 扩展 ID 永远是 fckanncbkfgihdooginknddjhgkigjnd（原生主机的 allowed_origins 靠它）
background.js   service worker：和原生主机（py\nmhost.py）收发 JSON；暂存“要不要保存”的登录（storage.session，内存里，2 分钟过期）
content.js      网页里的脚本：找登录框、小钥匙+菜单（closed shadow DOM）、填充、登录提交后弹“保存/更新”条
popup.html/js   工具栏弹窗：当前网站匹配的账号、搜索全部（选不匹配的会二次确认）
```
链路：网页 → content.js → background.js → `connectNative` → `nmhost.py`（stdio，4 字节长度+JSON）→ `majing\core\nmlogic.py` → 保险库 vault.dat。

## 安全规则（改动时别破坏）
- 网址匹配在**原生主机**里做（`nmlogic.url_match`），不信扩展/网页自己报的；只比主机名，子域可以、`example.com.evil.com`/`evil-example.com` 不行，IP/localhost 要完全相同。
- http（非本机）页面默认不返回、不填充；只有用户在弹窗里搜索后明确确认才用 `force`，而且只有扩展自己的弹窗页面能带 force（background 校验 sender）。
- 页面脚本拿不到密码：background 取到后让 content 直接写进输入框；匹配列表里不含密码。
- 协议里请求编号 `id` 和条目 id 不能同名（条目字段叫 `item`）——已经因此踩过两次坑；主机回包把 `id` 放最后。
- 原生主机只认来源 `chrome-extension://<我们的 ID>/`，注册表在 HKCU（`majing\core\nmreg.py`）。

## 界面与自动填充（content.js）
- 点/聚焦用户名框或密码框 → 弹账号菜单（Chrome 同款：窄白卡片、钥匙图标 + 用户名 + 下面一行和**真实密码等长的圆点**，悬停浅灰）；在用户名框里打字会过滤；↑↓/Enter/Esc 可用。
- **悬停/键盘选中即预填**：用户名预填进输入框、密码框放等长占位圆点（淡蓝底、不触发页面事件），移开/关闭就还原；点击才真正取密码填入。密码只在点击那一刻从主机取，匹配列表里只有长度 `plen`。
- **打开页面自动填充**（弹窗里可关，默认开）：只在顶层页面；登录框必须真正可见、没被遮、不透明、没移出屏幕（`trusted()`）；只有一个匹配账号、或这个网站上次选过某个账号才填；框里已有别的内容不动；`autocomplete=new-password` 不填。
- 登录框可能一开始就在页面里只是隐藏（单页应用）：监听 class/style/hidden/open 属性变化，而不只是增删节点。
- **模态 `<dialog>`（showModal，浏览器顶层）会盖住挂在页面根上的东西**：界面容器要挂进登录框所在的那个 `<dialog open>`（页面可能同时开着好几个，按输入框所属的选），并用容器自己的实际位置换算坐标（`origin()`）。code.zuicat.cn 的登录框就是这种，之前菜单看不见、点不了。
- 测试脚本里别用 `document.elementFromPoint` 判断是否被盖住（看不穿封闭 shadow），用 CDP `DOM.getNodeForLocation`。
- 冷启动：浏览器刚开后第一次请求要等原生主机进程（python）起来，约 1–3 秒；测试里要轮询等待，不要固定 sleep。

## 安装 / 调试
工具箱“密码”页 → “浏览器扩展”：先点“安装”（写注册表+启动脚本），再在浏览器 `chrome://extensions` 开开发者模式 → 加载已解压的扩展程序 → 选本文件夹。
当前启动脚本指向 `.venv` 的 python（源码运行）。**打包版还没做**：工具箱 exe 无控制台，没有 stdio，要另做一个控制台的小 exe 当主机。

新版 Chrome（137+）禁用了 `--load-extension`，自动化测试用 `--enable-unsafe-extension-debugging` 启动后，经 CDP 调 `Extensions.loadUnpacked`。
