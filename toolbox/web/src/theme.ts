// 取自 clash-verge-rev（GPL-3.0）：pages/_theme.tsx 与 pages/_layout/hooks/use-custom-theme.ts，去掉了 Tauri 相关部分
import { alpha, createTheme, Shadows } from '@mui/material'

export const defaultTheme = {
  primary_color: '#007AFF', secondary_color: '#FC9B76', primary_text: '#000000', secondary_text: '#3C3C4399',
  info_color: '#007AFF', error_color: '#FF3B30', warning_color: '#FF9500', success_color: '#06943D', background_color: '#ECECEC',
  font_family: `-apple-system, BlinkMacSystemFont,"Microsoft YaHei UI", "Microsoft YaHei", Roboto, "Helvetica Neue", Arial, sans-serif`,
}
export const defaultDarkTheme = {
  ...defaultTheme, primary_color: '#0A84FF', secondary_color: '#FF9F0A', primary_text: '#FFFFFF', background_color: '#2E303D',
  secondary_text: '#EBEBF599', info_color: '#0A84FF', error_color: '#FF453A', warning_color: '#FF9F0A', success_color: '#30D158',
}

export function buildTheme(mode: 'light' | 'dark') {
  const dt = mode === 'light' ? defaultTheme : defaultDarkTheme
  const muiTheme = createTheme({
    breakpoints: { values: { xs: 0, sm: 650, md: 900, lg: 1200, xl: 1536 } },
    palette: {
      mode,
      primary: { main: dt.primary_color }, secondary: { main: dt.secondary_color }, info: { main: dt.info_color },
      error: { main: dt.error_color }, warning: { main: dt.warning_color }, success: { main: dt.success_color },
      text: { primary: dt.primary_text, secondary: dt.secondary_text },
      background: { paper: mode === 'light' ? '#F5F5F5' : '#282A36', default: dt.background_color },
    },
    shadows: Array(25).fill('none') as Shadows,
    typography: { fontFamily: dt.font_family, fontSize: 13 },
  })
  const root = document.documentElement
  root.style.setProperty('--divider-color', mode === 'light' ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.06)')
  root.style.setProperty('--background-color', dt.background_color)
  root.style.setProperty('--selection-color', mode === 'light' ? '#f5f5f5' : '#3E3E3E')
  root.style.setProperty('--scroller-color', mode === 'light' ? '#90939980' : '#555555')
  root.style.setProperty('--primary-main', muiTheme.palette.primary.main)
  root.style.setProperty('--background-color-alpha', alpha(muiTheme.palette.primary.main, 0.1))
  let el = document.querySelector('style#verge-theme')
  if (!el) { el = document.createElement('style'); el.id = 'verge-theme'; document.head.appendChild(el) }
  el.innerHTML = `
    body { font-family: ${dt.font_family}; background-color: var(--background-color); }
    .MuiPaper-root { border-color: ${mode === 'light' ? '#cccccc' : '#1E1E1E'} !important; }
    .MuiBackdrop-root { transition: none !important; }      /* 弹窗遮罩不做淡入淡出：顶栏里原生的那一块是一步压暗的，网页遮罩渐变的话两边会有 0.2 秒对不上（先白后灰） */
    /* 右键菜单、下拉菜单这类弹出层：和底下的面板拉开——更亮的底色 + 细边 + 阴影（上面全局关了 box-shadow，所以用 filter 画阴影） */
    .MuiPopover-paper { background-color: ${mode === 'light' ? '#ffffff' : '#373a50'} !important; border: 1px solid ${mode === 'light' ? 'rgba(0,0,0,0.12)' : 'rgba(255,255,255,0.14)'} !important; filter: drop-shadow(0 6px 16px rgba(0,0,0,${mode === 'light' ? '0.2' : '0.5'})); }
    .MuiDialog-paper { background-color: ${mode === 'light' ? '#ffffff' : '#2E303D'} !important; }
    * { outline: none !important; box-shadow: none !important; }`
  return muiTheme
}
