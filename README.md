# JiaYuan 课件知识库

JiaYuan 是一个本地优先的课程资料管理与 RAG 问答应用。它可以把 PDF、DOCX、PPTX、Markdown、本地 HTML 或网页正文导入课程资料库，在指定课程或指定文件范围内检索，并在回答下方给出可点击的引用来源。

项目同时提供浏览器开发模式和 Windows 桌面版。桌面版内置独立 Python 运行时、Tesseract OCR 与基础中文向量模型，不依赖系统 Python；Marker 和 MinerU 是可选视觉解析引擎，在设置页首次选择时按需安装及下载各自模型。

## 主要功能

- 多格式入库：PDF、DOCX、PPTX、Markdown、HTML 和公开网页 URL。
- 拖拽导入：可把多个文件拖入聊天输入区，按队列逐个解析，避免视觉引擎争抢显存。
- PDF 默认解析：PyMuPDF 提取文本；页面无有效文本时自动调用项目内置 Tesseract OCR 兜底。
- 高级视觉解析：可选 Marker 或 MinerU，并支持 CPU/GPU 初始化、下载进度、超时回收和真实解析探针。
- 入库状态机：`uploaded → parsing → indexing → ready / failed`，记录文档哈希、页数/单元数、引擎、耗时、切片数和错误信息。
- 去重与补偿：相同 SHA-256 的已索引文件可复用；失败时按 `file_id` 清除已写入向量，避免孤儿数据。
- 范围检索：支持按课程和可选文件列表过滤 Chroma 数据。
- 混合检索：向量候选、BM25、MMR 去重和可选 reranker 共同选择最终上下文，并带最低相关度门槛。依据不足时会明确提示资料库没有足够依据。
- 可追溯引用：切片保存章节、页码/幻灯片、序号和解析引擎；回答可跳转 PDF 页、打开 Office 文件、预览 Markdown/HTML 或访问原网页。
- 资料库模糊搜索：支持文件名、课程名、文档类型、状态、解析引擎和来源地址的组合搜索。
- 统一任务中心：集中显示资料解析、引擎初始化、RollCall 和备份任务，支持安全取消、失败重试及 App 重启后的中断恢复。
- 数据维护：提供 SQLite/源文件/向量库自检、完整 ZIP 备份、备份校验与下次启动恢复。

## Windows 桌面版

在 `release` 目录运行：

```text
JiaYuan-Setup-x64.exe
```

双击安装程序即可按当前 Windows 用户一键安装；无需预装 Python、Node.js 或后端依赖。安装完成后会自动创建桌面和开始菜单中的 `JiaYuan` 快捷方式，并启动应用。

首次启动会把私有运行时释放到当前 Windows 用户的数据目录，耗时通常比后续启动长；基础向量模型已经随安装包提供，并在首次入库或检索时离线按需加载，不再阻塞 App 窗口打开。桌面数据默认保存在：

```text
%LOCALAPPDATA%\JiaYuan\
├─ data\       # SQLite、上传文档、Chroma 向量库和引擎状态
├─ models\     # Marker、MinerU 与检索模型缓存
├─ runtime\    # 私有 Python 运行时
├─ logs\       # electron.log 与 backend.log
├─ backups\    # 数据中心创建或导入的完整 ZIP 备份
└─ profile\    # Electron 页面配置
```

卸载程序默认保留这个目录，以免误删知识库。若要彻底重置，请先退出 JiaYuan，再自行备份并删除 `%LOCALAPPDATA%\JiaYuan`。

桌面安装程序当前未配置商业代码签名证书，Windows 可能显示 SmartScreen 提示；请仅使用可信来源生成的安装包，并核对发布方提供的 SHA-256。

## Marker / MinerU 初始化

1. 打开“设置”，选择 Marker 或 MinerU。
2. 选择 CPU 或 GPU。GPU 模式要求 NVIDIA 显卡和可用驱动；程序会先执行 CUDA kernel 验证，再安装匹配的 PyTorch CUDA 12.8 组件。
3. 保持网络畅通。程序会在桌面私有运行时中安装 `marker-pdf[full]` 或 `mineru[pipeline]`，模型写入 `%LOCALAPPDATA%\JiaYuan\models`，不会污染项目源码目录。
4. 只有依赖安装、模型完整性检查和最小文档解析探针全部通过后，界面才会显示初始化成功。

