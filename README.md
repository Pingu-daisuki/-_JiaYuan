# 厦大_JiaYuan 

写在最前面：
  本项目是我学完python后基于兴趣激发做的，不仅希望可以作为课设项目，更希望能够在日常中自己使用
  该项目是我的小学期课设项目 也是我的第一个项目 希望能帮到大家

JiaYuan 是一个面向课程学习场景的本地优先桌面应用。它把学习仪表盘、课程资料库、RAG 问答、可验证引用、Deadline、RollCall、OJ 和 TronClass 辅助集中在同一个工作台中，让资料整理、检索、复习和校园学习工具不再分散在多个页面。

项目同时提供浏览器开发模式和 Windows 桌面版。桌面版基于 Electron，内置独立 Python 运行时、Tesseract OCR 与基础中文向量模型，不依赖系统 Python；Marker 和 MinerU 是可选视觉解析引擎，可在设置页首次启用时按需安装依赖和模型。

## 主要功能

### 学习仪表盘

- 集中显示今天和未来 7 天的 Deadline。
- 查看正在处理、失败和待重试的文档与后台任务。
- 快速进入最近使用的课程资料和最近对话。
- 汇总待复习知识点与 RollCall 监控状态。
- 显示资料库健康状态、可检索文件数量、磁盘占用和剩余空间。

### XMU_RAG 对话工作区

- 自动保存对话，关闭 App 后可继续上次研究过程。
- 对话可绑定课程，并为每个对话独立保存“全部资料 / 指定课程 / 指定文件”检索范围。
- 支持新建、重命名、搜索、固定和删除对话。
- 支持固定回答、删除单条消息和重新生成回答。
- 支持导出 Markdown；Windows 桌面版还可导出 PDF。
- 回答支持 Markdown、代码高亮和 LaTeX 公式渲染。
- 依据不足时明确提示当前资料范围没有足够证据，并提供调整检索范围的入口。

### 可验证引用

- 回答下方展示引用文件、章节、页码或幻灯片位置及相关度。
- 点击引用后在右侧打开原文预览，并自动高亮与问题相关的内容。
- 同时展示引用位置前后的相邻切片，方便核对上下文。
- 区分模型总结与知识库原文，避免把生成内容误认为原始事实。
- 展示同一课程下的相关资料，并可打开原始文件或定位到 PDF 页。
- PDF 按页定位，PPTX 按幻灯片定位，DOCX、Markdown 和 HTML 按章节或内容片段定位。

### XMU_Library 本地图书馆

- 使用树形目录整理课程与资料，支持任意层级的子文件夹。
- 可在根目录或任意子目录下继续创建文件夹。
- 支持文件夹重命名、安全删除以及文件跨层级移动。
- 删除文件夹时，其直属文件和子文件夹会安全移回根目录，避免误删资料。
- 支持文件名、课程名、文档类型、状态、解析引擎和来源地址的模糊搜索。
- 文件移动后会同步更新向量元数据，保证按课程检索时不会命中旧目录。
- 删除资料时同步清理原文件、数据库记录和对应向量切片。

### 文档导入与索引

- 支持 PDF、DOCX、PPTX、Markdown、HTML 和公开网页 URL。
- 支持拖拽多个文件、拖入整个文件夹或从导入窗口选择文件夹。
- 导入整个文件夹时自动保留原有目录层级，并可统一选择目标目录。
- 导入前计算 SHA-256，识别完全重复文件和同名历史版本。
- 导入前粗略预估 PDF 页数、处理时间和磁盘占用。
- 多文件按队列逐个处理，避免 Marker、MinerU 等视觉引擎争抢显存。
- 导入队列会暂存在本机；App 意外关闭后，未完成项目可恢复为等待状态。
- 失败文件可单独重试，整批完成后可发送桌面通知。
- 支持监控本地文件夹，每 15 秒检查文件变化，并自动重新导入和索引。该功能依赖浏览器或 Electron 的文件系统访问能力。
- 单个文件最大 100 MiB；上传接口会校验扩展名、MIME、文件签名和压缩包安全边界。

### 文档解析与检索

