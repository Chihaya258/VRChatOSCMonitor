"""
HardwareMonitor-VRChatOSC
========================
通过 GPU-Z 共享内存获取 GPU 硬件信息，定时发送至 VRChat 聊天框 (OSC 协议)。

原理：
  1. 读取 GPU-Z 创建的 Windows 命名共享内存 (GPUZShMem)
  2. 解析其中的 GPU 传感器数据 (负载、显存、温度等)
  3. 结合 CPU 和 RAM 使用率，通过 OSC 协议发送到 VRChat 的 /chatbox/input

依赖：
  - GPU-Z 软件 (需手动开启共享内存选项: 设置 → 勾选「共享内存」)
  - VRChat (需在设置中开启 OSC)
  - 仅支持 Windows 平台
"""

# ============================================================================
# Section 1: 导入模块
# ============================================================================

import ctypes
import json
import mmap
import os
import subprocess
import sys
import threading
import time
import winreg

import platform

import psutil
from pythonosc import udp_client

# ============================================================================
# Section 2: 默认配置常量
# ============================================================================

DEFAULT_CONFIG = {
    "gpuz_path": "",          # GPU-Z.exe 的完整路径，留空则自动搜索
    "osc_ip": "127.0.0.1",    # OSC 目标 IP (VRChat 默认本地)
    "osc_port": 9000,         # OSC 目标端口 (VRChat 默认 9000)
    "update_interval": 5,     # 数据刷新间隔 (秒)
    "debug": True,            # 是否输出详细调试日志
}

CONFIG_FILE = "config.json"
GPUZ_DOWNLOAD_URL = "https://www.techpowerup.com/download/techpowerup-gpu-z/"

# ============================================================================
# Section 3: GPU-Z 共享内存结构体 (与 GPU-Z 内部 SH_MEM 布局一一对应)
# ============================================================================

class GPUZ_RECORD(ctypes.Structure):
    """GPU-Z 静态数据键值对记录。

    存储不频繁变动的显卡信息，如名称、显存大小、驱动版本等。
    每个记录包含一个键名 (key) 和对应的值 (value)，均为宽字符串。
    """
    _pack_ = 1
    _fields_ = [
        ("key",   ctypes.c_wchar * 256),   # 键名，如 "CardName" / "MemSize" / "DriverVersion"
        ("value", ctypes.c_wchar * 256),   # 对应的字符串值
    ]


class GPUZ_SENSOR_RECORD(ctypes.Structure):
    """GPU-Z 传感器数据记录。

    存储实时变化的硬件传感器读数，如 GPU 负载、温度、风扇转速等。
    value 为 double 类型，digits 指示建议显示的小数位数。
    """
    _pack_ = 1
    _fields_ = [
        ("name",   ctypes.c_wchar * 256),  # 传感器名称，如 "GPU Load" / "GPU Temperature"
        ("unit",   ctypes.c_wchar * 8),    # 单位，如 "%" / "°C" / "MB" / "RPM"
        ("digits", ctypes.c_uint),         # 建议显示的小数位数 (0 = 整数)
        ("value",  ctypes.c_double),       # 当前传感器数值
    ]


class GPUZ_SH_MEM(ctypes.Structure):
    """GPU-Z 共享内存完整布局。

    通过 Windows 命名共享内存 "GPUZShMem" 映射，
    与 GPU-Z 内部 SH_MEM 结构体完全对齐，使用 _pack_ = 1 确保无填充字节。
    包含 128 条静态数据 + 128 条传感器数据，足够覆盖所有主流显卡。
    """
    _pack_ = 1
    _fields_ = [
        ("version",    ctypes.c_uint),                       # 共享内存协议版本号
        ("busy",       ctypes.c_int),                        # 忙碌标志 (1 = GPU-Z 正在写入数据)
        ("lastUpdate", ctypes.c_uint),                       # 最后一次更新时的系统 Tick 计数
        ("data",       GPUZ_RECORD * 128),                   # 128 条静态数据记录
        ("sensors",    GPUZ_SENSOR_RECORD * 128),            # 128 条动态传感器记录
    ]

