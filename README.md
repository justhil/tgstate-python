# tgState V2 - Python 版

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)[![Framework](https://img.shields.io/badge/Framework-FastAPI-green.svg)](https://fastapi.tiangolo.com/)[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)

`tgState` 原项目链接[csznet/tgState](https://github.com/csznet/tgState)，使用fastapi重构增加前端网盘页面管理文件，增加前端图床页面方便复制。

## 功能特性

*   **无限存储**: 利用 Telegram 的云服务作为您的私人文件仓库。
*   **永久图床**：只要服务还在运行，图床永不失效。
*   **现代化 UI**: 一个简洁、响应式且用户友好的网页界面，用于上传和管理文件。
*   **轻松部署**: 只需几分钟即可使用 Docker 完成部署，或在本地直接运行。
*   **直接链接**: 为每个上传的文件生成一个可直接分享的链接。
*   **大文件支持**: 自动处理大文件分块上传。
*   **密码保护**: 可选的密码保护机制，确保您的 Web 界面安全。

##  快速开始

推荐使用 Docker 来部署 `tgState`，这是最简单快捷的方式。

### 使用 Docker 部署

```bash
docker run -d \
  --name tgstate \
  -p 8000:8000 \
  -e BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11" \
  -e CHANNEL_NAME="@my_test_channel" \
  -e PASS_WORD="supersecret" \
  -e BASE_URL="https://my-service.com" \
  -e PICGO_API_KEY="supersecret(可选不需要就删除这行)" \
  mitu233/python-tgstate:latest
```


3. **访问应用**: 在浏览器中打开 `http://localhost:8000` 即可开始使用。

### 本地开发与运行

如果您希望在本地环境直接运行 `tgState`：

1. **克隆项目并进入目录**:

   ```bash
   git clone https://github.com/your-repo/python-tgstate.git
   cd python-tgstate
   ```

2. **创建并激活虚拟环境**:

   ```bash
   # 创建虚拟环境
   python -m venv venv
   # 激活虚拟环境 (Windows)
   venv\Scripts\activate
   # 激活虚拟环境 (Linux/macOS)
   # source venv/bin/activate
   ```

3. **安装依赖**:

   ```bash
   pip install -r requirements.txt
   ```

4. **创建 `.env` 配置文件**: 参照 Docker 部分的说明，在项目根目录创建并配置 `.env` 文件。

5. **启动应用**:

   ```bash
   uvicorn app.main:app --reload
   ```

   如果没有配置域名应用将在 `http://127.0.0.1:8000` 上运行。

##  配置 (环境变量)

`tgState` 通过环境变量进行配置，应用会从根目录的 `.env` 文件中自动加载这些变量。

| 变量            | 描述                                                         | 是否必须 | 默认值                  |
| --------------- | ------------------------------------------------------------ | -------- | ----------------------- |
| `BOT_TOKEN`     | 您的 Telegram Bot API 令牌。可以从 [@BotFather](https://t.me/BotFather) 获取。 | **是**   | `None`                  |
| `CHANNEL_NAME`  | 用于文件存储的目标聊天/频道。可以是公共频道的 `@username` 。 | **是**   | `None`                  |
| `PASS_WORD`     | 用于保护 Web 界面访问的密码。如果留空，则应用将公开访问，无需密码。 | 否       | `None`                  |
| `BASE_URL`      | 您的服务的公共 URL。用于生成完整的下载链接。                 | 否       | `http://127.0.0.1:8000` |
| `PICGO_API_KEY` | 用于 PicGo 上传接口的 API 密钥。                             | 否       | `None`                  |

## 注意密码相关

1. **两个密码都【没有】设置**：
   - **处理方式**：完全开放。
   - **结果**：无论是通过 Picogo/API 还是网页，**均可直接上传**，无需任何凭证。
2. **只设置了【Picogo密码】**：
   - **结果**：来自网页的上传请求会无条件允许。来自 Picogo/API 的请求会验证后允许。
3. **只设置了【登录密码】**：
   - **结果**：来自网页的上传只有**已登录**的网页用户能上传。来自 Picogo/API 的请求会无条件允许。

##  使用方法

1. **访问 Web 界面**: 启动应用后，在浏览器中访问 `http://127.0.0.1:8000` (或您配置的 `BASE_URL`)。

2. **密码验证**: 如果您在 `.env` 文件中设置了 `PASS_WORD`，应用会首先跳转到密码输入页面。输入正确密码后即可访问主界面。

3. **上传文件**: 在主界面，点击上传区域选择文件，或直接将文件拖拽到上传框中。上传成功后，文件会出现在下方的文件列表中。

4. **获取链接**: 文件列表中的每个文件都会显示其文件名、大小和上传日期。点击文件名即可复制该文件的直接下载链接。

   ## PicGo 配置指南

   ### 前置要求

   1. 安装插件web-uploader

   ### 核心配置

   1.  **图床配置名**: 随便
   2.  **api地址**: 填写你的服务提供的上传地址。本地是 `http://<你的服务器IP>:8000/api/upload`。
   3.  **POST参数名**: `file`。
   4.  **JSON 参数名**: `url`。
   5.  **自定义body**：{"key":"PICGO_API_KEY"}（可选推荐）

   用 roocode 和 白嫖的心 制作。