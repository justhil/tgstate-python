# PicGo 配置指南

本文档将指导你如何配置 PicGo，以便将文件上传到由 `tgState` 驱动的服务。

## 核心配置

1.  **Uploader**: 选择 `Web Uploader`。
2.  **URL**: 填写你的服务提供的上传地址。通常是 `http://<你的服务器IP>:8000/api/upload`。
3.  **Method**: `POST`。
4.  **File Parameter Name**: `file`。
5.  **JSON Path**: `url`。

## 安全性：API 密钥（可选但推荐）

为了保护你的上传接口不被滥用，我们增加了可选的 API 密钥验证。

### 1. 在服务端设置密钥

在你的 `.env` 文件中，添加或修改以下行：

```env
# [可选] PicGo 上传接口的 API 密钥。如果留空，则无需密钥。
PICGO_API_KEY=your_secret_picgo_api_key
```

将 `your_secret_picgo_api_key` 替换为你自己的强密码。设置后，请重启服务。

### 2. 在 PicGo 中配置密钥

在 PicGo 的 `Web Uploader` 设置中，找到 **Body** 部分，并添加一个新的参数：

-   **Key**: `key`
-   **Value**: `your_secret_picgo_api_key` (与你在 `.env` 文件中设置的值完全相同)

这个设置将 API 密钥作为请求体的一部分发送，而不是通过请求头。

配置完成后，点击“确定”保存。现在你的 PicGo 上传将包含此密钥，从而通过服务器验证。