"""Marker / MinerU 的安装、模型下载和可用性验证。"""

import importlib.util
import json
import os
import queue
import shutil
import site
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

import fitz

from core.paths import (
    DATA_DIR,
    ENGINE_FLAG_DIR,
    MINERU_CONFIG_PATH,
    MODEL_DIR,
    UPLOAD_DIR,
)


BACKEND_DIR = DATA_DIR
FLAG_DIR = ENGINE_FLAG_DIR
os.makedirs(FLAG_DIR, exist_ok=True)

SUPPORTED_ENGINES = {"marker", "mineru"}
PIP_PACKAGE = {
    # full extra 才包含 DOCX/PPTX/HTML 等非 PDF 输入所需的转换依赖。
    "marker": "marker-pdf[full]",
    # 当前 MinerU 已从 magic-pdf 迁移到 mineru CLI。pipeline 后端同时支持 CPU/GPU。
    "mineru": "mineru[pipeline]",
}
CLI_NAME = {
    "marker": "marker_single",
    "mineru": "mineru",
}
MODULE_ENTRY = {
    "marker": ("marker.scripts.convert_single", "convert_single_cli"),
    "mineru": ("mineru.cli.client", "main"),
}

HF_MIRROR_ENDPOINT = "https://hf-mirror.com"
INIT_SUCCESS_TOKEN = "___ENGINE_INIT_SUCCESS___"
INIT_FAILURE_TOKEN = "___ENGINE_INIT_FAILED___"
_PROBE_OK = "___PROBE_OK___"
_PROBE_FAIL = "___PROBE_FAIL___"
_INSTALL_OK = "___INSTALL_OK___"
_INSTALL_FAIL = "___INSTALL_FAIL___"
_GPU_TORCH_OK = "___GPU_TORCH_OK___"
_GPU_TORCH_FAIL = "___GPU_TORCH_FAIL___"
_MODELS_OK = "___MODELS_OK___"
_MODELS_FAIL = "___MODELS_FAIL___"
FLAG_SCHEMA_VERSION = 3

# RTX 50 系列（sm_120）需要较新的 PyTorch CUDA kernel。固定匹配的官方
# torch / torchvision wheel，防止只升级其中一项而产生 ABI 不兼容。
GPU_TORCH_VERSION = "2.11.0"
GPU_TORCHVISION_VERSION = "0.26.0"
GPU_TORCH_INDEX_URL = "https://download.pytorch.org/whl/cu128"
INSTALL_TIMEOUT_SECONDS = 60 * 60
MODEL_DOWNLOAD_TIMEOUT_SECONDS = 2 * 60 * 60
PROBE_TIMEOUT_SECONDS = 30 * 60
INIT_HEARTBEAT_SECONDS = 5
MINERU_PIPELINE_MODEL_DIRS = (
    ("models", "Layout", "PP-DocLayoutV2"),
    ("models", "MFR", "unimernet_hf_small_2503"),
    ("models", "MFR", "pp_formulanet_plus_m"),
    ("models", "OCR", "paddleocr_torch"),
    ("models", "TabCls", "paddle_table_cls"),
    ("models", "TabRec", "SlanetPlus"),
    ("models", "TabRec", "UnetStructure"),
)
# Marker 的 MarkdownRenderer 支持保留分页。使用极不可能出现在课件正文中的
# 分隔符，供 processor.py 将 Markdown 精确拆回 PDF 页级文本并写入引用元数据。
MARKER_PAGE_SEPARATOR = "<!-- JIAYUAN_PAGE_BREAK -->"

# 8 GB 笔记本显卡运行 Marker 的默认并发/批量会占满显存，在高分辨率扫描件上
# 容易持续交换显存而长时间没有产出。这里优先稳定和可见进度，而非峰值吞吐。
MARKER_LOW_VRAM_GPU_ARGS = (
    "--disable_multiprocessing",
    "--layout_batch_size", "1",
    "--detection_batch_size", "1",
    "--ocr_error_batch_size", "1",
    # 识别模型本身约占 3.5 GB；8 条一批可保持在 8 GB 显存以内，
    # 又避免逐行推理使扫描件耗时成倍增加。
    "--recognition_batch_size", "8",
    "--equation_batch_size", "1",
    "--lowres_image_dpi", "96",
    "--highres_image_dpi", "144",
)

