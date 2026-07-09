# backend/core/engine_init.py
# ---------------------------------------------------------------
# 负责 MinerU / Marker 这类"重型"解析引擎的首次模型初始化。
#
# 思路：
#   MinerU 和 Marker 底层都是"首次调用时自动从 HuggingFace/ModelScope
#   下载模型权重到本地缓存"的机制。所以我们不需要去猜它们具体的下载
#   命令，只需要用一个极小的"空白 PDF"去真实调用一次对应引擎的 CLI，
#   即可触发它们各自的模型下载逻辑；下载过程中的输出会被我们实时转发
#   给前端展示为进度日志。
#
#   下载成功后，我们在本地写一个"标记文件"，以后再选择同一个引擎时，
#   直接跳过下载，不再重复初始化。
#
#   ✨ 新增：支持 CPU / GPU 两种运行设备选择，由前端在"首次点击引擎"
#   弹窗里传入 use_gpu 参数：
#     - use_gpu=False（默认）：装 CPU 版 torch/torchvision，兼容性最好，
#       几乎不会崩，但推理速度慢。
#     - use_gpu=True：装 CUDA 版 torch/torchvision，需要用户电脑有
#       NVIDIA 显卡 + 匹配的驱动，速度快很多，但环境不匹配时可能崩溃
#       （届时会在日志里提示用户改回 CPU）。
#   选择结果会持久化到标记文件里，之后 processor.py 真正解析 PDF 时
#   会读取这个偏好，来决定要不要把请求路由到 GPU。
#
#   模型权重下载走的是 huggingface.co，国内网络直连经常慢到卡死，这里
#   把 HF_ENDPOINT 切到国内镜像站 hf-mirror.com。
#
#   全程自动完成，用户不需要碰任何命令行。
# ---------------------------------------------------------------
import os
import sys
import site
import json
import uuid
import shutil
import subprocess
import fitz  # PyMuPDF，用来生成一个用于"探测/触发下载"的空白 PDF

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLAG_DIR = os.path.join(BACKEND_DIR, "engine_flags")
os.makedirs(FLAG_DIR, exist_ok=True)

SUPPORTED_ENGINES = {"mineru", "marker"}

PIP_PACKAGE = {
    "mineru": 'magic-pdf[full]',
    "marker": "marker-pdf",
}
CLI_NAME = {
    "mineru": "magic-pdf",
    "marker": "marker_single",
}

TORCH_CPU_INDEX_URL = "https://download.pytorch.org/whl/cpu"
TORCH_CUDA_INDEX_URL = "https://download.pytorch.org/whl/cu124"
HF_MIRROR_ENDPOINT = "https://hf-mirror.com"


# =====================================================================
# 🔍 定位 pip --user 安装出来的可执行文件目录
#     （解决 Windows 应用商店版 Python 装完命令找不到的问题）
# =====================================================================
def _candidate_script_dirs():
    dirs = []
    try:
        user_base = site.getuserbase()
        if user_base:
            dirs.append(os.path.join(user_base, "Scripts"))
            dirs.append(os.path.join(user_base, "bin"))
    except Exception:
        pass
    try:
        user_site = site.getusersitepackages()
        if user_site:
            py_root = os.path.dirname(user_site)
            dirs.append(os.path.join(py_root, "Scripts"))
            dirs.append(os.path.join(py_root, "bin"))
    except Exception:
        pass
    dirs.append(os.path.join(os.path.dirname(sys.executable), "Scripts"))
    dirs.append(os.path.join(os.path.dirname(sys.executable), "bin"))

    seen = set()
    result = []
    for d in dirs:
        d = os.path.normpath(d)
        if d not in seen and os.path.isdir(d):
            seen.add(d)
            result.append(d)
    return result