- 默认使用 PyMuPDF 提取 PDF 文本；页面没有有效文字时自动调用内置 Tesseract OCR 兜底。
- 可选 Marker 或 MinerU 处理扫描件和复杂排版，并支持 CPU/GPU 初始化、下载进度、取消、超时回收和真实解析探针。
- 入库状态机为 `uploaded → parsing → indexing → ready / failed`，记录文件哈希、页数或单元数、解析引擎、耗时、切片数和错误信息。
- 相同 SHA-256 的已索引文件可复用；失败时按 `file_id` 清理已写入向量，避免产生孤儿数据。
- 使用本地中文向量模型与 Chroma 保存索引，支持课程和文件范围过滤。
- 检索组合向量候选、BM25、MMR 去重和相关度门槛，尽量减少重复或弱相关上下文。

### XMU_DeadLines

- 复用已经通过统一身份认证的身份资料。
- 按“作业 / 小测”和“考试安排”分类查看截止时间。
- 默认优先读取本地缓存，减少页面等待。
- 可手动从畅课同步最新任务并更新本地数据库。

### XMU_RollCall

- 新增身份时先验证厦门大学统一身份认证，再保存到本机。
- 支持管理多个已认证身份；身份资料同时与 Deadline、OJ 和 TronClass 共享。
- 支持全天候监控或自定义课程活跃时段。
- 可配置轮询间隔和“已有 X 人签到后再签到”的潜伏阈值；人数读取失败时不会冒险执行。
- 实时显示认证、扫描、阈值判断、签到结果和网络错误日志。
- 支持从页面或任务中心安全停止监控。

### XMU_OJ

- 使用已认证身份登录厦大 OJ，并按实验 ID 读取题目列表。
- 可选择设置页保存的大模型，为未通过题目生成代码并提交评测。
- 自动跳过已经通过的题目，并展示生成、提交、冷却和评测结果日志。
- 支持实验密码、提交间隔和运行中止。

### XMU_TronClass

- 仅在 Windows 桌面版中可用，通过独立畅课窗口运行。
- 使用独立、持久化的 Electron 会话；首次需要手动登录，后续可复用本机登录状态。
- 左侧复用 RollCall、Deadline 和 OJ 的已认证身份列表。
- 自动使用设置页当前启用的模型，不在模块内重复保存模型配置。
- “单步识别并选择”只处理当前未作答的选择题或判断题。
- “开始连续辅助”会依次识别、请求模型、选择答案并切换下一题。
- “暂停”会停止连续流程，并让尚未完成的模型结果失效，避免停止后继续点击。
- “清空多轮记忆”只清除当前畅课辅助上下文，不删除身份、模型或课程数据。
- 程序不会点击最终“提交”或“交卷”，提交前必须由用户自行核对。

### Settings 与运行数据中心

- 配置 PyMuPDF、Marker 或 MinerU 解析引擎。
- 管理多个云端或本地模型配置，并指定当前启用模型。
- 模型接口采用 OpenAI 兼容配置：模型 ID、API Base URL 和 API Key。
- 任务中心统一展示文档解析、引擎初始化、RollCall 和备份任务。
- 后台任务支持安全取消、失败重试及 App 重启后的中断恢复。
- 数据自检覆盖 SQLite、源文件、目录结构、磁盘空间和可选的 Chroma 深度检查。
- 支持创建、下载、导入、校验和恢复 JiaYuan ZIP 资料备份。

## 推荐使用流程

1. 安装并打开 JiaYuan，等待首次运行时和基础向量模型释放完成。
2. 在 `Settings` 中添加模型 ID、API Base URL 和 API Key，并设为当前模型。
3. 保持默认 PyMuPDF，或按需要初始化 Marker / MinerU。
4. 在 XMU_RAG 中导入本地资料、整个文件夹或公开网页，并选择目标课程目录。
5. 等待资料状态变为“可检索”，再选择全部资料、指定课程或指定文件开始提问。
6. 点击回答下方引用，在侧边预览中核对原文和位置。
7. 如需使用 Deadline、RollCall、OJ 或 TronClass，可在对应模块新增并验证统一身份资料。

## Windows 桌面版

在 `release` 目录运行：

```text
JiaYuan-Setup-x64.exe
```