# ============================================================================
# Section 4: 配置文件管理
# ============================================================================

# 模块级配置缓存，在 __main__ 中赋值
_config = None


def load_config():
    """加载 config.json 配置文件。

    若文件存在且合法，读取其内容并与默认值合并 (确保所有键都存在)。
    若文件不存在，自动创建包含默认值的 config.json。
    若文件存在但解析失败，打印警告并回退到默认配置。

    Returns:
        dict: 合并后的完整配置字典
    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            # 将默认值中缺失的键补充到用户配置中 (向后兼容)
            for key, value in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = value
            print(f"[INFO] 已加载配置文件: {CONFIG_FILE}")
            return config
        except (json.JSONDecodeError, IOError) as e:
            print(f"[WARN] 配置文件读取失败 ({e})，使用默认配置")

    # 配置文件不存在 → 创建默认配置
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
        print(f"[INFO] 已创建默认配置文件: {CONFIG_FILE}")
    except IOError as e:
        print(f"[WARN] 无法创建配置文件: {e}")
    return dict(DEFAULT_CONFIG)


def save_config(config):
    """保存当前配置到 config.json。

    Args:
        config: 要保存的配置字典
    """
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except IOError as e:
        print(f"[WARN] 无法保存配置文件: {e}")

# ============================================================================
# Section 5: 日志系统
# ============================================================================

def debug_log(msg, level="INFO"):
    """统一的带级别、带时间戳日志输出。

    日志级别:
      [INFO]  - 关键流程节点 (启动、连接成功、线程就绪等)
      [DEBUG] - 详细调试信息 (传感器读数、OSC 内容、搜索路径等)
      [WARN]  - 可恢复的异常 (GPU-Z 未就绪、OSC 发送失败等)
      [ERROR] - 不可恢复的错误

    当 config.debug 为 False 时，跳过所有 [DEBUG] 级别日志。

    Args:
        msg: 日志消息文本
        level: 日志级别，支持 "INFO" / "DEBUG" / "WARN" / "ERROR"
    """
    global _config
    if _config is not None and not _config.get("debug", True) and level == "DEBUG":
        return
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{level}] {timestamp} - {msg}")
    sys.stdout.flush()


def warn_gpuz_not_available():
    """打印 GPU-Z 下载引导信息 (仅在终端输出一次醒目提示)。"""
    print()
    print("=" * 60)
    print("  未找到 GPU-Z！请按以下任一方式提供 GPU-Z：")
    print("=" * 60)
    print(f"  ① 前往官网下载: {GPUZ_DOWNLOAD_URL}")
    print("  ② 将 GPU-Z.exe 放到本程序目录下:")
    print(f"     {os.getcwd()}")
    print("  ③ 在 config.json 中设置 gpuz_path 为 exe 的完整路径")
    print('     例如: "gpuz_path": "D:\\tools\\GPU-Z.exe"')
    print("  ④ 手动启动 GPU-Z 并确保已开启共享内存选项")
    print("     (GPU-Z 设置 → Sensors 标签页 → 勾选 Shared Memory)")
    print("=" * 60)
    print()

# ============================================================================
# Section 6: GPU-Z 自动搜索 (按优先级逐级搜索)
# ============================================================================


def _search_in_directory(directory):
    """在指定目录中搜索 GPU-Z 可执行文件。

    匹配文件名规则: 以 "gpu-z" 开头 (不区分大小写) 且以 ".exe" 结尾。

    Args:
        directory: 要搜索的目录路径

    Returns:
        str | None: 找到的第一个 exe 的完整路径，未找到返回 None
    """
    if not os.path.isdir(directory):
        return None
    try:
        for entry in os.listdir(directory):
            if entry.lower().startswith("gpu-z") and entry.lower().endswith(".exe"):
                full_path = os.path.join(directory, entry)
                if os.path.isfile(full_path):
                    debug_log(f"在目录中找到: {full_path}", "DEBUG")
                    return full_path
    except PermissionError:
        # 无权限访问的目录，静默跳过
        pass
    return None


def _search_registry():
    r"""在 Windows 注册表中搜索 GPU-Z 的安装路径。

    依次扫描三个标准卸载信息注册表位置:
      1. HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall     (64-bit 应用)
      2. HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall     (当前用户)
      3. HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall (32-bit)

    对每个 DisplayName 包含 "GPU-Z" 的条目，依次尝试:
      - InstallLocation 目录下搜索 exe
      - DisplayIcon 指向的 exe 或目录

    Returns:
        str | None: 找到的 exe 完整路径，未找到返回 None
    """
    registry_locations = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    for hive, subkey_path in registry_locations:
        try:
            with winreg.OpenKey(hive, subkey_path) as parent_key:
                index = 0
                while True:
                    # --- 枚举所有子键 ---
                    try:
                        subkey_name = winreg.EnumKey(parent_key, index)
                        index += 1
                    except OSError:
                        break  # 枚举完毕

                    try:
                        with winreg.OpenKey(parent_key, subkey_name) as key:
                            # --- 读取 DisplayName ---
                            try:
                                display_name = winreg.QueryValueEx(key, "DisplayName")[0]
                            except OSError:
                                continue

                            if "GPU-Z" not in display_name:
                                continue

                            debug_log(f"注册表匹配: {display_name}", "DEBUG")

                            # --- 尝试从 InstallLocation 搜索 ---
                            try:
                                install_location = winreg.QueryValueEx(key, "InstallLocation")[0]
                                result = _search_in_directory(install_location)
                                if result:
                                    return result
                            except OSError:
                                pass

                            # --- 尝试从 DisplayIcon 获取路径 ---
                            try:
                                display_icon = winreg.QueryValueEx(key, "DisplayIcon")[0]
                            except OSError:
                                continue

                            if not display_icon:
                                continue

                            icon_path = display_icon.strip('"')
                            # DisplayIcon 直接指向 exe 文件
                            if os.path.isfile(icon_path) and icon_path.lower().endswith(".exe"):
                                debug_log(f"通过注册表 DisplayIcon 找到: {icon_path}", "DEBUG")
                                return icon_path
                            # DisplayIcon 指向某个目录，从目录搜索
                            icon_dir = os.path.dirname(icon_path)
                            if icon_dir:
                                result = _search_in_directory(icon_dir)
                                if result:
                                    return result

                    except OSError:
                        continue
        except OSError:
            continue

    return None


def _search_common_paths():
    r"""在常见安装路径中搜索 GPU-Z (遍历所有存在的盘符)。

    检查每个盘符下的:
      - :\Program Files\GPU-Z\
      - :\Program Files (x86)\GPU-Z\

    Returns:
        str | None: 找到的 exe 完整路径，未找到返回 None
    """
    common_subdirs = [
        r"Program Files\GPU-Z",
        r"Program Files (x86)\GPU-Z",
    ]

    # os.path.exists 检测盘符是否存在 (不会触发硬件访问)
    for drive_letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        drive_root = f"{drive_letter}:\\"
        if not os.path.exists(drive_root):
            continue

        for subdir in common_subdirs:
            search_path = os.path.join(drive_root, subdir)
            result = _search_in_directory(search_path)
            if result:
                return result

    return None


def _search_system_path():
    """通过 where.exe 在系统 PATH 环境变量中搜索 GPU-Z。

    Returns:
        str | None: 找到的 exe 完整路径，未找到返回 None
    """
    try:
        result = subprocess.run(
            ["where.exe", "GPU-Z.exe"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # where.exe 可能返回多行 (多个同名文件)，取第一个
            path = result.stdout.strip().split("\n")[0].strip()
            if os.path.isfile(path):
                debug_log(f"通过 PATH 找到: {path}", "DEBUG")
                return path
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _search_user_dirs():
    """在用户目录中搜索 GPU-Z (下载文件夹 / 桌面)。

    Returns:
        str | None: 找到的 exe 完整路径，未找到返回 None
    """
    user_profile = os.environ.get("USERPROFILE", "")
    if not user_profile:
        return None

    user_dirs = [
        os.path.join(user_profile, "Downloads"),
        os.path.join(user_profile, "Desktop"),
    ]

    for d in user_dirs:
        result = _search_in_directory(d)
        if result:
            return result

    return None


def find_gpuz_exe():
    r"""自动搜索系统中 GPU-Z 可执行文件的位置。

    按以下优先级逐级搜索 (上一级命中则立即返回):

      1. config.json 中用户手动指定的 gpuz_path
      2. 当前工作目录 (程序所在目录)
      3. Windows 注册表 (卸载信息)
      4. 系统 PATH 环境变量 (where.exe)
      5. 所有盘符下的 Program Files\GPU-Z 和 Program Files (x86)\GPU-Z
      6. 用户 Downloads 和 Desktop 目录

    Returns:
        str | None: GPU-Z.exe 的完整路径，找不到返回 None
    """
    debug_log("开始搜索 GPU-Z 可执行文件...", "INFO")

    # ── 1. 配置文件指定的路径 ──
    gpuz_path = _config.get("gpuz_path", "").strip() if _config else ""
    if gpuz_path:
        if os.path.isfile(gpuz_path):
            debug_log(f"使用 config.json 中指定的路径: {gpuz_path}", "INFO")
            return gpuz_path
        else:
            debug_log(f"config.json 中指定的路径无效: {gpuz_path}", "WARN")

    # ── 2. 当前工作目录 ──
    debug_log("搜索当前工作目录...", "DEBUG")
    result = _search_in_directory(os.getcwd())
    if result:
        return result

    # ── 3. Windows 注册表 ──
    debug_log("搜索注册表卸载信息...", "DEBUG")
    result = _search_registry()
    if result:
        return result

    # ── 4. 系统 PATH ──
    debug_log("搜索系统 PATH 环境变量...", "DEBUG")
    result = _search_system_path()
    if result:
        return result

    # ── 5. 全盘常见安装路径 ──
    debug_log("搜索常见安装路径 (全盘遍历)...", "DEBUG")
    result = _search_common_paths()
    if result:
        return result

    # ── 6. 用户下载/桌面目录 ──
    debug_log("搜索用户目录 (Downloads / Desktop)...", "DEBUG")
    result = _search_user_dirs()
    if result:
        return result

    debug_log("搜索完毕: 未找到 GPU-Z", "WARN")
    return None

# ============================================================================
# Section 7: GPU-Z 进程与共享内存管理
# ============================================================================


def _is_gpuz_running():
    """判断 GPU-Z 进程是否已在运行。

    通过 tasklist 命令查找 GPU-Z.exe 进程名。

    Returns:
        bool: GPU-Z 进程存在返回 True
    """
    try:
        output = subprocess.getoutput('tasklist /FI "IMAGENAME eq GPU-Z.exe"')
        return "GPU-Z.exe" in output
    except Exception:
        return False


def wait_for_gpuz_shm(timeout=15):
    """轮询等待 GPU-Z 共享内存就绪。

    每 0.5 秒尝试打开命名共享内存 "GPUZShMem"，
    直到成功建立映射或超时。

    设计目的:
      GPU-Z 启动后需要数秒来初始化传感器并创建共享内存。
      此函数确保在读取数据之前共享内存已经可用，
      避免 get_GPU_info() 因共享内存未就绪而反复报错。

    Args:
        timeout: 最长等待时间 (秒)，默认 15 秒

    Returns:
        bool: 共享内存在超时前就绪返回 True，否则 False
    """
    debug_log(f"等待 GPU-Z 共享内存就绪 (最长 {timeout}s)...", "INFO")
    shm_size = ctypes.sizeof(GPUZ_SH_MEM)

    for attempt in range(timeout * 2):  # 每 0.5s 一次
        try:
            # 尝试只读打开共享内存
            mm = mmap.mmap(-1, shm_size, tagname="GPUZShMem", access=mmap.ACCESS_READ)
            mm.close()
            debug_log(f"共享内存已就绪 (第 {attempt + 1} 次尝试)", "INFO")
            return True
        except Exception:
            time.sleep(0.5)

    debug_log(f"共享内存等待超时 ({timeout}s)，请确认 GPU-Z 已启动并开启共享内存", "WARN")
    return False


def start_gpuz():
    """搜索并启动 GPU-Z，等待共享内存就绪。

    完整流程:
      1. 调用 find_gpuz_exe() 自动搜索系统上的 GPU-Z
      2. 若未找到 → 打印下载引导 + 配置说明，返回 False
      3. 若找到 → 检查 GPU-Z 是否已在运行
      4. 若未运行 → 以最小化模式 (-minimized) 启动
      5. 调用 wait_for_gpuz_shm() 轮询等待共享内存就绪
      6. 返回启动结果

    Returns:
        bool: GPU-Z 就绪 (已运行 且 共享内存可访问) 返回 True
    """
    exe_path = find_gpuz_exe()

    if exe_path is None:
        warn_gpuz_not_available()
        return False

    debug_log(f"找到 GPU-Z 可执行文件: {exe_path}", "INFO")

    # ── 检查是否已在运行 ──
    if _is_gpuz_running():
        debug_log("GPU-Z 进程已在运行中，跳过启动", "INFO")
    else:
        debug_log("正在启动 GPU-Z (最小化到系统托盘)...", "INFO")
        try:
            # shell=True 确保 Windows 正确传递带空格的路径
            subprocess.Popen(f'"{exe_path}" -minimized', shell=True)
            debug_log("GPU-Z 启动命令已执行", "DEBUG")
        except Exception as e:
            debug_log(f"启动 GPU-Z 失败: {e}", "ERROR")
            print(f"启动 GPU-Z 失败，请手动启动: {exe_path}")
            return False

    # ── 等待共享内存就绪 ──
    if wait_for_gpuz_shm(timeout=15):
        debug_log("GPU-Z 共享内存连接成功，可以开始读取硬件数据", "INFO")
        return True
    else:
        print("[WARN] GPU-Z 共享内存未就绪，请确保已开启共享内存选项:")
        print("       GPU-Z → Sensors 标签页 → 勾选 Shared Memory")
        return False

# ============================================================================
# Section 8: 硬件数据采集
# ============================================================================


def get_GPU_info():
    """通过 GPU-Z 共享内存读取当前 GPU 硬件信息。

    工作流程:
      1. 打开 Windows 命名共享内存 "GPUZShMem" (只读模式)
      2. 将原始字节映射为 GPUZ_SH_MEM 结构体
      3. 遍历 data[] 数组提取静态信息 (卡名 / 总显存)
      4. 遍历 sensors[] 数组提取动态传感器 (负载 / 已用显存)

    Returns:
        dict 包含以下字段:
          - "GPU Load":                float   GPU 核心负载百分比 (0-100)
          - "Memory Used (Dedicated)": float   已用专用显存 (GB)
          - "MemSize":                 float   总显存大小 (GB)
          - "CardName":                str     显卡名称
        读取失败时返回 None
    """
    info = {
        "GPU Load": 0.0,
        "Memory Used (Dedicated)": None,
        "MemSize": None,
        "CardName": "GPU",
    }

    shm_size = ctypes.sizeof(GPUZ_SH_MEM)

    # ── 1. 打开共享内存 ──
    try:
        mm = mmap.mmap(-1, shm_size, tagname="GPUZShMem", access=mmap.ACCESS_READ)
    except Exception as e:
        debug_log(f"无法打开 GPU-Z 共享内存: {e}", "WARN")
        return None

    # ── 2. 读取并解析 ──
    try:
        mm.seek(0)
        raw = mm.read(shm_size)
        gpuz = GPUZ_SH_MEM.from_buffer_copy(raw)

        # 遍历静态数据记录 (CardName, MemSize, DriverVersion 等)
        for record in gpuz.data:
            key = record.key
            if key == "MemSize":
                # GPU-Z 以 MB 为单位存储，转换为 GB
                info["MemSize"] = round(int(record.value) / 1024, 2)
            elif key == "CardName":
                info["CardName"] = record.value

        # 遍历传感器记录 (GPU Load, Temperature, Memory Used 等)
        for sensor in gpuz.sensors:
            name = sensor.name
            if name == "Memory Used (Dedicated)":
                # GPU-Z 以 MB 为单位存储，转换为 GB
                info["Memory Used (Dedicated)"] = round(int(sensor.value) / 1024, 2)
            elif name == "GPU Load":
                info[name] = sensor.value

        debug_log(
            f"GPU 数据已读取: {info['CardName']} | "
            f"负载 {info['GPU Load']:.1f}% | "
            f"显存 {info['Memory Used (Dedicated)']}GB/{info['MemSize']}GB",
            "DEBUG",
        )
        return info

    except Exception as e:
        debug_log(f"解析 GPU 共享内存数据失败: {e}", "ERROR")
        return None
    finally:
        mm.close()

# ============================================================================
# Section 9: 全局状态与工作线程
# ============================================================================

# --- 硬件状态缓存 (多线程共享，通过 data_lock 保护) ---
status_data = {
    "cpu": 0.0,
    "gpu": 0.0,
    "ram_used": "N/A",
    "ram_total": "N/A",
    "vram_used": "N/A",
    "vram_total": "N/A",
    "gpu_name": "GPU",
    "text": "",          # 用户在控制台输入的附加文本
}

data_lock = threading.Lock()

# --- 系统静态信息 (启动时获取一次，运行期不变) ---
SYS_CPU = platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "未知")
SYS_RAM = f"{round(psutil.virtual_memory().total / (1024**3))}GB"


def hardware_monitor():
    """硬件监控线程: 定时轮询 CPU / RAM / GPU 数据。

    每 update_interval 秒采集一次:
      - psutil.cpu_percent()  → CPU 总使用率
      - psutil.virtual_memory() → 系统内存已用/总量
      - get_GPU_info()        → GPU 负载 + 显存 (通过 GPU-Z 共享内存)

    异常处理:
      - 当 GPU-Z 不可用时 (get_GPU_info 返回 None)，GPU 相关字段保持不变，
        保留上一次的有效读数。CPU 和 RAM 照常更新。
    """
    update_interval = _config.get("update_interval", 5) if _config else 5
    debug_log(f"硬件监控线程已启动 (刷新间隔 {update_interval}s)", "INFO")

    while True:
        # ── 采集 CPU 和系统内存 ──
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        ram_used = round(mem.used / (1024 ** 3), 2)
        ram_total = round(mem.total / (1024 ** 3), 2)

        # ── 采集 GPU 数据 ──
        gpu = get_GPU_info()

        # ── 线程安全地更新全局状态 ──
        with data_lock:
            # CPU / RAM 始终更新
            status_data["cpu"] = cpu_percent
            status_data["ram_used"] = ram_used
            status_data["ram_total"] = ram_total

            # GPU: 仅在有有效数据时才更新 (修复原版 Bug: gpu 为 None 时跳过下游)
            if gpu is not None:
                status_data["gpu"] = gpu["GPU Load"]
                status_data["vram_used"] = (
                    f"{gpu['Memory Used (Dedicated)']}GB"
                    if gpu["Memory Used (Dedicated)"] is not None
                    else "N/A"
                )
                status_data["vram_total"] = (
                    f"{gpu['MemSize']}GB"
                    if gpu["MemSize"] is not None
                    else "N/A"
                )
                status_data["gpu_name"] = gpu["CardName"] or "GPU"

        time.sleep(update_interval)


def send_osc():
    """OSC 发送线程: 定时将硬件状态发送至 VRChat 聊天框。

    通过 python-osc 库向本地 UDP 端口发送 /chatbox/input 消息。
    VRChat 收到后会在聊天框中显示多行格式化文本:

        CPU[Intel i7-13700K]: 35.2%
        RAM: 12.5GB/32GB
        GPU[RTX 4090]: 82.1%
        VRAM: 18.2GB/24GB
    """
    update_interval = _config.get("update_interval", 5) if _config else 5
    osc_ip = _config.get("osc_ip", "127.0.0.1") if _config else "127.0.0.1"
    osc_port = _config.get("osc_port", 9000) if _config else 9000

    debug_log(f"OSC 发送线程已启动 → {osc_ip}:{osc_port}", "INFO")

    client = udp_client.SimpleUDPClient(osc_ip, osc_port)

    while True:
        # ── 读取最新状态快照 ──
        with data_lock:
            data = status_data.copy()

        # ── 组装多行消息 ──
        parts = [
            f"CPU[{SYS_CPU}]: {data['cpu']:.1f}%",
            f"RAM: {data['ram_used']}GB/{data['ram_total']}GB",
            f"GPU[{data['gpu_name']}]: {data['gpu']:.1f}%",
            f"VRAM: {data['vram_used']}/{data['vram_total']}",
        ]

        # 用户在控制台输入的附加文本
        if data["text"]:
            parts.append(f'"{data["text"].strip()}"')

        # ── 通过 OSC 发送 ──
        try:
            client.send_message("/chatbox/input", ["\n".join(parts), True])
            debug_log("OSC 消息已发送", "DEBUG")
        except Exception as e:
            debug_log(f"OSC 发送失败 (请确认 VRChat 正在运行且 OSC 已开启): {e}", "WARN")

        time.sleep(update_interval)


def input_handler():
    """控制台输入线程: 将用户输入文本追加到 OSC 聊天框消息末尾。

    在程序运行期间，用户可以在控制台中直接输入任意文本，
    该文本将作为额外行显示在 VRChat 聊天框中。
    输入空行可清空附加文本。
    """
    debug_log("控制台输入线程已就绪 (输入文本以追加到聊天框消息)", "INFO")

    while True:
        try:
            new_text = input().strip()
            with data_lock:
                status_data["text"] = new_text + " " if new_text else ""
            if new_text:
                debug_log(f"聊天框附加文本: \"{new_text}\"", "DEBUG")
            else:
                debug_log("聊天框附加文本已清空", "DEBUG")
        except EOFError:
            # stdin 被关闭 (如通过 nohup 或管道运行)
            pass
        except Exception as e:
            debug_log(f"输入处理异常: {e}", "DEBUG")

# ============================================================================
# Section 10: 主入口
# ============================================================================


if __name__ == "__main__":
    # ── 阶段 1: 加载配置 ──
    _config = load_config()

    # ── 阶段 2: 打印启动横幅 ──
    print("=" * 60)
    print("  HardwareMonitor-VRChatOSC")
    print("  硬件监控 → VRChat OSC 聊天框")
    print("=" * 60)
    print(f"  CPU:      {SYS_CPU}")
    print(f"  RAM:      {SYS_RAM}")
    print(f"  OSC目标:  {_config.get('osc_ip', '127.0.0.1')}:{_config.get('osc_port', 9000)}")
    print(f"  更新间隔: {_config.get('update_interval', 5)}s")
    print(f"  调试模式: {'开' if _config.get('debug', True) else '关'}")
    print("=" * 60)

    # ── 阶段 3: 搜索并启动 GPU-Z ──
    gpuz_ready = start_gpuz()
    if gpuz_ready:
        print("[INFO] GPU-Z 已就绪，开始硬件监控...\n")
    else:
        print("[INFO] GPU-Z 未就绪，程序将持续尝试检测共享内存。")
        print("       后续启动 GPU-Z 后无需重启本程序。\n")

    # ── 阶段 4: 启动守护线程 ──
    threading.Thread(target=hardware_monitor, daemon=True, name="HW-Monitor").start()
    threading.Thread(target=send_osc, daemon=True, name="OSC-Sender").start()
    threading.Thread(target=input_handler, daemon=True, name="Input-Handler").start()

    debug_log("全部线程已启动，按 Ctrl+C 退出程序", "INFO")

    # ── 阶段 5: 主线程空闲等待 ──
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n程序已退出，感谢使用!")
