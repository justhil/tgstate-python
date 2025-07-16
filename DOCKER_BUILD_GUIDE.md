# GitHub Actions 构建与运行 Docker 镜像指南 (Python版) 🚀

你好呀！(≧∇≦)ﾉ

收到你的反馈啦！你说得对，我应该把 Python 项目的环境变量考虑进去。这次的指南会更详细，不仅包括如何用 GitHub Actions **构建**镜像，还包括如何**运行**这个需要环境变量的容器。

这份指南分为两大部分：
1.  **自动构建镜像**: 设置 GitHub Actions，在代码推送到 `main` 分支时自动构建 Docker 镜像并推送到 Docker Hub。
2.  **运行容器**: 如何使用 `docker run` 命令，并传入必要的环境变量来启动你的应用。

---

## Part 1: 使用 GitHub Actions 自动构建镜像

这一部分的目标是自动化镜像的构建和推送过程。

### 步骤 1.1: 准备工作

请确保你已经准备好：
1.  **一个 GitHub 仓库**: 你的项目代码需要托管在 GitHub 上。
2.  **一个 Docker Hub 账户**: 我们将把构建好的镜像推送到这里。

### 步骤 1.2: 在 GitHub 中设置 Secrets

为了让 GitHub Actions 能够登录到你的 Docker Hub 账户，你需要安全地存储你的凭据。

1.  打开你的 GitHub 项目仓库页面。
2.  点击 **Settings** > **Secrets and variables** > **Actions**。
3.  点击 **New repository secret** 按钮，添加以下两个 secret：
    *   **`DOCKERHUB_USERNAME`**: 你的 Docker Hub 用户名。
    *   **`DOCKERHUB_TOKEN`**: 你的 Docker Hub Access Token。
        *   **如何生成 Access Token**: 登录 Docker Hub -> Account Settings -> Security -> New Access Token。记得生成后立即复制，它只会出现一次！

### 步骤 1.3: 创建 GitHub Actions Workflow 文件

现在，我们来创建工作流文件。

1.  在你的项目根目录下，创建一个名为 `.github/workflows` 的文件夹（如果它还不存在的话）。
2.  在该文件夹中，创建一个名为 `docker-image.yml` 的新文件。
3.  将以下内容复制并粘贴到 `docker-image.yml` 文件中：

```yaml
name: Build and Push Docker Image

# 当有代码推送到 main 分支时触发
on:
  push:
    branches: [ "main" ]

jobs:
  build-and-push:
    # 使用最新的 ubuntu 系统作为运行环境
    runs-on: ubuntu-latest

    steps:
      # 第一步：检出你的代码
      - name: Checkout repository
        uses: actions/checkout@v4

      # 第二步：登录到 Docker Hub
      - name: Log in to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      # 第三步：构建并推送 Docker 镜像
      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          # 将镜像推送到 Docker Hub
          push: true
          # 为镜像打上标签
          # 请将下面的 'your-dockerhub-username' 替换为你的 Docker Hub 用户名
          tags: ${{ secrets.DOCKERHUB_USERNAME }}/python-tgstate:latest,${{ secrets.DOCKERHUB_USERNAME }}/python-tgstate:${{ github.sha }}
```

**重要提示**: 请务必将上面 `tags` 部分的 `your-dockerhub-username` 替换成你自己的 Docker Hub 用户名！

### 步骤 1.4: 提交并推送代码

将新创建的 `.github/workflows/docker-image.yml` 文件提交到你的 Git 仓库并推送到 GitHub。

```bash
git add .github/workflows/docker-image.yml
git commit -m "feat: Add GitHub Action to build and push Docker image"
git push origin main
```

推送后，你就可以在 GitHub 仓库的 **Actions** 标签页下看到工作流开始运行了。

---

## Part 2: 运行已构建的 Docker 容器

你的应用需要一些环境变量才能正常工作。`Dockerfile` 本身不包含这些敏感信息，这是正确的做法。我们应该在运行容器时把它们传进去。

### 步骤 2.1: 准备 `.env` 文件

1.  从 `.env.example` 复制一份新文件，并命名为 `.env`。
    ```bash
    cp .env.example .env
    ```
2.  打开 `.env` 文件，填入你自己的真实配置值。例如：
    ```ini
    # 你的 Telegram Bot 的 API Token。从 @BotFather 获取。
    BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
    
    # 文件存储的目标，可以是公开频道的 @username 或你自己的用户 ID。
    CHANNEL_NAME=@my_test_channel
    
    # [可选] 访问 Web 界面的密码。如果留空，则无需密码。
    PASS_WORD=supersecret
    
    # [可选] PicGo 上传接口的 API 密钥。如果留空，则无需密钥。
    PICGO_API_KEY=picgo_secret_key
    
    # [可选] 你的服务的公开访问 URL，用于生成完整的文件下载链接。
    BASE_URL=https://my-service.com
    ```
    **注意**: `.env` 文件包含了敏感信息，请确保已将其添加到 `.gitignore` 文件中，**绝对不要**提交到 Git 仓库！

### 步骤 2.2: 使用 `docker run` 启动容器

现在，你可以使用 `docker run` 命令来启动你刚刚构建并推送到 Docker Hub 的镜像了。

假设你的 Docker Hub 用户名是 `rooroo`，你可以这样运行：

```bash
docker run -d \
  --name my-telegram-app \
  -p 8000:8000 \
  --env-file ./.env \
  rooroo/python-tgstate:latest
```

命令解释：
*   `-d`: 在后台运行容器。
*   `--name my-telegram-app`: 给容器起一个好记的名字。
*   `-p 8000:8000`: 将容器的 8000 端口映射到主机的 8000 端口。
*   `--env-file ./.env`: **(关键步骤)** 从 `.env` 文件中读取所有环境变量并注入到容器中。
*   `rooroo/python-tgstate:latest`: 你要运行的镜像。记得替换 `rooroo` 为你的用户名。

## 完成！✨

现在，你的应用应该已经在 Docker 容器中成功运行起来了！

这份更新后的指南应该更符合你的项目需求了。如果还有任何问题，随时都可以再问我哦~ (o´ω`o)ﾉ