双击安装程序即可按当前 Windows 用户一键安装；无需预装 Python、Node.js 或后端依赖。安装完成后会自动创建桌面和开始菜单中的 `JiaYuan` 快捷方式，并启动应用。

首次启动需要把私有 Python 运行时和基础向量模型释放到当前 Windows 用户的数据目录，耗时通常比后续启动长。以后启动会复用已经准备好的运行环境；向量模型在首次入库或检索时离线按需加载，不会访问 Hugging Face 网络。

桌面数据默认保存在：

```text
%LOCALAPPDATA%\JiaYuan\
├─ data\
│  ├─ campus_assistant.db   # 资料、对话、任务、Deadline 与校园身份
│  ├─ uploads\              # 导入的原始文档
│  ├─ vector_db\            # Chroma 向量库
│  ├─ engine_config\        # 解析引擎配置
│  ├─ engine_flags\         # 解析引擎验证状态
│  └─ backups\              # 数据中心创建或导入的 ZIP 备份
├─ models\                  # 基础向量模型、Marker 与 MinerU 模型缓存
├─ runtime\                 # 私有 Python 运行时
├─ logs\                    # electron.log 与 backend.log
└─ profile\                 # Electron 配置、模型设置和畅课独立会话
```

卸载程序默认保留这个目录，以免误删知识库。若要彻底重置，请先退出 JiaYuan，备份需要保留的资料，再删除 `%LOCALAPPDATA%\JiaYuan`。

桌面安装程序当前未配置商业代码签名证书，Windows 可能显示 SmartScreen 提示；请仅使用可信来源生成的安装包，并核对发布方提供的 SHA-256。

## Marker / MinerU 初始化

1. 打开 `Settings`，选择 Marker 或 MinerU。
2. 选择 CPU 或 GPU。GPU 模式要求 NVIDIA 显卡和可用驱动；程序会先验证 CUDA，再安装匹配的 PyTorch CUDA 12.8 组件。
3. 保持网络畅通。程序会在桌面私有运行时中安装 `marker-pdf[full]` 或 `mineru[pipeline]`，模型写入 `%LOCALAPPDATA%\JiaYuan\models`，不会污染项目源码目录。
4. 只有依赖安装、模型完整性检查和最小扫描文档解析探针全部通过后，界面才会显示初始化成功。

Marker 和 MinerU 首次安装及模型下载体积较大，实际耗时由网络、磁盘、CPU 和显卡环境决定。日志长时间没有变化时，先查看 `%LOCALAPPDATA%\JiaYuan\logs\backend.log`；初始化任务会定期输出心跳，并在取消、长期无输出或超过总时限时回收子进程。

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

浏览器开发模式默认使用 `http://127.0.0.1:8000` 后端。XMU_TronClass、桌面 PDF 导出、持久化畅课窗口等 Electron 专属能力需要在桌面版中验证。

开发模式的数据库、上传文件、向量库和引擎缓存位于 `backend` 下，均已加入 `.gitignore`。不要把真实账号、`config.json`、数据库、上传资料、备份包或模型缓存提交到版本库。

## 项目结构

```text
JiaYuan\
├─ backend\             # FastAPI、SQLite、RAG、校园工具和数据维护
│  ├─ core\             # 解析、检索、任务、数据库及业务核心
│  ├─ routes\           # REST 与 SSE 接口
│  └─ tests\            # 后端单元测试
├─ frontend\            # Vue 3、Vite、Element Plus 前端
│  └─ src\components\   # 仪表盘及各功能模块
├─ desktop\             # Electron 主进程、Preload、测试和打包脚本
├─ release\             # Windows 安装包与解包构建产物
├─ install_backend.bat  # 安装后端开发依赖
└─ start.bat            # 启动浏览器开发模式
```

## 构建 Windows 安装包

```powershell
cd desktop
npm install
npm run build:runtime
npm run pack:win
```

`build:runtime` 会下载官方 Windows 嵌入式 Python，安装 `backend/requirements.txt`，下载基础中文向量模型并执行离线导入验证，然后生成桌面运行时归档。`pack:win` 会先构建 Vue 前端，再通过 electron-builder 生成 NSIS x64 安装程序。

如果运行时依赖或 Python 版本发生变化，应重新执行 `npm run build:runtime`。只修改前端、Electron 源码或普通后端源码时，可复用现有运行时归档并直接重新打包。

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

