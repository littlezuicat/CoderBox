// 通用小件：拖放区、文件行、分段选择、设置行。样式沿用 Clash Verge 的 MUI 主题。
import CloudUploadOutlined from '@mui/icons-material/CloudUploadOutlined'
import CloseRounded from '@mui/icons-material/CloseRounded'
import InfoRounded from '@mui/icons-material/InfoRounded'
import { alpha, Box, Button, ButtonGroup, Chip, IconButton, LinearProgress, Tooltip, Typography, useTheme } from '@mui/material'
import { useEffect, useRef, useState } from 'react'

/** 文件拖到 box 上时返回 true（高亮用），拖离/放下/离开窗口就变回 false。 */
export function useDropHighlight(box: React.MutableRefObject<HTMLElement | null>, disabled?: boolean) {
  const [active, setActive] = useState(false)
  const timer = useRef<any>(null)
  // 文件拖到框上时高亮，拖离就熄。pywebview 在 document 上拦了拖放事件，页面元素自己的 onDragOver 收不到，所以挂在 window 的捕获阶段。
  // 判断“在不在框里”用三种办法任一成立：事件目标元素在框内 / 鼠标坐标在框内 / 坐标按屏幕缩放比例还原后在框内
  // （高分屏上外部拖放事件的坐标有时是物理像素）。拖动过程中 dragover 不断触发，350ms 没有新事件就当离开了窗口。
  useEffect(() => {
    const hasFiles = (e: DragEvent) => { const t = Array.from(e.dataTransfer?.types || []); return t.length === 0 || t.includes('Files') }
    const inRect = (r: DOMRect, x: number, y: number) => x >= r.left && x <= r.right && y >= r.top && y <= r.bottom
    const inside = (e: DragEvent) => {
      const el = box.current; if (!el) return false
      if (e.target instanceof Node && el.contains(e.target)) return true
      const r = el.getBoundingClientRect(), k = window.devicePixelRatio || 1
      return inRect(r, e.clientX, e.clientY) || (k !== 1 && inRect(r, e.clientX / k, e.clientY / k))
    }
    const over = (e: DragEvent) => {
      if (disabled || !hasFiles(e)) return
      setActive(inside(e)); clearTimeout(timer.current); timer.current = setTimeout(() => setActive(false), 350)
    }
    const off = () => { clearTimeout(timer.current); setActive(false) }
    window.addEventListener('dragenter', over, true); window.addEventListener('dragover', over, true)
    window.addEventListener('drop', off, true); window.addEventListener('dragend', off, true)
    return () => { clearTimeout(timer.current); window.removeEventListener('dragenter', over, true); window.removeEventListener('dragover', over, true); window.removeEventListener('drop', off, true); window.removeEventListener('dragend', off, true) }
  }, [disabled])
  return active
}

export function DropZone({ title, hint, onPick, disabled }: { title: string; hint: string; onPick: () => void; disabled?: boolean }) {
  const theme = useTheme()
  const dark = theme.palette.mode === 'dark'
  const box = useRef<HTMLElement | null>(null)
  const active = useDropHighlight(box, disabled)
  return (
    <Box ref={box}
      onClick={() => !disabled && onPick()}
      sx={{ borderRadius: 2, border: '2px dashed', borderColor: alpha(theme.palette.primary.main, active ? 0.9 : 0.45), bgcolor: active ? alpha(theme.palette.primary.main, 0.1) : dark ? '#282a36' : '#ffffff',
        height: 150, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 0.5, cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.6 : 1,
        '&:hover': { bgcolor: alpha(theme.palette.primary.main, 0.06) } }}>
      <Box sx={{ width: 44, height: 44, borderRadius: 1.5, bgcolor: alpha(theme.palette.primary.main, 0.12), color: 'primary.main', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <CloudUploadOutlined />
      </Box>
      <Typography sx={{ fontWeight: 700, fontSize: 15 }}>{title}</Typography>
      <Typography variant="body2" color="text.secondary">{hint}</Typography>
    </Box>
  )
}

export type StateChip = { label: string; color: 'default' | 'primary' | 'success' | 'error' | 'warning' }

export function FileRow({ chip, color, name, meta, state, progress, onRemove, onOpen }: { chip: string; color: string; name: string; meta?: string; state?: StateChip; progress?: number | null; onRemove?: () => void; onOpen?: () => void }) {
  const theme = useTheme()
  return (
    <Box onClick={onOpen} sx={{ cursor: onOpen ? 'pointer' : 'default', display: 'flex', alignItems: 'center', gap: 1.5, py: 1.2, borderBottom: 1, borderColor: 'divider', '&:last-child': { borderBottom: 0 } }}>
      <Box sx={{ width: 40, height: 40, borderRadius: 1.5, bgcolor: alpha((theme.palette as any)[color].main, 0.14), color: `${color}.main`, fontWeight: 800, fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>{chip}</Box>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography sx={{ fontWeight: 600, fontSize: 14 }} noWrap title={name}>{name}</Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', userSelect: 'text' }}>{meta}</Typography>
        {progress != null && <LinearProgress variant="determinate" value={progress} sx={{ mt: 0.6, height: 5, borderRadius: 3 }} />}
      </Box>
      {state && <Chip size="small" label={state.label} color={state.color} variant={state.color === 'default' ? 'outlined' : 'filled'} sx={{ fontWeight: 700, borderRadius: 1.5 }} />}
      {onRemove && <IconButton size="small" onClick={(e) => { e.stopPropagation(); onRemove() }}><CloseRounded fontSize="small" /></IconButton>}
    </Box>
  )
}

/** Clash Verge 的按钮组：描边小按钮，选中的是实心主色。 */
export function Segment({ value, options, onChange, disabled, fullWidth }: { value: number; options: string[]; onChange: (i: number) => void; disabled?: boolean; fullWidth?: boolean }) {
  return (
    <ButtonGroup size="small" disabled={disabled} fullWidth={fullWidth} sx={{ '& .MuiButton-root': { textTransform: 'none', fontWeight: 600, px: 2, minWidth: 56 } }}>
      {options.map((o, i) => <Button key={o} variant={i === value ? 'contained' : 'outlined'} disableElevation onClick={() => onChange(i)}>{o}</Button>)}
    </ButtonGroup>
  )
}

export function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', py: 0.6 }}><Typography>{label}</Typography>{children}</Box>
}

/** 说明文字收进二级：灰色小圆“!”，悬停才显示。只给确实需要解释的地方加。 */
export function InfoTip({ text }: { text: React.ReactNode }) {
  return (
    <Tooltip placement="bottom-start" enterDelay={120} title={<span style={{ fontSize: 12.5, lineHeight: 1.6 }}>{text}</span>} slotProps={{ tooltip: { sx: { maxWidth: 340, borderRadius: 2, px: 1.5, py: 1 } } }}>
      <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', ml: 0.6, p: '2px', borderRadius: '50%', flexShrink: 0, cursor: 'pointer', color: 'text.disabled', transition: 'box-shadow .15s, color .15s', verticalAlign: 'middle',
        '&:hover': { color: 'text.secondary', boxShadow: (t) => `0 0 0 4px ${t.palette.mode === 'dark' ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.08)'}` } }}>
        <InfoRounded sx={{ fontSize: 17 }} />
      </Box>
    </Tooltip>
  )
}

export const pageGrid = { display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'minmax(0, 1fr) 320px' }, gap: 1.5, alignItems: 'start' }
export const rounded = { borderRadius: 2, fontWeight: 700 }