def _build_subprocess_env(use_gpu: bool = False):
    """构造一份供子进程使用的环境变量：补全 PATH + 切换国内模型下载镜像源 + 指定运行设备"""
    env = os.environ.copy()
    extra_dirs = _candidate_script_dirs()
    if extra_dirs:
        env["PATH"] = os.pathsep.join(extra_dirs) + os.pathsep + env.get("PATH", "")
    # ✨ 把模型下载源切到国内 HuggingFace 镜像站，避免直连卡死
    env["HF_ENDPOINT"] = HF_MIRROR_ENDPOINT
    # ✨ Marker (surya) 读取 TORCH_DEVICE 这个环境变量来决定用 CPU 还是 GPU
    env["TORCH_DEVICE"] = "cuda" if use_gpu else "cpu"
    return env


def _find_cli(cli_name: str):
    found = shutil.which(cli_name, path=_build_subprocess_env()["PATH"])
    if found:
        return found
    for d in _candidate_script_dirs():
        for name in (cli_name, cli_name + ".exe"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return None


# =====================================================================
# 🎛️ MinerU 的设备偏好写在 magic-pdf.json 配置文件里，不是环境变量
# =====================================================================
def _magic_pdf_config_path():
    return os.path.join(os.path.expanduser("~"), "magic-pdf.json")


def _apply_mineru_device_config(use_gpu: bool):
    """把 GPU/CPU 偏好写进 magic-pdf.json 的 device-mode 字段（文件若不存在则跳过，等首次运行自动生成后下次再改）"""
    cfg_path = _magic_pdf_config_path()
    if not os.path.exists(cfg_path):
        return
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["device-mode"] = "cuda" if use_gpu else "cpu"
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 配置文件格式意外损坏时不阻塞主流程，静默跳过


# =====================================================================
# 📦 自动安装：先装对应设备版本的 torch/torchvision，再装主包
# =====================================================================
def _ensure_torch(use_gpu: bool):
    """
    强制装一次指定设备版本的 torch/torchvision，
    避免 pip 默认解析出跟用户硬件不匹配的版本导致崩溃。
    """
    device_label = "GPU（CUDA）" if use_gpu else "CPU"
    index_url = TORCH_CUDA_INDEX_URL if use_gpu else TORCH_CPU_INDEX_URL
    yield f"[提示] 正在准备 {device_label} 版深度学习运行库...\n"

    cmd = [sys.executable, "-m", "pip", "install",
           "--force-reinstall", "--no-deps",  # ✨ 关键：强制重装，避免 pip 认为"torch 已装"就跳过，
                                                #    导致 CPU/GPU 版本切换失效；--no-deps 避免连带重装一堆无关依赖
           "--index-url", index_url, "torch", "torchvision"]
    yield f"[执行] {' '.join(cmd)}\n"
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=_build_subprocess_env(use_gpu),
    )
    for line in process.stdout:
        line = line.rstrip()
        if line:
            yield f"[安装] {line}\n"
    process.wait()

    if process.returncode != 0:
        yield f"[错误] ❌ {device_label} 版 torch/torchvision 安装失败，返回码 {process.returncode}。\n"
        if use_gpu:
            yield "[提示] 可能是显卡驱动/CUDA 版本不匹配。建议改选 CPU 模式重试。\n"
        yield "___TORCH_FAIL___"
    else:
        yield f"[系统] ✅ {device_label} 版深度学习运行库准备完成。\n"
        yield "___TORCH_OK___"