_INIT_LOCKS = {engine: threading.Lock() for engine in SUPPORTED_ENGINES}


def _candidate_script_dirs():
    """定位 pip 在当前解释器或 --user 目录生成的可执行文件。"""
    dirs = []
    try:
        user_base = site.getuserbase()
        if user_base:
            dirs.extend([os.path.join(user_base, "Scripts"), os.path.join(user_base, "bin")])
    except Exception:
        pass
    try:
        user_site = site.getusersitepackages()
        if user_site:
            py_root = os.path.dirname(user_site)
            dirs.extend([os.path.join(py_root, "Scripts"), os.path.join(py_root, "bin")])
    except Exception:
        pass

    executable_dir = os.path.dirname(sys.executable)
    dirs.extend(
        [
            executable_dir,
            os.path.join(executable_dir, "Scripts"),
            os.path.join(executable_dir, "bin"),
        ]
    )

    seen = set()
    result = []
    for directory in dirs:
        normalized = os.path.normpath(directory)
        if normalized not in seen and os.path.isdir(normalized):
            seen.add(normalized)
            result.append(normalized)
    return result


def _build_subprocess_env(use_gpu: bool = False):
    """为安装和解析子进程构造统一环境。"""
    env = os.environ.copy()
    extra_dirs = _candidate_script_dirs()
    if extra_dirs:
        env["PATH"] = os.pathsep.join(extra_dirs) + os.pathsep + env.get("PATH", "")

    device = "cuda" if use_gpu else "cpu"
    env["TORCH_DEVICE"] = device  # Marker / Surya
    env["MINERU_DEVICE_MODE"] = device
    env.setdefault("MINERU_MODEL_SOURCE", "modelscope")
    env["MINERU_TOOLS_CONFIG_JSON"] = MINERU_CONFIG_PATH
    env.setdefault("HF_HOME", os.path.join(MODEL_DIR, "huggingface"))
    env.setdefault("MODELSCOPE_CACHE", os.path.join(MODEL_DIR, "modelscope"))
    env.setdefault("HF_ENDPOINT", HF_MIRROR_ENDPOINT)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    # MinerU 3.x 会启动一个 127.0.0.1 临时 API，再由 CLI 用 httpx 提交任务。
    # 若系统配置了 HTTP(S)_PROXY 而 NO_PROXY 未含 localhost，任务会被错误地
    # 交给代理并永久停在“服务已启动、队列为 0”。模型下载仍可使用代理。
    no_proxy_values = [value.strip() for value in env.get("NO_PROXY", "").split(",") if value.strip()]
    for host in ("127.0.0.1", "localhost", "::1"):
        if host not in no_proxy_values:
            no_proxy_values.append(host)
    env["NO_PROXY"] = ",".join(no_proxy_values)
    env["no_proxy"] = env["NO_PROXY"]
    return env


def _find_cli(cli_name: str):
    found = shutil.which(cli_name, path=_build_subprocess_env()["PATH"])
    if found:
        return found
    for directory in _candidate_script_dirs():
        for name in (cli_name, cli_name + ".exe", cli_name + ".cmd"):
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def _module_available(engine: str) -> bool:
    module_name, _ = MODULE_ENTRY[engine]
    top_level_module = module_name.split(".", 1)[0]
    try:
        return importlib.util.find_spec(top_level_module) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _resolve_cli_prefix(engine: str):
    """
    返回用于启动引擎的命令前缀。

    Windows 上偶尔会出现 pip 已安装包但没生成 Scripts/*.exe 的情况，
    因此在 CLI 不存在时直接调用官方 entry point。
    """
    cli_path = _find_cli(CLI_NAME[engine])
    if cli_path:
        return [cli_path]
    if not _module_available(engine):
        return None

    module_name, function_name = MODULE_ENTRY[engine]
    entry_code = f"from {module_name} import {function_name}; {function_name}()"
    return [sys.executable, "-c", entry_code]