Marker/MinerU 首次安装和模型下载体积较大，实际时间由网络、磁盘和显卡环境决定。日志长时间无变化时，先查看 `%LOCALAPPDATA%\JiaYuan\logs\backend.log`；初始化接口会定期输出心跳，并在超时后回收子进程。

## 本地开发

推荐环境：

- Windows 10/11 x64
- Python 3.10–3.13
- Node.js `^22.18.0` 或 `>=24.12.0`

安装依赖：

```powershell
.\install_backend.bat
cd frontend
npm install
```

启动前后端开发服务：

```powershell
.\start.bat
```

也可以分别运行：

```powershell
cd backend
python main.py

cd frontend
npm run dev
```

开发模式的数据库、上传文件、向量库和引擎缓存位于 `backend` 下，均已加入 `.gitignore`。不要把真实账号、`config.json`、数据库、上传资料或模型缓存提交到版本库。

## 构建 Windows 安装包

```powershell
cd desktop
npm install
npm run build:runtime
npm run pack:win
```

`build:runtime` 会下载官方 Windows 嵌入式 Python，安装 `backend/requirements.txt`，下载基础中文向量模型并做离线导入验证，然后生成桌面运行时归档。`pack:win` 会先构建 Vue 前端，再通过 electron-builder 生成 NSIS x64 安装程序。

如运行时依赖或 Python 版本发生变化，应重新执行 `npm run build:runtime`。仅修改前端或普通后端源码时，可复用现有运行时归档。

常用验证命令：

```powershell
cd frontend
npm run build

cd ..\desktop
npm test
npm run pack:dir

cd ..
python -m unittest discover -s backend\tests
```

## 数据与安全边界

- 本仓库的初始化版本不包含测试数据库、个人账号、上传文档、Chroma 数据、Marker/MinerU 模型或它们的成功标记。
- 账号配置和知识库仅保存在本机。当前应用没有为 SQLite 中的账号字段提供额外应用层加密，请保护 Windows 登录账号和用户数据目录。
- 完整备份包含资料库和校园账号数据，可能含敏感凭证；请勿把备份 ZIP 上传到不可信位置。
- 上传接口校验扩展名、MIME、文件签名、压缩包展开体积与压缩比；单文件上限为 100 MiB。
- 网页导入仅接受 HTTP/HTTPS HTML，限制响应体和重定向，并拒绝本机、局域网及链路本地地址，以降低 SSRF 风险。
- DOCX 没有稳定原生页码，引用以章节定位；PPTX 按幻灯片定位；PDF 按页定位。
- 当前网页导入适合服务端可直接获取正文的公开静态页面，不支持需要登录或必须运行 JavaScript 才能渲染的页面。

## 故障排查

- 桌面版启动失败：查看 `%LOCALAPPDATA%\JiaYuan\logs\electron.log` 和 `backend.log`。
- 首次入库或检索：会在后台首次装载本地向量运行时，后续操作直接复用；该过程不会访问 Hugging Face 网络。
- Marker/MinerU 初始化失败：确认网络、可用磁盘空间和 NVIDIA 驱动；删除对应失败缓存前请先备份，不要手工创建初始化成功标记。
- 资料入库失败：在资料库查看失败状态和错误信息，修复环境后使用“重新索引”。
- 检索无依据：先确认文件状态为“就绪”，并检查当前选择的课程和文件范围是否包含目标资料。

## 备份说明

本次初始化前的完整工程备份保存在开发机的 `.backups` 目录，该目录不会被打进桌面应用，也不会提交到 Git。备份可能含原数据库、账号配置和上传文档，应按敏感文件管理。

桌面封装采用 Electron 的隔离渲染配置与独立用户数据目录；运行时归档通过 electron-builder 的 `extraResources` 随应用发布。相关实现可参考 [Electron BrowserWindow](https://www.electronjs.org/docs/latest/api/browser-window)、[Electron app 数据目录](https://www.electronjs.org/docs/latest/api/app)、[electron-builder 文件内容配置](https://www.electron.build/docs/contents/) 和 [NSIS 安装器配置](https://www.electron.build/docs/nsis/)。