def _auto_pip_install(engine: str, use_gpu: bool):
    """
    自动帮用户 pip install 对应引擎的主包，把输出实时 yield 出去。
    注意：torch/torchvision 已经在 init_engine_stream 一开始被 _ensure_torch()
    处理过一次了，这里不再重复安装，避免同一次初始化把几个 GB 的 torch 下两遍。
    """
    package = PIP_PACKAGE[engine]
    yield f"[提示] 未检测到 {CLI_NAME[engine]} 命令，尝试自动安装 pip 包: {package}\n"

    cmd = [sys.executable, "-m", "pip", "install", package]
    yield f"[执行] {' '.join(cmd)}\n"
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=_build_subprocess_env(use_gpu),
    )
    for line in process.stdout:
        line = line.rstrip()
        if line:
            yield f"[安装] {line}\n"
    process.wait()
    returncode = process.returncode

    if returncode != 0:
        yield f"[错误] ❌ 自动安装 {package} 失败，返回码 {returncode}。\n"
        yield "[提示] 可能是网络无法访问 PyPI，或需要手动指定国内镜像源重试。\n"
    elif _find_cli(CLI_NAME[engine]) is None:
        yield f"[错误] ❌ {package} 已安装，但仍找不到命令 `{CLI_NAME[engine]}`。\n"
        yield "[提示] 大概率是 Python 的 Scripts 目录未加入系统 PATH，请重启一下后端进程再试。\n"
    else:
        yield f"[系统] ✅ {package} 安装完成，继续下载模型...\n"


# =====================================================================
# 📌 初始化状态标记（同时记录用户选择的运行设备）
# =====================================================================
def _flag_path(engine: str) -> str:
    return os.path.join(FLAG_DIR, f"{engine}.initialized")


def is_initialized(engine: str) -> bool:
    """引擎是否已经完成过首次模型初始化"""
    if engine not in SUPPORTED_ENGINES:
        return True
    return os.path.exists(_flag_path(engine))


def get_engine_device(engine: str) -> str:
    """读取该引擎当前已初始化的运行设备（'cpu' 或 'cuda'），未初始化则默认 'cpu'"""
    path = _flag_path(engine)
    if not os.path.exists(path):
        return "cpu"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("device", "cpu")
    except Exception:
        return "cpu"


def _mark_initialized(engine: str, use_gpu: bool):
    with open(_flag_path(engine), "w", encoding="utf-8") as f:
        json.dump({"device": "cuda" if use_gpu else "cpu"}, f)


def _make_probe_pdf() -> str:
    """生成一个只有一页、几乎空白的 PDF，仅用于触发模型下载，不承担真实解析意义。
    文件名带 uuid，避免用户短时间内触发多次初始化（比如先后点了 Marker 又点 MinerU）
    时，多个子进程抢占同一个探测文件导致读写冲突。"""
    probe_path = os.path.join(BACKEND_DIR, "uploads", f"_engine_probe_{uuid.uuid4().hex[:8]}.pdf")
    os.makedirs(os.path.dirname(probe_path), exist_ok=True)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "engine initialization probe")
    doc.save(probe_path)
    doc.close()
    return probe_path


def _build_cmd(engine: str, probe_path: str, output_dir: str):
    cli_name = CLI_NAME[engine]
    cli_path = _find_cli(cli_name) or cli_name

    if engine == "mineru":
        return [cli_path, "-p", probe_path, "-o", output_dir, "-m", "auto"]
    else:  # marker
        return [cli_path, probe_path, "--output_dir", output_dir]


def _run_probe(engine: str, probe_path: str, output_dir: str, use_gpu: bool):
    """执行一次探测调用，yield 输出行；最后 yield 一个特殊标记告知调用方成功/失败"""
    cmd = _build_cmd(engine, probe_path, output_dir)
    yield f"[执行] {' '.join(cmd)}\n"

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=_build_subprocess_env(use_gpu),
    )
    for line in process.stdout:
        line = line.rstrip()
        if line:
            yield f"[下载] {line}\n"
    process.wait()

    if process.returncode != 0:
        yield f"[错误] ❌ {engine.upper()} 初始化失败，返回码 {process.returncode}。\n"
        yield "___RESULT_FAIL___"
    else:
        yield "___RESULT_OK___"


