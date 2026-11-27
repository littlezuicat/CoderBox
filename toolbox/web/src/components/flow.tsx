// “上面放文件 → 中间箭头 → 下面出结果”的版式：PPT 定图和格式转换共用。
// 输入的文件不会被自动清掉，可以反复改参数重新转（可以多个文件，一个接一个转）；输出的文件可以用鼠标拖出窗口保存，也可以点“打开文件位置”。
import AddRounded from '@mui/icons-material/AddRounded'
import ArrowDownwardRounded from '@mui/icons-material/ArrowDownwardRounded'
import CloseRounded from '@mui/icons-material/CloseRounded'
import CloudUploadOutlined from '@mui/icons-material/CloudUploadOutlined'
import DeleteOutline from '@mui/icons-material/DeleteOutline'
import FolderOpenOutlined from '@mui/icons-material/FolderOpenOutlined'
import MoveToInboxOutlined from '@mui/icons-material/MoveToInboxOutlined'
import { alpha, Box, Button, Chip, IconButton, LinearProgress, Tooltip, Typography, useTheme } from '@mui/material'
import { keyframes } from '@mui/material/styles'
import { useRef } from 'react'

import { api } from '../bridge'
import { StateChip, useDropHighlight } from './common'
import { EnhancedCard } from './enhanced-card'

export type FlowFile = { key: string; chip: string; color: string; name: string; meta?: string; state?: StateChip; progress?: number | null }

