# Suioo Web

Windows 本地代理面板，提供 Suioo AnyConnect 接入、国内 / 海外域名分流、网站耗时展示和后台保活。使用用户态协议内核，无需 OpenConnect GUI。

## 虚拟机与便携 Python

离线迁移后先校验包的 SHA256，不复制其他电脑的 DPAPI、账号或 Codex 登录缓存。Python 不在 PATH 时，可运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File windows/Start-Portable.ps1 -PythonExecutable C:\工具\python.exe -NoBrowser -NoIntegration
```

该入口只等待启动器退出，后台服务持续运行；避免外层用 `Start-Process -Wait` 等待整个服务进程树。`-NoIntegration` 保留已有 Windows 用户代理设置。正常桌面启动仍使用原来的 `启动Suioo.cmd`。

运行 `python -B diagnostics.py --codex --no-open` 可另查 Codex 安装、登录状态及 OpenAI 认证页、ChatGPT、API 的代理连通性。PATH 尚未刷新时也识别 Suioo 用户安装目录；不会登录、发送模型请求或导出账号及原始日志。

Google 204 或通道 ready 不代表 OpenAI 可用。登录页403/429与未带密钥的API401分别报告；401不是模型响应通过。当前会话的 CSTP `0xb0 Internal Error` 是服务端断开信号，不能靠清空认证掩盖，也不保证切换 TCP-only 就能解决。网络专项通过后，仍需目标用户完成 Codex 官方登录并做简单短答验证。

## 首次使用

1. 在 Windows 10 / 11 x64 安装 Python 3.12 或更新版本，并勾选 **Add Python to PATH**。
2. 克隆仓库或下载 ZIP 并完整解压，然后双击 **`启动Suioo.cmd`**。支持中文及含空格的项目路径。面板启动后自动安装 Codex 及配套 Code Mode Host 到当前用户目录并配置 PATH，无需管理员权限或 Node.js；离线迁移包已内置 Codex。
3. 首次启动会从 sing-box 官方 GitHub Release 下载固定版本的协议内核，核验 SHA-256 后解压到本地 `runtime/engine`。首次下载需要能访问 GitHub；后续启动复用本地内核。
4. 浏览器会自动进入“连接”页。输入**你自己的 Suioo 接入账号和密码**，点击“连接”。默认接入地址为 `https://node.anyconnect.cloud`，可在“更多设置”中修改。
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

迁移打包使用 `python windows/Build-Package.py --output-dir 干净迁移包 --include-engine --include-codex`，仅收集 `publish-files.json` 白名单内的项目文件，并附带通过固定 SHA-256 校验的 `vendor` 内核压缩包。省略 `--include-engine` 时，目标机首次启动需要访问 GitHub。Git 历史、账号、运行数据、验收证据和输出目录不会进入迁移 ZIP。使用 `python windows/Verify-Package.py 路径.zip` 检查清单和全部文件摘要。

目标机运行面板需 Python 3.12 或更新版本；仅运行 Codex 不需要 Python、Node.js 或 VS Code。完整解压后双击 `打开CMD.cmd`，输入 `codex` 即可启动；在项目目录直接运行 `codex` 也会自动安装。`启动Suioo.cmd` 和 `安装Codex.cmd` 同样会安装 Codex 并配置当前用户 PATH，之后从开始菜单新开的 CMD 可在任意目录运行 `codex`。已打开的 CMD 或 VS Code 保留旧环境，应关闭后重新打开，或使用 `打开CMD.cmd`。安装位置为 `%LOCALAPPDATA%/Suioo`，项目移动后全局命令仍可用。

面板先启动，再检查 Codex 组件；安装失败会单独提示并返回错误码，已启动的面板仍可用于检查连接。`安装Codex.cmd` 可独立重试。

离线包通过 `--include-codex` 同时附带 Codex 主程序与 Code Mode Host 的官方固定版本压缩包，安装前校验压缩包及可执行文件 SHA-256；源码未带压缩包时从官方 Release 下载。运行 `codex --version` 可检查安装；运行 `codex` 首次需自行登录。命令安装和启动不依赖 Suioo 连接成功，登录及模型请求需要可用网络。VS Code 单独安装；代理接入在面板中启用。迁移包不含 Codex 登录状态。

代理核心的来源、固定摘要和许可证见 [vendor/README.txt](vendor/README.txt) 和 [docs/第三方组件.txt](docs/第三方组件.txt)。域名规则来源及许可证保存在 `rules/`。

## 网络慢或打不开

- 双击 `一键诊断.cmd`，约一分钟后自动打开报告目录，将其中的 `诊断报告.zip` 发给排查人员。
- 双击 `一键修复.cmd`，先诊断，再根据结果重新接入浏览器或恢复本项目失效的代理；修改前在 `data/diagnostic-backups` 留存本机备份，并在操作后重新诊断。
- 报告对比国内直连、显式代理、Google 小请求、首页和图片，记录 DNS、TCP、TLS、首字节、总耗时及隧道状态。HTTP 403/429 不算正常访问；历史断线和当前状态分别记录。

可分享 ZIP 仅含脱敏报告，不包含账号、登录状态、原始配置、原始日志或本机备份。诊断会向报告中列出的百度、Google、gstatic 发出测试请求。不自动覆盖其他代理、PAC、DNS、防火墙或证书设置。优先复用本项目正在运行的 Python，并检查启动脚本支持的位置及 Python 安装注册表；找不到 Python 时自动使用 Windows 原生诊断，仍采集实际 HTTP 请求、DNS 和隧道状态。原生模式只诊断，扩展修复需要 Python 3.12 或更新版本。诊断命令不安装或更新 Codex。
