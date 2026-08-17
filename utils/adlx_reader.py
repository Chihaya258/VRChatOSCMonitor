"""AMD ADLX GPU metrics reader.

ADLX exposes C-style interface vtables from ``amdadlx64.dll``.  This module
uses the stable part of that ABI through ctypes so the application does not
need GPU-Z or a separately compiled native extension for AMD GPUs.

The vtable slot order and data types are taken from AMD's ADLX SDK headers:
``ISystem.h`` and ``IPerformanceMonitoring.h`` (SDK 1.5).
"""

import atexit
import ctypes
import os
import threading

from utils.logger import debug_log


ADLX_OK = 0
AMD_VENDOR_ID = "1002"

# ADLX_FULL_VERSION for SDK 1.5.0.124.  The runtime-reported version is used
# when available so this reader remains compatible with an installed driver
# whose ADLX runtime is older than the headers used to develop this project.
ADLX_SDK_FULL_VERSION = (1 << 48) | (5 << 32) | 124


class ADLXError(RuntimeError):
    """Raised when the AMD ADLX runtime returns an error."""


def _interface_method(interface, slot, restype, *argtypes):
    """Return an ADLX interface method from its C ABI vtable."""
    if not interface:
        raise ADLXError("ADLX returned an empty interface pointer")

    vtable = ctypes.cast(
        interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
    ).contents
    address = vtable[slot]
    if not address:
        raise ADLXError(f"ADLX interface vtable slot {slot} is null")

    # ADLX interface methods use ADLX_STD_CALL (__stdcall on 32-bit Windows).
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(address)


def _release(interface):
    """Release a reference-counted ADLX interface, ignoring shutdown errors."""
    if interface:
        try:
            _interface_method(interface, 1, ctypes.c_long)(interface)
        except Exception:
            pass


def _decode_adlx_string(value):
    if not value:
        return ""
    try:
        return value.decode("utf-8").strip()
    except UnicodeDecodeError:
        return value.decode(errors="replace").strip()