const ChipBox = ({ chip, color }: { chip: string; color: string }) => {
  const theme = useTheme()
  return <Box sx={{ width: 36, height: 36, borderRadius: 1.5, bgcolor: alpha((theme.palette as any)[color].main, 0.14), color: `${color}.main`, fontWeight: 800, fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>{chip}</Box>
}

/** 上面的输入区：空的时候是大大的拖放提示；放了文件就一条一条列出来（可以多个），下面留一条“继续添加”。 */
export function InputBox({ title, hint, files, disabled, onPick, onClear, onRemove }: { title: string; hint: string; files: FlowFile[]; disabled?: boolean; onPick: () => void; onClear: () => void; onRemove: (i: number) => void }) {
  const theme = useTheme()
  const dark = theme.palette.mode === 'dark'
  const box = useRef<HTMLElement | null>(null)
  const active = useDropHighlight(box, disabled)
  const empty = files.length === 0
  return (
    <Box ref={box} onClick={() => empty && !disabled && onPick()}
      sx={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', borderRadius: 2, border: '2px dashed', borderColor: alpha(theme.palette.primary.main, active ? 0.9 : 0.45),
        bgcolor: active ? alpha(theme.palette.primary.main, 0.1) : dark ? '#282a36' : '#ffffff', opacity: disabled ? 0.75 : 1, cursor: empty && !disabled ? 'pointer' : 'default', transition: 'background-color .15s, border-color .15s',
        ...(empty ? { alignItems: 'center', justifyContent: 'center', gap: 0.5, '&:hover': { bgcolor: alpha(theme.palette.primary.main, 0.06) } } : {}) }}>
      {empty ? <>
        <Box sx={{ width: 44, height: 44, borderRadius: 1.5, bgcolor: alpha(theme.palette.primary.main, 0.12), color: 'primary.main', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><CloudUploadOutlined /></Box>
        <Typography sx={{ fontWeight: 700, fontSize: 15 }}>{title}</Typography>
        <Typography variant="body2" color="text.secondary">{hint}</Typography>
      </> : <>
        <Box sx={{ px: 2, pt: 1.2, pb: 0.4, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Typography variant="body2" color="text.secondary">输入 · {files.length} 个文件</Typography>
          <Button size="small" color="inherit" disabled={disabled} startIcon={<DeleteOutline />} sx={{ fontWeight: 600 }} onClick={onClear}>清空</Button>
        </Box>
        <Box sx={{ flex: 1, minHeight: 0, overflowY: 'auto', px: 2 }}>
          {files.map((f, i) => (
            <Box key={f.key} sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 0.9, borderBottom: 1, borderColor: 'divider', '&:last-of-type': { borderBottom: 0 } }}>
              <ChipBox chip={f.chip} color={f.color} />
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography sx={{ fontWeight: 600, fontSize: 14 }} noWrap title={f.name}>{f.name}</Typography>
                {f.meta && <Typography variant="caption" color={f.state?.color === 'error' ? 'error' : 'text.secondary'} sx={{ display: 'block' }} noWrap>{f.meta}</Typography>}
                {f.progress != null && <LinearProgress variant="determinate" value={f.progress} sx={{ mt: 0.5, height: 5, borderRadius: 3 }} />}
              </Box>
              {f.state && <Chip size="small" label={f.state.label} color={f.state.color} variant={f.state.color === 'default' ? 'outlined' : 'filled'} sx={{ fontWeight: 700, borderRadius: 1.5 }} />}
              {!disabled && <IconButton size="small" onClick={() => onRemove(i)}><CloseRounded fontSize="small" /></IconButton>}
            </Box>
          ))}
        </Box>
        <Box onClick={() => !disabled && onPick()} sx={{ m: 1, py: 0.8, borderRadius: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.6, color: 'text.secondary', fontSize: 13, cursor: disabled ? 'default' : 'pointer', '&:hover': disabled ? {} : { bgcolor: alpha(theme.palette.primary.main, 0.07), color: 'primary.main' } }}>
          <AddRounded sx={{ fontSize: 18 }} />拖入或点击继续添加
        </Box>
      </>}
    </Box>
  )
}

const flow = keyframes`from { transform: translateY(-50%) } to { transform: translateY(0) }`
const ring = keyframes`0% { transform: scale(1); opacity: .55 } 100% { transform: scale(1.7); opacity: 0 }`

/** 中间的箭头：转换时箭头不停地往下流，外面一圈波纹；空闲时点它也能开始转换。 */
export function FlowArrow({ busy, canStart, onStart, text, percent }: { busy: boolean; canStart: boolean; onStart: () => void; text?: string; percent?: number | null }) {
  const theme = useTheme()
  const main = theme.palette.primary.main
  const click = !busy && canStart
  return (
    <Box sx={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', alignItems: 'center', py: 1, gap: 0.6, minHeight: 84 }}>
      <Tooltip title={click ? '开始转换' : ''} placement="right">
        <Box onClick={click ? onStart : undefined}
          sx={{ position: 'relative', width: 46, height: 46, borderRadius: '50%', bgcolor: !busy && !canStart ? 'action.disabledBackground' : alpha(main, busy ? 0.16 : 0.1), color: !busy && !canStart ? 'text.disabled' : 'primary.main', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'visible',
            cursor: click ? 'pointer' : 'default', transition: 'background-color .2s, transform .15s', '&:hover': click ? { bgcolor: alpha(main, 0.2), transform: 'translateY(1px)' } : {},
            '&::after': busy ? { content: '""', position: 'absolute', inset: 0, borderRadius: '50%', border: `2px solid ${alpha(main, 0.5)}`, animation: `${ring} 1.4s ease-out infinite`, pointerEvents: 'none' } : {} }}>
          <Box sx={{ width: 46, height: 46, borderRadius: '50%', overflow: 'hidden', position: 'relative' }}>
            {/* 两个箭头上下叠放，整体往下滑一个身位，循环起来就是箭头一直往下流 */}
            <Box sx={{ position: 'absolute', left: 0, top: 0, width: '100%', height: '200%', display: 'flex', flexDirection: 'column', transform: busy ? undefined : 'translateY(-50%)', animation: busy ? `${flow} .9s linear infinite` : 'none', willChange: busy ? 'transform' : 'auto' }}>
              {[0, 1].map((k) => <Box key={k} sx={{ height: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><ArrowDownwardRounded sx={{ fontSize: 26 }} /></Box>)}
            </Box>
          </Box>
        </Box>
      </Tooltip>
      <Typography variant="caption" color={busy ? 'primary' : 'text.secondary'} sx={{ minHeight: 18, userSelect: 'text', textAlign: 'center', maxWidth: '90%' }} noWrap>{text || ' '}</Typography>
      {busy && percent != null && <LinearProgress variant="determinate" value={percent} sx={{ width: 160, height: 4, borderRadius: 2, mt: -0.2 }} />}
    </Box>
  )
}

export type OutFile = { key: string; chip: string; color: string; name: string; meta?: string; state?: StateChip; progress?: number | null; path?: string }

function OutRow({ f }: { f: OutFile }) {
  const theme = useTheme()
  const down = useRef<{ x: number; y: number } | null>(null)
  const canDrag = !!f.path
  // 按住文件往窗口外拖：移动超过几个像素就交给后端发起系统拖放（HTML5 的拖放没法把文件交给资源管理器）
  const onDown = (e: React.MouseEvent) => {
    if (!canDrag || e.button !== 0) return
    down.current = { x: e.clientX, y: e.clientY }
    const move = (ev: MouseEvent) => {
      const d = down.current; if (!d) return
      if (Math.hypot(ev.clientX - d.x, ev.clientY - d.y) > 6) { cleanup(); api.start_drag([f.path]) }
    }
    const cleanup = () => { down.current = null; window.removeEventListener('mousemove', move, true); window.removeEventListener('mouseup', cleanup, true) }
    window.addEventListener('mousemove', move, true); window.addEventListener('mouseup', cleanup, true)
  }
  return (
    <Box onMouseDown={onDown} title={canDrag ? '按住拖到别处保存' : undefined}
      sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 1.1, borderBottom: 1, borderColor: 'divider', '&:last-of-type': { borderBottom: 0 }, userSelect: 'none', cursor: canDrag ? 'grab' : 'default',
        '&:hover': canDrag ? { bgcolor: alpha(theme.palette.primary.main, 0.05) } : {}, borderRadius: 1 }}>
      <ChipBox chip={f.chip} color={f.color} />
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography sx={{ fontWeight: 600, fontSize: 14 }} noWrap>{f.name}</Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }} noWrap>{f.meta}</Typography>
        {f.progress != null && <LinearProgress variant="determinate" value={f.progress} sx={{ mt: 0.5, height: 5, borderRadius: 3 }} />}
      </Box>
      {f.state && <Chip size="small" label={f.state.label} color={f.state.color} variant={f.state.color === 'default' ? 'outlined' : 'filled'} sx={{ fontWeight: 700, borderRadius: 1.5 }} />}
      {canDrag && <Tooltip title="打开文件位置"><IconButton size="small" onMouseDown={(e) => e.stopPropagation()} onClick={() => api.reveal(f.path)}><FolderOpenOutlined fontSize="small" /></IconButton></Tooltip>}
    </Box>
  )
}

/** 下面的输出区。 */
export function OutputBox({ files, hint, onClear, disabled }: { files: OutFile[]; hint?: string; onClear?: () => void; disabled?: boolean }) {
  return (
    <Box sx={{ flex: 1, minHeight: 0 }}>
      <EnhancedCard title="输出" icon={<MoveToInboxOutlined />} minHeight={120} action={files.length ? (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {files.some((f) => f.path) && <Typography variant="caption" color="text.secondary">按住文件可拖出去保存</Typography>}
          {onClear && <Tooltip title="只是清空这个列表，文件还在原处"><span><Button size="small" color="inherit" disabled={disabled} startIcon={<DeleteOutline />} sx={{ fontWeight: 600 }} onClick={onClear}>清空</Button></span></Tooltip>}
        </Box>) : null}>
        {files.length === 0
          ? <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', m: 'auto', py: 2, lineHeight: 1.8, userSelect: 'none' }}>{hint || '转换好的文件会出现在这里'}</Typography>
          : files.map((f) => <OutRow key={f.key} f={f} />)}
      </EnhancedCard>
    </Box>
  )
}
