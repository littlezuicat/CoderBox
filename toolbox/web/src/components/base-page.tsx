// 取自 clash-verge-rev：components/base/base-page.tsx（去掉 Tauri 拖拽属性）
import { Box, Typography } from '@mui/material'
import { InfoTip } from './common'
import { useTheme } from '@mui/material/styles'
import React, { ReactNode } from 'react'

interface Props { info?: React.ReactNode; title?: React.ReactNode; header?: React.ReactNode; contentStyle?: React.CSSProperties; children?: ReactNode; full?: boolean }

export const BasePage: React.FC<Props> = ({ title, info, header, contentStyle, full, children }) => {
  const isDark = useTheme().palette.mode === 'dark'
  return (
    <div className="base-page">
      <header style={{ userSelect: 'none' }}>
        <Box sx={{ display: 'flex', alignItems: 'center' }}><Typography sx={{ fontSize: '20px', fontWeight: '700 ' }}>{title}</Typography>{info && <InfoTip text={info} />}</Box>
        {header}
      </header>
      <div className={full ? 'base-container no-padding' : 'base-container'} style={{ backgroundColor: isDark ? '#1e1f27' : '#ffffff' }}>
        <section style={{ backgroundColor: isDark ? '#1e1f27' : 'var(--background-color)' }}>
          <div className="base-content" style={contentStyle}>{children}</div>
        </section>
      </div>
    </div>
  )
}
