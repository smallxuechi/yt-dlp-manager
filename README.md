# yt-dlp Web 管理器

一个简洁的本地视频/音频下载管理工具，支持 YouTube、B站、Twitter 等 1000+ 网站。

## 功能特点

- 支持 YouTube、Bilibili 等主流视频网站
- 多种格式选择：最佳视频、仅音频、最高画质+音频
- 并发分片加速下载（默认 8 线程）
- 代理支持，国内/国外网站自动识别
- 下载队列管理 + 实时进度显示
- 下载历史记录 + 文件管理
- 纯 Web 界面，无需安装客户端

## 快速开始（新电脑）

### 第一步：克隆项目

```powershell
git clone https://github.com/smallxuechi/yt-dlp-manager.git
cd yt-dlp-manager
```

### 第二步：安装工具

运行安装脚本，自动下载 yt-dlp 和 FFmpeg：

```powershell
.\install-tools.ps1
```

或手动下载后放入 `tools/` 目录：
- [yt-dlp.exe](https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe)
- [FFmpeg](https://github.com/BtbN/FFmpeg-Builds/releases)（取 `ffmpeg.exe` 和 `ffprobe.exe`）

### 第三步：安装 Python 依赖

```powershell
pip install -r requirements.txt
```

### 第四步：启动

双击 `启动.bat`，浏览器会自动打开 http://localhost:8080

---

## 同步更新（已有项目时）

在原电脑推送新改动：

```powershell
git add .
git commit -m "feat: 描述改动内容"
git push
```

在另一台电脑拉取最新版本：

```powershell
git pull
```

---

## 项目结构

```
yt-dlp-manager/
├── index.html          # Web 界面
├── server.py           # Python 服务器
├── 启动.bat            # 一键启动脚本
├── install-tools.ps1   # 工具安装脚本
├── requirements.txt    # Python 依赖
├── tools/              # 工具目录（需自行下载，不含在仓库中）
│   ├── yt-dlp.exe
│   ├── ffmpeg.exe
│   └── cookies.txt     # 可选，用于 YouTube 登录
├── downloads/          # 下载目录（自动创建）
└── logs/               # 日志目录（自动创建）
```

> `tools/`、`downloads/`、`logs/`、`data.json`、`settings.json` 已加入 `.gitignore`，
> 不会上传到 GitHub，每台电脑独立维护。

## 技术栈

- 后端：Python 标准库 HTTP Server（无需额外框架）
- 前端：纯 HTML / CSS / JavaScript
- 下载核心：yt-dlp + FFmpeg