def init_engine_stream(engine: str, use_gpu: bool = False):
    """
    生成器：流式返回初始化过程中的日志。

    流程：
      1. 按选择的设备（CPU/GPU）尝试直接调用 CLI 触发模型下载
      2. 如果命令不存在（未安装 pip 包）→ 自动装对应设备版本的
         torch/torchvision + 自动 pip install 主包，装完再重试一次
      3. 两次都失败才真正报错给用户
      4. 成功后把设备选择写入标记文件，供后续实际解析时读取
    """
    if engine not in SUPPORTED_ENGINES:
        yield f"[系统] {engine} 无需初始化，可直接使用。\n"
        return

    if is_initialized(engine):
        current_device = get_engine_device(engine)
        yield f"[系统] {engine.upper()} 此前已完成初始化（当前运行设备: {current_device.upper()}），跳过下载。\n"
        return

    device_label = "GPU" if use_gpu else "CPU"
    yield f"[系统] 🚀 首次启用 {engine.upper()}（运行设备: {device_label}），开始准备本地环境...\n"

    probe_path = None
    output_dir = None
    try:
        # ✨ 关键修复：不管这个引擎的 CLI 命令是不是已经存在（比如之前用
        # 别的设备装过），都无条件先确保 torch/torchvision 是本次选择的
        # 设备版本。pip 是幂等的：版本已经匹配就几乎瞬间跳过，版本不匹配
        # （比如上次装的是 CPU 这次选 GPU）就会自动重装成正确版本，
        # 避免出现"选了 GPU 但用的还是旧 CPU 版 torch"导致报错。
        torch_ok = True
        for chunk in _ensure_torch(use_gpu):
            if chunk == "___TORCH_OK___":
                torch_ok = True
            elif chunk == "___TORCH_FAIL___":
                torch_ok = False
            else:
                yield chunk
        if not torch_ok:
            yield "[提示] 运行库准备失败，后续步骤可能会有兼容性风险，但仍继续尝试。\n"

        probe_path = _make_probe_pdf()
        output_dir = os.path.join(BACKEND_DIR, "uploads", f"_probe_out_{engine}_{uuid.uuid4().hex[:8]}")

        # MinerU 的设备选择写在配置文件里，提前尝试写一次（首次可能文件还不存在，没关系）
        if engine == "mineru":
            _apply_mineru_device_config(use_gpu)

        attempted_install = False
        for attempt in range(2):  # 最多尝试两轮：直接跑 -> (可能)装包后再跑一次
            try:
                success = False
                for chunk in _run_probe(engine, probe_path, output_dir, use_gpu):
                    if chunk == "___RESULT_OK___":
                        success = True
                    elif chunk == "___RESULT_FAIL___":
                        success = False
                    else:
                        yield chunk

                if success:
                    if engine == "mineru":
                        _apply_mineru_device_config(use_gpu)  # 文件这时候大概率已生成，再写一次确保生效
                    _mark_initialized(engine, use_gpu)
                    yield f"[系统] ✅ {engine.upper()} 模型初始化完成（运行设备: {device_label}）！以后使用该引擎将不再需要下载。\n"
                    return
                else:
                    yield "[提示] 请检查网络是否能访问模型源，或稍后重试。\n"
                    if use_gpu:
                        yield "[提示] 如果反复失败，可能是显卡驱动不兼容，建议改选 CPU 模式重试。\n"
                    return

            except FileNotFoundError:
                if attempted_install:
                    yield f"[错误] ❌ 自动安装后仍找不到命令 `{CLI_NAME[engine]}`，请手动检查安装。\n"
                    return
                attempted_install = True
                yield "[提示] 模型体积较大，具体耗时取决于网络状况，请耐心等待。\n"
                for chunk in _auto_pip_install(engine, use_gpu):
                    yield chunk
                if _find_cli(CLI_NAME[engine]) is None:
                    return
                # 安装成功，进入下一轮 for 循环，重新跑一次探测

    except Exception as e:
        yield f"[致命异常] 💥 初始化中断: {str(e)}\n"
    finally:
        try:
            if probe_path and os.path.exists(probe_path):
                os.remove(probe_path)
        except Exception:
            pass
        try:
            if output_dir and os.path.exists(output_dir):
                shutil.rmtree(output_dir, ignore_errors=True)
        except Exception:
            pass