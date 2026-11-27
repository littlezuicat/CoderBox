import ArrowOutwardRounded from '@mui/icons-material/ArrowOutwardRounded'
import ChevronRightRounded from '@mui/icons-material/ChevronRightRounded'
import CodeRounded from '@mui/icons-material/CodeRounded'
import OndemandVideoRounded from '@mui/icons-material/OndemandVideoRounded'
import QrCode2Rounded from '@mui/icons-material/QrCode2Rounded'
import SendOutlined from '@mui/icons-material/SendOutlined'
import SlideshowOutlined from '@mui/icons-material/SlideshowOutlined'
import SwapHorizOutlined from '@mui/icons-material/SwapHorizOutlined'
import { alpha, Box, Typography, useTheme } from '@mui/material'
import { useState } from 'react'

import { api } from '../bridge'
import { BasePage } from '../components/base-page'
import LiteraturePage, { LiteratureIcon } from './literature'

const LINKS: [string, string, string, string, React.ReactNode, string][] = [
  ['聚合收款码', 'www.zuicat.cn/agg', '把微信、支付宝等多个收款码合成一个二维码，生成可打印的底牌。', 'https://www.zuicat.cn/agg/', <QrCode2Rounded />, 'primary'],
  ['视频下载器', 'peanutdl.com', 'B站、抖音视频下载（第三方站点 PeanutDL）。', 'https://peanutdl.com/zh/tools', <OndemandVideoRounded />, 'error'],
  ['CoderLand 码境', 'code.zuicat.cn', '面向 C、C++、Python 与 Java 学习者的编程闯关练习平台。', 'https://code.zuicat.cn/', <CodeRounded />, 'success'],
  ['网页版 PPT 转图片', 'www.zuicat.cn/ppt', '没装 Office 的电脑用这个：上传后由服务器排版出图。', 'https://www.zuicat.cn/ppt/', <SlideshowOutlined />, 'warning'],
  ['网页版格式转换', 'www.zuicat.cn/converter', '手机上或者别人的电脑上临时转个格式。', 'https://www.zuicat.cn/converter/', <SwapHorizOutlined />, 'info'],
  ['网页版文件快传', 'www.zuicat.cn/file', '手机和电脑之间互传，凭取件码下载。', 'https://www.zuicat.cn/file/', <SendOutlined />, 'secondary'],
]

// 文献翻译暂时关闭（不接入发布）：恢复时改成 true，并把 py/majing/core/litrans.py 的 ENABLED 也改成 True
const LIT_ENABLED = false

export default function OnlinePage() {
  const theme = useTheme()
  const dark = theme.palette.mode === 'dark'
  const [view, setView] = useState<'list' | 'lit'>('list')
  const cardSx = { display: 'flex', gap: 1.5, p: 2, borderRadius: 2, cursor: 'pointer', bgcolor: dark ? '#282a36' : '#ffffff', '&:hover': { bgcolor: alpha(theme.palette.primary.main, 0.07) } }
  if (LIT_ENABLED && view === 'lit') return <BasePage title="文献翻译"><LiteraturePage onBack={() => setView('list')} /></BasePage>
  return (
    <BasePage title="在线工具">
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 1.5 }}>
        {LIT_ENABLED && <Box onClick={() => setView('lit')} sx={cardSx}>
          <Box sx={{ width: 44, height: 44, borderRadius: 1.5, flexShrink: 0, bgcolor: alpha(theme.palette.primary.main, 0.12), color: 'primary.main', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><LiteratureIcon /></Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography sx={{ fontWeight: 700, fontSize: 15 }}>文献</Typography>
            <Typography variant="caption" color="text.secondary">工具箱自带 · 在线翻译</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>读文献用：输入即译，或在任何程序里划词按热键，译文弹在鼠标旁边。用你自己的翻译接口。</Typography>
          </Box>
          <ChevronRightRounded fontSize="small" sx={{ color: 'text.secondary' }} />
        </Box>}
        {LINKS.map(([t, h, d, url, icon, color]) => (
          <Box key={t} onClick={() => api.open_url(url)} sx={{ display: 'flex', gap: 1.5, p: 2, borderRadius: 2, cursor: 'pointer', bgcolor: dark ? '#282a36' : '#ffffff', '&:hover': { bgcolor: alpha(theme.palette.primary.main, 0.07) } }}>
            <Box sx={{ width: 44, height: 44, borderRadius: 1.5, flexShrink: 0, bgcolor: alpha((theme.palette as any)[color].main, 0.12), color: `${color}.main`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{icon}</Box>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography sx={{ fontWeight: 700, fontSize: 15 }}>{t}</Typography>
              <Typography variant="caption" color="text.secondary">{h}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{d}</Typography>
            </Box>
            <ArrowOutwardRounded fontSize="small" sx={{ color: 'text.secondary' }} />
          </Box>
        ))}
      </Box>
    </BasePage>
  )
}
