# Suioo Web

Windows 本地代理面板，提供 Suioo AnyConnect 接入、国内 / 海外域名分流、网站耗时展示和后台保活。使用用户态协议内核，无需 OpenConnect GUI。

## 首次使用

1. 在 Windows 10 / 11 x64 安装 Python 3.12 或更新版本，并勾选 **Add Python to PATH**。
2. 克隆仓库或下载 ZIP 并完整解压，然后双击 **`启动Suioo.cmd`**。支持中文及含空格的项目路径。
3. 首次启动会从 sing-box 官方 GitHub Release 下载固定版本的协议内核，核验 SHA-256 后解压到本地 `runtime/engine`。首次下载需要能访问 GitHub；后续启动复用本地内核。
4. 浏览器会自动进入“连接设置”。输入**你自己的 Suioo 接入账号和密码**，点击“验证账号并连接”。默认接入地址为 `https://node.anyconnect.cloud`，也可填写服务商提供的 HTTPS 接入地址。
5. 账号验证和连通性检查通过后，凭据才会以 Windows DPAPI 加密保存到本机 `data/connection.dpapi`。**以后在同一台电脑、同一项目目录启动时自动读取，无需重复输入。**

本仓库不含维护者或其他用户的 Suioo 账号、密码、DPAPI 文件、浏览器登录状态、Codex 登录信息或运行历史。下载仓库不会获得任何可直接使用的账号。

凭据不是明文写入 CMD、源码或 Git。`data/`、`runtime/`、`config.json` 和下载缓存均被 Git 忽略。请勿使用 `git add -f` 提交这些本机文件。删除本地凭据、换电脑、系统重装或重新解压到全新目录后，需要重新输入一次。

## 日常使用

- 双击 `启动Suioo.cmd`，打开本地面板；默认地址 `http://127.0.0.1:18789`。
- 默认 HTTP / HTTPS 代理入口：`http://127.0.0.1:18790`。
- 验证连接后可勾选“接入 Windows 浏览器及新终端”；已有开发终端不被重启。
- 腾讯、阿里、字节、百度、向日葵 / 贝锐的国内服务走直连，海外 / 国际服务走代理；GitHub 网站、API、源码、下载及其关联域固定代理。未知域名默认代理。
- 网站测速展示 DNS、TCP、TLS、首字节和总耗时，支持 CSV。HTTP 403 / 429 表示受限，不能当作网页正常。
- `Install-Service.cmd` 可选：以管理员权限安装开机服务和登录守护，使后台在重启后自动恢复。已保存的本机凭据会复用；安装不向 GitHub 上传凭据。
- `Restore-Network.cmd` 恢复本工具管理的 Windows 用户代理和新终端设置。

关闭网页不会关闭代理。保活和自动恢复不等于物理断网时请求也能永不中断。

## 开发与发布

```text
python -m unittest discover -s tests -v
python windows/Check-Publish.py
```

发布检查使用 Git 暂存区内容，拒绝凭据、运行目录、旧现场报告及未声明文件；在有本机凭据时，还会检查待提交内容是否含这些已保存的账号或密码。不要把本机完整开发压缩包或历史日志直接上传仓库。

`windows/Build-Package.py` 可生成不带账号和本机数据的使用包。GitHub 源码首次启动自动下载内核；已有使用包可直接复用随包提供的内核。

代理核心的来源、固定摘要和许可证见 [vendor/README.txt](vendor/README.txt) 和 [docs/第三方组件.txt](docs/第三方组件.txt)。域名规则来源及许可证保存在 `rules/`。