class ADLXGPUReader:
    """Owns an ADLX session and reads metrics from one AMD GPU."""

    # IADLXSystem slots in SDK/Include/ISystem.h.
    # IADLXSystem is a singleton interface and, unlike most ADLX interfaces,
    # does not inherit IADLXInterface. Its vtable starts directly with
    # GetHybridGraphicsType / GetGPUs.
    _SYSTEM_GET_GPUS = 1
    _SYSTEM_GET_PERFORMANCE_MONITORING = 9

    # IADLXGPUList slots in SDK/Include/ISystem.h.
    _GPU_LIST_SIZE = 3
    _GPU_LIST_AT_GPU = 11

    # IADLXGPU slots in SDK/Include/ISystem.h.
    _GPU_VENDOR_ID = 3
    _GPU_NAME = 7
    _GPU_TOTAL_VRAM = 11

    # IADLXPerformanceMonitoringServices slots in
    # SDK/Include/IPerformanceMonitoring.h.
    _PERF_CURRENT_GPU_METRICS = 18

    # IADLXGPUMetrics slots in SDK/Include/IPerformanceMonitoring.h.
    _METRICS_GPU_USAGE = 4
    _METRICS_GPU_VRAM = 12

    def __init__(self):
        # read() may initialize lazily, so the same thread needs to acquire
        # the lock recursively.
        self._lock = threading.RLock()
        self._dll = None
        self._system = None
        self._performance = None
        self._gpu = None
        self._initialized = False
        self._gpu_name = ""
        self._total_vram_mb = None
        self._closed = False
        atexit.register(self.close)

    @property
    def available(self):
        return self._initialized and self._gpu is not None

    @property
    def gpu_name(self):
        return self._gpu_name

    def initialize(self):
        """Load ADLX, select the configured AMD GPU, and cache static data."""
        with self._lock:
            if self.available:
                return True
            if self._closed:
                return False
            if os.name != "nt":
                debug_log("ADLX 仅支持 Windows，跳过 AMD ADLX 数据源", "WARN")
                return False

            try:
                self._dll = ctypes.CDLL("amdadlx64.dll")
            except OSError as exc:
                debug_log(f"无法加载 AMD ADLX 运行库 amdadlx64.dll: {exc}", "WARN")
                return False

            try:
                self._initialize_runtime()
                self._select_amd_gpu()
                self._initialized = True
                vram = (
                    f"{self._total_vram_mb / 1024:.2f}GB"
                    if self._total_vram_mb is not None
                    else "N/A"
                )
                debug_log(
                    f"ADLX 已连接: {self._gpu_name or 'AMD GPU'} | 总显存 {vram}",
                    "INFO",
                )
                return True
            except Exception as exc:
                debug_log(f"ADLX 初始化失败: {exc}", "WARN")
                self._cleanup_interfaces()
                self._terminate_runtime()
                return False

    def _initialize_runtime(self):
        query_version = self._dll.ADLXQueryFullVersion
        query_version.argtypes = [ctypes.POINTER(ctypes.c_uint64)]
        query_version.restype = ctypes.c_int

        runtime_version = ctypes.c_uint64()
        result = query_version(ctypes.byref(runtime_version))
        if result != ADLX_OK:
            raise ADLXError(f"ADLXQueryFullVersion 返回 {result}")

        # ADLXInitialize is present on older drivers; ADLXInitialize2 was
        # added later and includes an optional ADL mapping output.
        system = ctypes.c_void_p()
        version = runtime_version.value or ADLX_SDK_FULL_VERSION
        try:
            initialize2 = self._dll.ADLXInitialize2
        except AttributeError:
            initialize = self._dll.ADLXInitialize
            initialize.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)]
            initialize.restype = ctypes.c_int
            result = initialize(version, ctypes.byref(system))
        else:
            initialize2.argtypes = [
                ctypes.c_uint64,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_void_p),
            ]
            initialize2.restype = ctypes.c_int
            adl_mapping = ctypes.c_void_p()
            result = initialize2(
                version, ctypes.byref(system), ctypes.byref(adl_mapping)
            )

        if result != ADLX_OK or not system:
            raise ADLXError(f"ADLXInitialize 返回 {result}")
        self._system = system

        performance = ctypes.c_void_p()
        result = _interface_method(
            self._system,
            self._SYSTEM_GET_PERFORMANCE_MONITORING,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        )(self._system, ctypes.byref(performance))
        if result != ADLX_OK or not performance:
            raise ADLXError(
                f"IADLXSystem.GetPerformanceMonitoringServices 返回 {result}"
            )
        self._performance = performance

    def _select_amd_gpu(self):
        gpu_list = ctypes.c_void_p()
        result = _interface_method(
            self._system,
            self._SYSTEM_GET_GPUS,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        )(self._system, ctypes.byref(gpu_list))
        if result != ADLX_OK or not gpu_list:
            raise ADLXError(f"IADLXSystem.GetGPUs 返回 {result}")

        try:
            count = _interface_method(gpu_list, self._GPU_LIST_SIZE, ctypes.c_uint)(
                gpu_list
            )
            for index in range(count):
                gpu = ctypes.c_void_p()
                result = _interface_method(
                    gpu_list,
                    self._GPU_LIST_AT_GPU,
                    ctypes.c_int,
                    ctypes.c_uint,
                    ctypes.POINTER(ctypes.c_void_p),
                )(gpu_list, index, ctypes.byref(gpu))
                if result != ADLX_OK or not gpu:
                    continue

                vendor_id = ctypes.c_char_p()
                result = _interface_method(
                    gpu,
                    self._GPU_VENDOR_ID,
                    ctypes.c_int,
                    ctypes.POINTER(ctypes.c_char_p),
                )(gpu, ctypes.byref(vendor_id))
                if result != ADLX_OK or _decode_adlx_string(vendor_id.value) != AMD_VENDOR_ID:
                    _release(gpu)
                    continue

                self._gpu = gpu
                self._gpu_name = self._read_gpu_name(gpu)
                self._total_vram_mb = self._read_total_vram(gpu)
                return
        finally:
            _release(gpu_list)

        raise ADLXError("ADLX 未发现 AMD GPU")

    def _read_gpu_name(self, gpu):
        name = ctypes.c_char_p()
        result = _interface_method(
            gpu,
            self._GPU_NAME,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_char_p),
        )(gpu, ctypes.byref(name))
        return _decode_adlx_string(name.value) if result == ADLX_OK else "AMD GPU"

    def _read_total_vram(self, gpu):
        vram_mb = ctypes.c_uint()
        result = _interface_method(
            gpu,
            self._GPU_TOTAL_VRAM,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint),
        )(gpu, ctypes.byref(vram_mb))
        return int(vram_mb.value) if result == ADLX_OK else None

    def read(self):
        """Return the GPU fields used by the OSC monitor, or None on failure."""
        with self._lock:
            if not self.available and not self.initialize():
                return None

            metrics = ctypes.c_void_p()
            try:
                result = _interface_method(
                    self._performance,
                    self._PERF_CURRENT_GPU_METRICS,
                    ctypes.c_int,
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_void_p),
                )(self._performance, self._gpu, ctypes.byref(metrics))
                if result != ADLX_OK or not metrics:
                    raise ADLXError(
                        f"GetCurrentGPUMetrics 返回 {result}"
                    )

                usage = ctypes.c_double()
                vram_mb = ctypes.c_int()
                usage_result = _interface_method(
                    metrics,
                    self._METRICS_GPU_USAGE,
                    ctypes.c_int,
                    ctypes.POINTER(ctypes.c_double),
                )(metrics, ctypes.byref(usage))
                vram_result = _interface_method(
                    metrics,
                    self._METRICS_GPU_VRAM,
                    ctypes.c_int,
                    ctypes.POINTER(ctypes.c_int),
                )(metrics, ctypes.byref(vram_mb))

                return {
                    "GPU Load": float(usage.value) if usage_result == ADLX_OK else 0.0,
                    "Memory Used (Dedicated)": (
                        round(vram_mb.value / 1024, 2)
                        if vram_result == ADLX_OK and vram_mb.value >= 0
                        else None
                    ),
                    "MemSize": (
                        round(self._total_vram_mb / 1024, 2)
                        if self._total_vram_mb is not None
                        else None
                    ),
                    "CardName": self._gpu_name or "AMD GPU",
                }
            except Exception as exc:
                debug_log(f"ADLX GPU 数据读取失败: {exc}", "WARN")
                return None
            finally:
                _release(metrics)

    def _cleanup_interfaces(self):
        _release(self._gpu)
        _release(self._performance)
        self._gpu = None
        self._performance = None
        self._system = None
        self._initialized = False

    def _terminate_runtime(self):
        if not self._dll:
            return
        try:
            terminate = self._dll.ADLXTerminate
            terminate.argtypes = []
            terminate.restype = ctypes.c_int
            terminate()
        except (AttributeError, OSError):
            pass

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._cleanup_interfaces()
            self._terminate_runtime()
            self._dll = None
            self._closed = True