- 发布安装包不应包含开发数据库、个人账号、上传文档、Chroma 数据、备份、Marker/MinerU 用户缓存或成功标记。
- 知识库、对话、校园身份和畅课会话默认仅保存在本机，不会自动同步到云端。
- 使用云端模型时，问题和本次请求选中的知识库上下文会发送给用户配置的模型服务商；敏感资料应优先使用可信服务或本地模型。
- 校园账号密码保存在本地 SQLite 中，模型 API Key 保存在 Electron 页面配置中；当前没有额外的应用层加密，请保护 Windows 登录账号和用户数据目录。
- TronClass 登录 Cookie 保存在独立 Electron 会话中。不要复制或分享 `profile` 目录。
- 数据中心生成的备份包含数据库、上传资料、向量库和引擎配置，因此可能包含校园账号和敏感资料；备份不包含私有 Python 运行时、模型缓存、日志、模型 API Key 或 TronClass 会话。
- 网页导入仅接受 HTTP/HTTPS HTML，限制响应体和重定向，并拒绝本机、局域网、保留地址和链路本地地址，以降低 SSRF 风险。
- 远程 TronClass 模型接口必须使用 HTTPS；仅允许回环地址上的本地模型使用 HTTP。
- AI 回答、生成代码和练习题建议都可能出错。请核对引用、代码和答案，并遵守课程、考试、OJ、畅课及学校系统的使用规则。

## 故障排查

- 桌面版启动失败：查看 `%LOCALAPPDATA%\JiaYuan\logs\electron.log` 和 `backend.log`。
- 首次启动较慢：首次需要释放私有运行时和基础模型；后续启动会直接复用。若持续卡住，查看日志中的解压或后端健康检查错误。
- 首次入库或检索较慢：本地向量模型会在后台首次加载，后续操作直接复用；该过程不会访问 Hugging Face 网络。
- Marker/MinerU 初始化失败：确认网络、可用磁盘空间和 NVIDIA 驱动。不要手工创建初始化成功标记。
- 文档导入失败：在导入队列或资料库查看错误信息，修复环境后点击“重试”或“重新索引”。
- 检索没有依据：确认文件状态为“可检索”，并检查当前对话保存的课程和文件范围是否包含目标资料。
- 模型请求返回 401：API Key 无效，或对应服务账号已被删除、禁用；请在 `Settings` 更换密钥并确认当前启用模型。
- 模型请求返回 403/429：检查模型权限、账户余额、调用额度和频率限制。
- RollCall 阈值未触发：查看日志是否成功读到已签到人数；人数读取失败时任务会主动跳过本轮。
- Deadline 无法同步：确认该身份仍可通过统一身份认证，并检查畅课接口是否可访问。
- TronClass 无法控制：确认正在使用 Windows 桌面版、已经选择身份、畅课独立窗口已打开，并已在 `Settings` 配置当前模型。
- 恢复备份后数据未变化：恢复会排队到下一次后端启动执行，请退出并重新打开 App。

## 备份说明

数据中心创建的是 JiaYuan 资料备份，不是整个安装目录的镜像。备份会对 SQLite 做一致性复制，包含上传文件、Chroma 向量库、解析引擎配置及状态，并写入格式清单。导入时会检查 ZIP 路径、文件数量、展开体积和数据库完整性；恢复任务在下次启动时应用，以避免运行中替换数据库和向量库。

开发机的 `.backups` 目录用于保存工程调整前的本地备份，不会被打进桌面应用，也不会提交到 Git。该目录可能含旧数据库、账号配置和上传文档，应按敏感文件管理。

桌面封装采用 Electron 隔离渲染、沙箱、受信导航范围和独立用户数据目录；运行时归档通过 electron-builder 的 `extraResources` 随应用发布。相关实现可参考 [Electron BrowserWindow](https://www.electronjs.org/docs/latest/api/browser-window)、[Electron app 数据目录](https://www.electronjs.org/docs/latest/api/app)、[electron-builder 文件内容配置](https://www.electron.build/docs/contents/) 和 [NSIS 安装器配置](https://www.electron.build/docs/nsis/)。
