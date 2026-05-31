# yt-dlp Web 管理器

一个简洁的本地视频/音频下载管理工具。

## 功能特点

- 支持 YouTube、Bilibili 等主流视频网站
- 多种格式选择：最佳视频、仅音频、最佳视频+音频
- 下载队列管理
- 实时进度显示
- 下载历史记录
- Web 图形界面

## 快速开始

### 1. 安装工具

运行安装脚本下载 yt-dlp 和 FFmpeg：

```powershell
.\install-tools.ps1
```

或者手动下载：
- [yt-dlp.exe](https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe) → 放入 `tools/` 目录
- [FFmpeg](https://github.com/BtbN/FFmpeg-Builds/releases) → 解压后放入 `tools/` 目录

### 2. 启动服务

```powershell
pip install -r requirements.txt
python server.py
```

### 3. 使用

浏览器打开 http://localhost:8080

## 项目结构

```
yt-dlp-manager/
├── index.html          # Web界面
├── server.py           # Python服务器
├── install-tools.ps1   # 工具安装脚本
├── requirements.txt    # Python依赖
├── tools/              # 工具目录 (yt-dlp.exe, ffmpeg.exe)
├── downloads/          # 下载目录
├── logs/               # 日志目录
└── data.json           # 任务数据
```

## 技术栈

- 后端: Python HTTP Server
- 前端: 纯 HTML/CSS/JS
- 下载核心: yt-dlp + FFmpeg