def _format_command(cmd) -> str:
    return subprocess.list2cmdline(cmd)


def _terminate_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()


def _stream_process_events(cmd, *, env, timeout_seconds: int):
    """在子进程静默时仍产生心跳，且超时后回收完整进程树。"""
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    output_queue: queue.Queue = queue.Queue()
    output_finished = object()

    def pump_output():
        try:
            for line in process.stdout:
                output_queue.put(line.rstrip())
        finally:
            output_queue.put(output_finished)

    threading.Thread(target=pump_output, daemon=True).start()
    started_at = time.monotonic()
    last_heartbeat = started_at
    timed_out = False

    while True:
        try:
            item = output_queue.get(timeout=1)
        except queue.Empty:
            item = None

        now = time.monotonic()
        elapsed = int(now - started_at)
        if elapsed >= timeout_seconds and process.poll() is None:
            timed_out = True
            _terminate_process_tree(process)
            yield "timeout", elapsed
            break

        if item is output_finished:
            break
        if isinstance(item, str) and item:
            last_heartbeat = now
            yield "line", item
        elif process.poll() is None and now - last_heartbeat >= INIT_HEARTBEAT_SECONDS:
            last_heartbeat = now
            yield "heartbeat", elapsed

        if process.poll() is not None and output_queue.empty():
            break

    if not timed_out:
        process.wait()
    yield "exit", process.returncode


def build_engine_command(
    engine: str,
    input_path: str,
    output_dir: str,
    *,
    force_ocr: bool = False,
    use_gpu: bool = False,
):
    """生成与当前官方 CLI 匹配的解析命令。"""
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"不支持的解析引擎: {engine}")
    prefix = _resolve_cli_prefix(engine)
    if prefix is None:
        raise FileNotFoundError(f"未找到 {CLI_NAME[engine]} CLI 或 {engine} Python 包")

    if engine == "marker":
        cmd = prefix + [
            input_path,
            "--output_dir", output_dir,
            "--output_format", "markdown",
            "--paginate_output",
            "--page_separator", MARKER_PAGE_SEPARATOR,
        ]
        if use_gpu:
            cmd.extend(MARKER_LOW_VRAM_GPU_ARGS)
        if force_ocr:
            cmd.append("--force_ocr")
        return cmd

    # pipeline 可由 MINERU_DEVICE_MODE=cpu/cuda 选择设备。相比 MinerU 3.x 的
    # 默认 hybrid-engine，它不依赖 Windows + Python 3.13 尚不支持的 Ray，
    # 因而在本项目环境中可稳定走 CUDA。
    return prefix + ["-p", input_path, "-o", output_dir, "-b", "pipeline"]


def read_markdown_output(output_dir: str) -> str:
    """递归读取引擎产生的非空 Markdown；不依赖具体版本的目录层级。"""
    markdown_files = []
    if os.path.isdir(output_dir):
        for root, _, files in os.walk(output_dir):
            for filename in files:
                if filename.lower().endswith(".md"):
                    markdown_files.append(os.path.join(root, filename))

    for path in sorted(markdown_files):
        try:
            with open(path, "r", encoding="utf-8") as file:
                content = file.read()
            if content.strip():
                return content
        except (OSError, UnicodeError):
            continue
    return ""


def _flag_path(engine: str) -> str:
    return os.path.join(FLAG_DIR, f"{engine}.initialized")


