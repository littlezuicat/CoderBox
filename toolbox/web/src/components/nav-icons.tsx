// 侧栏图标：渐变圆角方块 + 白色线条图形，五个功能各一种颜色。
import { Box } from '@mui/material'

const COLORS: Record<string, [string, string]> = {
  ppt: ['#FFB347', '#FF6B35'],
  convert: ['#5AB0FF', '#2F6DF6'],
  share: ['#3DDC97', '#16A34A'],
  remote: ['#B794F6', '#7C3AED'],
  online: ['#3CD3C4', '#0E91C9'],
}

const GLYPH: Record<string, React.ReactNode> = {
  // 幻灯片：屏幕 + 山和太阳 + 底座
  ppt: (<>
    <rect x="3.5" y="4.5" width="17" height="11.5" rx="2.4" />
    <path d="M6.5 13.2l3.4-3.6 2.6 2.7 2-1.9 3 2.8" />
    <circle cx="15.8" cy="8.3" r="1.1" fill="currentColor" stroke="none" />
    <path d="M12 16v3.3M8.5 19.5h7" />
  </>),
  // 转换：上下两条反向箭头
  convert: (<>
    <path d="M5 8.2h13.2m0 0l-3-3m3 3l-3 3" />
    <path d="M19 15.8H5.8m0 0l3-3m-3 3l3 3" />
  </>),
  // 快传：纸飞机
  share: (<>
    <path d="M20.6 3.6L3.4 10.4l6.2 2.4 2.4 6.2z" />
    <path d="M9.6 12.8l4.4-4.4" />
  </>),
  // 远程：终端窗口
  remote: (<>
    <rect x="3.5" y="4.5" width="17" height="15" rx="3" />
    <path d="M7.5 10l3 2.3-3 2.3" />
    <path d="M13 15h3.8" />
  </>),
  // SSH 管理：两层服务器
  ssh: (<>
    <rect x="3.5" y="4" width="17" height="6.5" rx="2.2" />
    <rect x="3.5" y="13.5" width="17" height="6.5" rx="2.2" />
    <path d="M7.2 7.25h.01M7.2 16.75h.01M11 7.25h5.8M11 16.75h5.8" />
  </>),
  // 设备安全：盾牌 + 对勾
  security: (<>
    <path d="M12 3.4l7 2.6v5.4c0 4.4-2.9 7.7-7 9.2-4.1-1.5-7-4.8-7-9.2V6z" />
    <path d="M8.9 12.1l2.2 2.2 4.1-4.3" />
  </>),
  // 密码：钥匙
  vault: (<>
    <circle cx="8.2" cy="12" r="3.6" />
    <path d="M11.8 12H20.4M17.4 12v3M20.4 12v2.2" />
  </>),
  // 设置：三条滑杆
  settings: (<>
    <path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h11M19 17h1" />
    <circle cx="15" cy="7" r="2" />
    <circle cx="9" cy="12" r="2" />
    <circle cx="17" cy="17" r="2" />
  </>),
  // 在线：地球
  online: (<>
    <circle cx="12" cy="12" r="8.4" />
    <path d="M3.6 12h16.8" />
    <path d="M12 3.6c2.6 2.4 3.8 5.2 3.8 8.4s-1.2 6-3.8 8.4c-2.6-2.4-3.8-5.2-3.8-8.4S9.4 6 12 3.6z" />
  </>),
}

export function NavIcon({ k, size = 24 }: { k: string; size?: number }) {
  // 和 Clash Verge 一样的单色线条图标：跟随文字颜色，不带底色
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" style={{ display: 'block' }}>{GLYPH[k]}</svg>
  )
}
