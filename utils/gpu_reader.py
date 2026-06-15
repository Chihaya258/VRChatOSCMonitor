"""
GPU 数据采集模块

负责检测 GPU 厂商并通过 NVML (NVIDIA) 或 GPU-Z 共享内存读取 GPU 硬件信息。
"""

import ctypes
import mmap

from utils.gpuz_structures import GPUZ_SH_MEM
from utils.logger import debug_log
import utils.config as _cfg

try:
    from pynvml import (
        nvmlInit, nvmlShutdown, nvmlDeviceGetCount,
        nvmlDeviceGetHandleByIndex, nvmlDeviceGetBrand,
        nvmlDeviceGetName, nvmlDeviceGetUtilizationRates,
        nvmlDeviceGetMemoryInfo, NVMLError, nvmlSystemGetDriverVersion,
    )
    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False

_gpu_vendor = "unknown"


def set_gpu_vendor(vendor):
    global _gpu_vendor
    _gpu_vendor = vendor


def get_gpu_vendor():
    return _gpu_vendor


def detect_gpu_vendor():
    source = _cfg._config.get("gpu_source", "auto") if _cfg._config else "auto"
    if source == "nvidia":
        if not NVML_AVAILABLE:
            debug_log("gpu_source=nvidia 但 pynvml 未安装，回退到自动检测", "WARN")
        else:
            debug_log("gpu_source=nvidia，强制使用 pynvml", "INFO")
            return "nvidia"
    elif source == "gpuz":
        debug_log("gpu_source=gpuz，强制使用 GPU-Z 共享内存", "INFO")
        return "unknown"

    if not NVML_AVAILABLE:
        debug_log("pynvml 未安装，使用 GPU-Z 共享内存", "INFO")
        return "unknown"

    try:
        nvmlInit()
        device_count = nvmlDeviceGetCount()
        if device_count == 0:
            debug_log("未检测到 NVIDIA GPU (pynvml)", "INFO")
            nvmlShutdown()
            return "unknown"
        try:
            handle = nvmlDeviceGetHandleByIndex(0)
            brand = nvmlDeviceGetBrand(handle)
            brand_names = {0: "Unknown", 1: "GeForce", 2: "Quadro", 3: "Tesla", 4: "NVS", 5: "GRID", 6: "GeForce Now"}
            brand_str = brand_names.get(brand, f"Unknown({brand})")
            gpu_name = nvmlDeviceGetName(handle)
            if isinstance(gpu_name, bytes):
                gpu_name = gpu_name.decode("utf-8")
            debug_log(f"检测到 NVIDIA {brand_str}: {gpu_name}", "INFO")
        except NVMLError:
            debug_log("无法获取 GPU 品牌，但检测到 NVIDIA 设备", "WARN")
        nvmlShutdown()
        return "nvidia"
    except NVMLError as e:
        debug_log(f"pynvml 初始化失败 ({e})，使用 GPU-Z", "WARN")
        return "unknown"
    except Exception as e:
        debug_log(f"GPU 检测异常 ({e})，使用 GPU-Z", "ERROR")
        return "unknown"


_nvml_handle = None
_nvml_initialized = False


def _ensure_nvml_init():
    global _nvml_handle, _nvml_initialized
    if _nvml_initialized and _nvml_handle is not None:
        return _nvml_handle
    if not NVML_AVAILABLE:
        return None
    try:
        nvmlInit()
        _nvml_initialized = True
        device_count = nvmlDeviceGetCount()
        if device_count == 0:
            debug_log("NVML: 未检测到 GPU 设备", "WARN")
            return None
        _nvml_handle = nvmlDeviceGetHandleByIndex(0)
        return _nvml_handle
    except NVMLError as e:
        debug_log(f"NVML 初始化失败: {e}", "ERROR")
        return None


def get_GPU_info_nvidia():
    info = {"GPU Load": 0.0, "Memory Used (Dedicated)": None, "MemSize": None, "CardName": "GPU"}
    handle = _ensure_nvml_init()
    if handle is None:
        return None
    try:
        try:
            name = nvmlDeviceGetName(handle)
            info["CardName"] = name.decode("utf-8") if isinstance(name, bytes) else name
        except NVMLError:
            pass
        try:
            utilization = nvmlDeviceGetUtilizationRates(handle)
            info["GPU Load"] = float(utilization.gpu)
        except NVMLError:
            pass
        try:
            mem_info = nvmlDeviceGetMemoryInfo(handle)
            info["Memory Used (Dedicated)"] = round(mem_info.used / (1024 ** 3), 2)
            info["MemSize"] = round(mem_info.total / (1024 ** 3), 2)
        except NVMLError:
            pass
        return info
    except Exception as e:
        debug_log(f"NVML GPU 读取失败: {e}", "ERROR")
        return None


def get_GPU_info():
    if _gpu_vendor == "nvidia":
        return get_GPU_info_nvidia()

    info = {"GPU Load": 0.0, "Memory Used (Dedicated)": None, "MemSize": None, "CardName": "GPU"}
    shm_size = ctypes.sizeof(GPUZ_SH_MEM)

    try:
        mm = mmap.mmap(-1, shm_size, tagname="GPUZShMem", access=mmap.ACCESS_READ)
    except Exception as e:
        debug_log(f"无法打开 GPU-Z 共享内存: {e}", "WARN")
        return None

    try:
        mm.seek(0)
        raw = mm.read(shm_size)
        gpuz = GPUZ_SH_MEM.from_buffer_copy(raw)

        for record in gpuz.data:
            key = record.key
            if key == "MemSize":
                info["MemSize"] = round(int(record.value) / 1024, 2)
            elif key == "CardName":
                info["CardName"] = record.value

        for sensor in gpuz.sensors:
            name = sensor.name
            if name == "Memory Used (Dedicated)":
                info["Memory Used (Dedicated)"] = round(int(sensor.value) / 1024, 2)
            elif name == "GPU Load":
                info[name] = sensor.value

        return info
    except Exception as e:
        debug_log(f"GPU 共享内存解析失败: {e}", "ERROR")
        return None
    finally:
        mm.close()