def _read_flag(engine: str):
    try:
        with open(_flag_path(engine), "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError, TypeError):
        return None


def is_initialized(engine: str) -> bool:
    """只有新版探针验证成功且 CLI/包仍存在时才返回 True。"""
    if engine not in SUPPORTED_ENGINES:
        return False
    flag = _read_flag(engine)
    if not flag:
        return False
    return (
        flag.get("schema_version") == FLAG_SCHEMA_VERSION
        and flag.get("package") == PIP_PACKAGE[engine]
        and _resolve_cli_prefix(engine) is not None
        and (engine != "mineru" or _mineru_pipeline_models_ready())
    )


def get_engine_device(engine: str) -> str:
    flag = _read_flag(engine) or {}
    return flag.get("device", "cpu")


def _mark_initialized(engine: str, use_gpu: bool):
    payload = {
        "schema_version": FLAG_SCHEMA_VERSION,
        "engine": engine,
        "package": PIP_PACKAGE[engine],
        "device": "cuda" if use_gpu else "cpu",
        "python": sys.version.split()[0],
        "model_dir": MODEL_DIR,
        "initialized_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(_flag_path(engine), "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def _python_compatibility_error(engine: str):
    version = sys.version_info
    if version < (3, 10) or version >= (3, 14):
        return f"{engine.upper()} 需要 Python 3.10-3.13，当前为 {version.major}.{version.minor}"
    return None


def _python_compatibility_warning(engine: str):
    """对官方建议范围外但仍可能可运行的环境给出提示，不抢先阻止真实探针。"""
    version = sys.version_info
    if engine == "mineru" and os.name == "nt" and version >= (3, 13):
        return "MinerU 在 Windows + Python 3.13 环境兼容性可能受部分依赖影响；将继续进行真实扫描件探针验证"
    return None


def _gpu_is_available(use_gpu: bool):
    """
    不仅检查 CUDA 是否可见，也检查当前 PyTorch wheel 是否包含该显卡架构的 kernel。

    例如 RTX 50 系列的 sm_120 在旧 PyTorch 中会让 cuda.is_available() 返回 True，
    但实际第一个 torch 运算就报 "no kernel image is available"。
    """
    if not use_gpu:
        return True, ""
    check_script = """
import json
import torch

info = {"torch": torch.__version__, "cuda_available": torch.cuda.is_available()}
if not torch.cuda.is_available():
    print(json.dumps(info, ensure_ascii=False))
    raise SystemExit(2)

capability = torch.cuda.get_device_capability(0)
architecture = f"sm_{capability[0]}{capability[1]}"
supported = torch.cuda.get_arch_list()
info.update({
    "device": torch.cuda.get_device_name(0),
    "architecture": architecture,
    "supported_architectures": supported,
})
print(json.dumps(info, ensure_ascii=False))
raise SystemExit(0 if architecture in supported or architecture.replace("sm_", "compute_") in supported else 3)
"""
    cmd = [
        sys.executable,
        "-c",
        check_script,
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_build_subprocess_env(True),
    )
    detail = (result.stdout + "\n" + result.stderr).strip()[-500:]
    return result.returncode == 0, detail


def _stream_pip_install(engine: str, use_gpu: bool):
    package = PIP_PACKAGE[engine]
    yield f"[提示] 未检测到可用的 {CLI_NAME[engine]}，开始安装 {package}。\n"
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", package]
    yield f"[执行] {_format_command(cmd)}\n"

    return_code = None
    timed_out = False
    for event, value in _stream_process_events(
        cmd,
        env=_build_subprocess_env(use_gpu),
        timeout_seconds=INSTALL_TIMEOUT_SECONDS,
    ):
        if event == "line":
            yield f"[安装] {value}\n"
        elif event == "heartbeat":
            yield f"[进度] 依赖安装仍在进行，已等待 {value} 秒...\n"
        elif event == "timeout":
            timed_out = True
            yield f"[错误] ❌ {package} 安装超过 {value} 秒，已回收安装进程。\n"
        elif event == "exit":
            return_code = value

    if timed_out or return_code != 0:
        yield f"[错误] ❌ {package} 安装失败，返回码 {return_code}。\n"
        yield _INSTALL_FAIL
        return
    if _resolve_cli_prefix(engine) is None:
        yield f"[错误] ❌ {package} 已安装，但 CLI 和 Python entry point 都不可用。\n"
        yield _INSTALL_FAIL
        return

    yield f"[系统] ✅ {package} 安装完成，即将下载/验证模型。\n"
    yield _INSTALL_OK


def _stream_gpu_torch_upgrade():
    """安装可覆盖 RTX 50 系列架构的官方 PyTorch CUDA wheel。"""
    yield (
        "[设备] 正在安装支持当前 NVIDIA 显卡的 PyTorch CUDA 12.8 运行时；"
        "下载体积较大，请保持此窗口打开。\n"
    )
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--force-reinstall",
        f"torch=={GPU_TORCH_VERSION}",
        f"torchvision=={GPU_TORCHVISION_VERSION}",
        "--index-url",
        GPU_TORCH_INDEX_URL,
    ]
    yield f"[执行] {_format_command(cmd)}\n"

    return_code = None
    timed_out = False
    for event, value in _stream_process_events(
        cmd,
        env=_build_subprocess_env(True),
        timeout_seconds=INSTALL_TIMEOUT_SECONDS,
    ):
        if event == "line":
            yield f"[PyTorch] {value}\n"
        elif event == "heartbeat":
            yield f"[进度] PyTorch CUDA 下载/安装仍在进行，已等待 {value} 秒...\n"
        elif event == "timeout":
            timed_out = True
            yield f"[错误] ❌ PyTorch CUDA 安装超过 {value} 秒，已回收安装进程。\n"
        elif event == "exit":
            return_code = value

    if timed_out or return_code != 0:
        yield f"[错误] ❌ PyTorch CUDA 更新失败，返回码 {return_code}。\n"
        yield _GPU_TORCH_FAIL
        return

    gpu_ok, gpu_detail = _gpu_is_available(True)
    if not gpu_ok:
        yield "[错误] ❌ PyTorch 已更新，但仍无法在当前显卡上执行 CUDA kernel。\n"
        if gpu_detail:
            yield f"[设备] {gpu_detail}\n"
        yield _GPU_TORCH_FAIL
        return

    yield "[设备] ✅ 已验证 PyTorch CUDA kernel 可在当前 NVIDIA 显卡上执行。\n"
    yield _GPU_TORCH_OK


def _mineru_pipeline_models_ready() -> bool:
    """校验官方 downloader 已写入配置，且 pipeline 的关键模型目录齐全。"""
    try:
        with open(MINERU_CONFIG_PATH, "r", encoding="utf-8") as file:
            config = json.load(file)
        model_root = config.get("models-dir", {}).get("pipeline")
        if not isinstance(model_root, str) or not model_root:
            return False
        return all(os.path.isdir(os.path.join(model_root, *parts)) for parts in MINERU_PIPELINE_MODEL_DIRS)
    except (OSError, ValueError, TypeError):
        return False


def _stream_mineru_model_download():
    """显式准备 MinerU pipeline 模型和其本地配置，避免 CLI 隐式下载时无进度卡住。"""
    if _mineru_pipeline_models_ready():
        yield "[模型] ✅ 已检测到完整的 MinerU pipeline 本地模型，跳过重复下载。\n"
        yield _MODELS_OK
        return

    downloader = _find_cli("mineru-models-download")
    if downloader:
        cmd = [downloader, "-s", "modelscope", "-m", "pipeline"]
    else:
        cmd = [sys.executable, "-m", "mineru.cli.models_download", "-s", "modelscope", "-m", "pipeline"]

    yield "[模型] 正在准备 MinerU pipeline 模型（首次下载可能需要较长时间）。\n"
    yield f"[模型] 下载目录：{os.path.join(MODEL_DIR, 'modelscope')}\n"
    yield f"[执行] {_format_command(cmd)}\n"
    return_code = None
    timed_out = False
    for event, value in _stream_process_events(
        cmd,
        env=_build_subprocess_env(True),
        timeout_seconds=MODEL_DOWNLOAD_TIMEOUT_SECONDS,
    ):
        if event == "line":
            yield f"[模型] {value}\n"
        elif event == "heartbeat":
            yield f"[进度] MinerU 模型仍在下载/校验，已等待 {value} 秒...\n"
        elif event == "timeout":
            timed_out = True
            yield f"[错误] ❌ MinerU 模型准备超过 {value} 秒，已回收下载进程。\n"
        elif event == "exit":
            return_code = value

    if timed_out or return_code != 0 or not _mineru_pipeline_models_ready():
        yield f"[错误] ❌ MinerU pipeline 模型准备失败，返回码 {return_code}，完整性校验未通过。\n"
        yield _MODELS_FAIL
        return

    yield "[模型] ✅ MinerU pipeline 模型和本地配置已准备完成。\n"
    yield _MODELS_OK


def _make_probe_pdf() -> str:
    """生成没有文字层的扫描型 PDF，用于真实验证 OCR 模型。"""
    probe_path = os.path.join(UPLOAD_DIR, f"_engine_probe_{uuid.uuid4().hex[:8]}.pdf")
    os.makedirs(os.path.dirname(probe_path), exist_ok=True)

    source_doc = fitz.open()
    source_page = source_doc.new_page(width=612, height=792)
    source_page.insert_text(
        (72, 180),
        "Engine initialization OCR probe\nMarker and MinerU must read this scanned page.",
        fontsize=18,
    )
    pixmap = source_page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    image_bytes = pixmap.tobytes("png")
    source_doc.close()

    probe_doc = fitz.open()
    probe_page = probe_doc.new_page(width=612, height=792)
    probe_page.insert_image(probe_page.rect, stream=image_bytes)
    probe_doc.save(probe_path)
    probe_doc.close()
    return probe_path


def _run_probe(engine: str, probe_path: str, output_dir: str, use_gpu: bool):
    cmd = build_engine_command(
        engine,
        probe_path,
        output_dir,
        force_ocr=(engine == "marker"),
        use_gpu=use_gpu,
    )
    yield f"[执行] {_format_command(cmd)}\n"
    yield "[验证] 正在用无文字层的扫描 PDF 验证 OCR 和 Markdown 输出...\n"

    return_code = None
    timed_out = False
    for event, value in _stream_process_events(
        cmd,
        env=_build_subprocess_env(use_gpu),
        timeout_seconds=PROBE_TIMEOUT_SECONDS,
    ):
        if event == "line":
            yield f"[引擎] {value}\n"
        elif event == "heartbeat":
            yield f"[进度] {engine.upper()} 正在加载模型/执行 OCR，已等待 {value} 秒...\n"
        elif event == "timeout":
            timed_out = True
            yield f"[错误] ❌ {engine.upper()} 探针超过 {value} 秒，已回收引擎进程。\n"
        elif event == "exit":
            return_code = value

    if timed_out or return_code != 0:
        yield f"[错误] ❌ {engine.upper()} 扫描件探针失败，返回码 {return_code}。\n"
        yield _PROBE_FAIL
        return

    markdown = read_markdown_output(output_dir)
    if not markdown.strip():
        yield f"[错误] ❌ {engine.upper()} 返回成功码，但未生成非空 Markdown。\n"
        yield _PROBE_FAIL
        return

    yield f"[验证] ✅ 扫描件 OCR 成功，生成 {len(markdown)} 个字符的 Markdown。\n"
    yield _PROBE_OK


def init_engine_stream(engine: str, use_gpu: bool = False):
    """
    安装引擎并用扫描型 PDF 完成真实探针。

    只有安装、设备检查、CLI 执行和非空 Markdown 输出全部成功后，
    才写入 initialized 标记并输出 INIT_SUCCESS_TOKEN。
    """
    probe_path = None
    output_dir = None
    init_lock = None
    lock_acquired = False
    try:
        if engine not in SUPPORTED_ENGINES:
            yield f"[错误] ❌ 不支持的引擎: {engine}\n"
            yield INIT_FAILURE_TOKEN
            return

        init_lock = _INIT_LOCKS[engine]
        lock_acquired = init_lock.acquire(blocking=False)
        if not lock_acquired:
            yield f"[错误] ❌ {engine.upper()} 已有一个初始化任务正在运行，请勿重复点击。\n"
            yield INIT_FAILURE_TOKEN
            return

        compatibility_error = _python_compatibility_error(engine)
        if compatibility_error:
            yield f"[错误] ❌ {compatibility_error}。\n"
            yield INIT_FAILURE_TOKEN
            return

        compatibility_warning = _python_compatibility_warning(engine)
        if compatibility_warning:
            yield f"[提示] ⚠️ {compatibility_warning}。\n"

        requested_device = "cuda" if use_gpu else "cpu"
        if is_initialized(engine) and get_engine_device(engine) == requested_device:
            yield f"[系统] ✅ {engine.upper()} 已通过扫描件验证（{requested_device.upper()}），无需重复下载。\n"
            yield INIT_SUCCESS_TOKEN
            return
        if is_initialized(engine):
            previous_device = get_engine_device(engine)
            yield (
                f"[系统] 当前 {engine.upper()} 已验证为 {previous_device.upper()}；"
                f"现按请求切换为 {requested_device.upper()} 并重新验证。\n"
            )

        device_label = "GPU" if use_gpu else "CPU"
        yield f"[系统] 🚀 首次启用 {engine.upper()}（{device_label}），开始准备环境...\n"

        existing_flag = _read_flag(engine) or {}
        package_definition_changed = (
            existing_flag.get("package") not in {None, PIP_PACKAGE[engine]}
            or (
                engine == "marker"
                and _resolve_cli_prefix(engine) is not None
                and existing_flag.get("package") != PIP_PACKAGE[engine]
            )
        )
        if _resolve_cli_prefix(engine) is None or package_definition_changed:
            if package_definition_changed:
                yield (
                    f"[系统] 检测到解析包配置已升级为 {PIP_PACKAGE[engine]}，"
                    "正在补齐多格式文档依赖。\n"
                )
            install_ok = False
            for chunk in _stream_pip_install(engine, use_gpu):
                if chunk == _INSTALL_OK:
                    install_ok = True
                elif chunk == _INSTALL_FAIL:
                    install_ok = False
                else:
                    yield chunk
            if not install_ok:
                yield INIT_FAILURE_TOKEN
                return
        else:
            yield f"[系统] ✅ 已检测到 {CLI_NAME[engine]} 或可用的 Python entry point。\n"

        gpu_ok, gpu_detail = _gpu_is_available(use_gpu)
        if not gpu_ok:
            yield "[设备] ⚠️ 已选择 GPU，但当前 PyTorch 无法为该显卡架构执行 CUDA kernel。\n"
            if gpu_detail:
                yield f"[设备] {gpu_detail}\n"
            torch_upgrade_ok = False
            for chunk in _stream_gpu_torch_upgrade():
                if chunk == _GPU_TORCH_OK:
                    torch_upgrade_ok = True
                elif chunk == _GPU_TORCH_FAIL:
                    torch_upgrade_ok = False
                else:
                    yield chunk
            if not torch_upgrade_ok:
                yield "[错误] ❌ GPU 环境未通过验证；不会降级为 CPU 或写入初始化成功标记。\n"
                yield INIT_FAILURE_TOKEN
                return

        if engine == "mineru":
            models_ok = False
            for chunk in _stream_mineru_model_download():
                if chunk == _MODELS_OK:
                    models_ok = True
                elif chunk == _MODELS_FAIL:
                    models_ok = False
                else:
                    yield chunk
            if not models_ok:
                yield INIT_FAILURE_TOKEN
                return

        probe_path = _make_probe_pdf()
        output_dir = os.path.join(UPLOAD_DIR, f"_probe_out_{engine}_{uuid.uuid4().hex[:8]}")
        if engine == "marker":
            yield f"[模型] Marker 首次运行会自动下载模型，缓存目录：{os.path.join(MODEL_DIR, 'huggingface')}\n"

        probe_ok = False
        for chunk in _run_probe(engine, probe_path, output_dir, use_gpu):
            if chunk == _PROBE_OK:
                probe_ok = True
            elif chunk == _PROBE_FAIL:
                probe_ok = False
            else:
                yield chunk

        if not probe_ok:
            yield INIT_FAILURE_TOKEN
            return

        _mark_initialized(engine, use_gpu)
        actual_device = "GPU" if use_gpu else "CPU"
        yield f"[系统] ✅ {engine.upper()} 已完成安装、OCR 和 Markdown 输出验证（实际运行设备: {actual_device}）。\n"
        yield INIT_SUCCESS_TOKEN
    except Exception as exc:
        yield f"[致命异常] 💥 初始化中断: {exc}\n"
        yield INIT_FAILURE_TOKEN
    finally:
        if probe_path:
            try:
                os.remove(probe_path)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        if output_dir:
            shutil.rmtree(output_dir, ignore_errors=True)
        if lock_acquired and init_lock:
            init_lock.release()
