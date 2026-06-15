"""
GPU-Z 搜索与进程管理模块

负责自动搜索系统中的 GPU-Z 可执行文件，启动 GPU-Z 进程，
并管理命名共享内存 "GPUZShMem" 的连接。
"""

import ctypes
import mmap
import os
import subprocess
import time
import winreg

from utils.gpuz_structures import GPUZ_SH_MEM
from utils.logger import debug_log, warn_gpuz_not_available
import utils.config as _cfg


# ============================================================================
# GPU-Z 自动搜索 (按优先级逐级搜索)
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
    gpuz_path = _cfg._config.get("gpuz_path", "").strip() if _cfg._config else ""
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
# GPU-Z 进程与共享内存管理
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
