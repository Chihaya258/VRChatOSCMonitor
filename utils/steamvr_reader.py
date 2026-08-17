"""SteamVR/OpenVR frame-timing reader.

Reads the active VR application's frame interval from SteamVR's official
OpenVR compositor interface.  The implementation uses ``ctypes`` and the
``openvr_api.dll`` installed with SteamVR, so it does not add a Python package
dependency or inject into VRChat.
"""

import atexit
import ctypes
import os
import threading
import time

import psutil

from utils.logger import debug_log


VR_APPLICATION_BACKGROUND = 3
VR_INIT_ERROR_NONE = 0
IVR_COMPOSITOR_VERSION = b"FnTable:IVRCompositor_029"
STEAMVR_PROCESS_NAMES = {"vrserver.exe", "vrcompositor.exe"}


class _HmdMatrix34(ctypes.Structure):
    _fields_ = [("m", (ctypes.c_float * 4) * 3)]


class _HmdVector3(ctypes.Structure):
    _fields_ = [("v", ctypes.c_float * 3)]


class _TrackedDevicePose(ctypes.Structure):
    _fields_ = [
        ("mDeviceToAbsoluteTracking", _HmdMatrix34),
        ("vVelocity", _HmdVector3),
        ("vAngularVelocity", _HmdVector3),
        ("eTrackingResult", ctypes.c_int),
        ("bPoseIsValid", ctypes.c_bool),
        ("bDeviceIsConnected", ctypes.c_bool),
    ]


class _CompositorFrameTiming(ctypes.Structure):
    """ABI-compatible ``vr::Compositor_FrameTiming`` from OpenVR 1.27."""

    _fields_ = [
        ("m_nSize", ctypes.c_uint32),
        ("m_nFrameIndex", ctypes.c_uint32),
        ("m_nNumFramePresents", ctypes.c_uint32),
        ("m_nNumMisPresented", ctypes.c_uint32),
        ("m_nNumDroppedFrames", ctypes.c_uint32),
        ("m_nReprojectionFlags", ctypes.c_uint32),
        ("m_flSystemTimeInSeconds", ctypes.c_double),
        ("m_flPreSubmitGpuMs", ctypes.c_float),
        ("m_flPostSubmitGpuMs", ctypes.c_float),
        ("m_flTotalRenderGpuMs", ctypes.c_float),
        ("m_flCompositorRenderGpuMs", ctypes.c_float),
        ("m_flCompositorRenderCpuMs", ctypes.c_float),
        ("m_flCompositorIdleCpuMs", ctypes.c_float),
        ("m_flClientFrameIntervalMs", ctypes.c_float),
        ("m_flPresentCallCpuMs", ctypes.c_float),
        ("m_flWaitForPresentCpuMs", ctypes.c_float),
        ("m_flSubmitFrameMs", ctypes.c_float),
        ("m_flWaitGetPosesCalledMs", ctypes.c_float),
        ("m_flNewPosesReadyMs", ctypes.c_float),
        ("m_flNewFrameReadyMs", ctypes.c_float),
        ("m_flCompositorUpdateStartMs", ctypes.c_float),
        ("m_flCompositorUpdateEndMs", ctypes.c_float),
        ("m_flCompositorRenderStartMs", ctypes.c_float),
        ("m_HmdPose", _TrackedDevicePose),
        ("m_nNumVSyncsReadyForUse", ctypes.c_uint32),
        ("m_nNumVSyncsToFirstView", ctypes.c_uint32),
        ("m_flTransferLatencyMs", ctypes.c_float),
    ]


# ``FnTable:IVRCompositor_029`` contains C-callable stdcall wrappers.  Only
# the fields through GetFrameTiming are needed here.
_GetFrameTiming = ctypes.WINFUNCTYPE(
    ctypes.c_bool,
    ctypes.POINTER(_CompositorFrameTiming),
    ctypes.c_uint32,
)


class _IVRCompositorFnTable(ctypes.Structure):
    _fields_ = [
        ("SetTrackingSpace", ctypes.c_void_p),
        ("GetTrackingSpace", ctypes.c_void_p),
        ("WaitGetPoses", ctypes.c_void_p),
        ("GetLastPoses", ctypes.c_void_p),
        ("GetLastPoseForTrackedDeviceIndex", ctypes.c_void_p),
        # IVRCompositor_029 added these texture-submit entries before the
        # timing methods.  Omitting them shifts GetFrameTiming by three
        # slots; the old layout was therefore calling
        # ClearLastSubmittedFrame and reading an untouched timing struct.
        ("GetSubmitTexture", ctypes.c_void_p),
        ("Submit", ctypes.c_void_p),
        ("SubmitWithArrayIndex", ctypes.c_void_p),
        ("ClearLastSubmittedFrame", ctypes.c_void_p),
        ("PostPresentHandoff", ctypes.c_void_p),
        ("GetFrameTiming", _GetFrameTiming),
    ]


class SteamVRFPSReader:
    """Owns a background OpenVR session and reads the active app's FPS."""

    _RETRY_INTERVAL_SECONDS = 10.0

    def __init__(self):
        self._lock = threading.RLock()
        self._dll = None
        self._compositor = None
        self._initialized = False
        self._session_started = False
        self._closed = False
        self._last_attempt = 0.0
        self._last_log_key = None
        self._last_frame_index = None
        self._last_sample_time = None
        self._status = "等待 SteamVR 帧数据"
        atexit.register(self.close)

    @property
    def available(self):
        return self._initialized and self._compositor is not None

    @property
    def status(self):
        """Human-readable state used when the OSC FPS row has no value yet."""
        with self._lock:
            return self._status

    def _set_status(self, status):
        self._status = status

    def _log_once(self, key, message, level="DEBUG"):
        if self._last_log_key != key:
            debug_log(message, level)
            self._last_log_key = key

    @staticmethod
    def _steamvr_is_running():
        try:
            for process in psutil.process_iter(["name"]):
                name = (process.info.get("name") or "").lower()
                if name in STEAMVR_PROCESS_NAMES:
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _steam_install_paths():
        paths = []
        try:
            import winreg

            registry_keys = (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
            )
            for hive, key, value in registry_keys:
                try:
                    with winreg.OpenKey(hive, key) as handle:
                        path, _ = winreg.QueryValueEx(handle, value)
                    if path:
                        paths.append(os.path.expandvars(path))
                except OSError:
                    continue
        except ImportError:
            pass

        program_files = os.environ.get("ProgramFiles(x86)")
        if program_files:
            paths.append(os.path.join(program_files, "Steam"))
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            paths.append(os.path.join(program_files, "Steam"))

        # Preserve order while ignoring duplicate paths from the registry.
        return list(dict.fromkeys(os.path.normpath(path) for path in paths))

    @classmethod
    def _find_openvr_dll(cls):
        configured_path = os.environ.get("OPENVR_API_DLL", "").strip()
        if configured_path and os.path.isfile(configured_path):
            return configured_path

        architecture = "win64" if ctypes.sizeof(ctypes.c_void_p) == 8 else "win32"
        for steam_path in cls._steam_install_paths():
            candidates = (
                os.path.join(
                    steam_path,
                    "steamapps",
                    "common",
                    "SteamVR",
                    "bin",
                    architecture,
                    "openvr_api.dll",
                ),
                os.path.join(steam_path, "openvr_api.dll"),
            )
            for candidate in candidates:
                if os.path.isfile(candidate):
                    return candidate
        return None

    def _describe_init_error(self, error):
        try:
            describe = self._dll.VR_GetVRInitErrorAsEnglishDescription
            describe.argtypes = [ctypes.c_int]
            describe.restype = ctypes.c_char_p
            message = describe(error)
            if message:
                return message.decode("utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
        return f"错误码 {error}"

    def initialize(self):
        """Attach to an already-running SteamVR instance without launching it."""
        with self._lock:
            if self.available:
                return True
            if self._closed or os.name != "nt":
                return False

            now = time.monotonic()
            if now - self._last_attempt < self._RETRY_INTERVAL_SECONDS:
                return False
            self._last_attempt = now

            if not self._steamvr_is_running():
                self._set_status("SteamVR 未运行")
                self._log_once(
                    "steamvr-not-running",
                    "SteamVR 未运行，暂不读取 VR 应用 FPS",
                    "DEBUG",
                )
                return False

            dll_path = self._find_openvr_dll()
            if not dll_path:
                self._set_status("未找到 SteamVR 接口")
                self._log_once(
                    "openvr-dll-not-found",
                    "SteamVR 正在运行，但未找到 openvr_api.dll",
                    "WARN",
                )
                return False

            try:
                self._dll = ctypes.CDLL(dll_path)
                initialize = self._dll.VR_InitInternal
                initialize.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
                initialize.restype = ctypes.c_uint32

                init_error = ctypes.c_int()
                initialize(
                    ctypes.byref(init_error),
                    VR_APPLICATION_BACKGROUND,
                )
                if init_error.value != VR_INIT_ERROR_NONE:
                    raise RuntimeError(self._describe_init_error(init_error.value))
                self._session_started = True

                get_interface = self._dll.VR_GetGenericInterface
                get_interface.argtypes = [
                    ctypes.c_char_p,
                    ctypes.POINTER(ctypes.c_int),
                ]
                get_interface.restype = ctypes.c_void_p

                interface_error = ctypes.c_int()
                interface = get_interface(
                    IVR_COMPOSITOR_VERSION,
                    ctypes.byref(interface_error),
                )
                if not interface or interface_error.value != VR_INIT_ERROR_NONE:
                    raise RuntimeError(
                        "无法获取 IVRCompositor_029 "
                        f"({self._describe_init_error(interface_error.value)})"
                    )

                self._compositor = ctypes.cast(
                    interface,
                    ctypes.POINTER(_IVRCompositorFnTable),
                ).contents
                self._initialized = True
                self._set_status("等待 VR 应用帧数据")
                self._last_log_key = None
                debug_log("SteamVR 已连接，开始读取 VR 应用 FPS", "INFO")
                return True
            except Exception as exc:
                self._set_status("SteamVR 初始化失败")
                self._log_once("steamvr-init-failed", f"SteamVR FPS 初始化失败: {exc}", "WARN")
                self._shutdown_session()
                return False

    def _shutdown_session(self):
        if self._session_started and self._dll:
            try:
                shutdown = self._dll.VR_ShutdownInternal
                shutdown.argtypes = []
                shutdown.restype = None
                shutdown()
            except (AttributeError, OSError):
                pass
        self._compositor = None
        self._initialized = False
        self._session_started = False
        self._last_frame_index = None
        self._last_sample_time = None

    def _calculate_fps(self, timing):
        frame_interval_ms = float(timing.m_flClientFrameIntervalMs)
        if 0.1 <= frame_interval_ms <= 10_000:
            return round(1000.0 / frame_interval_ms, 1), round(frame_interval_ms, 2)

        # Usually m_flClientFrameIntervalMs is populated.  This fallback keeps
        # the feature useful for runtimes that omit it.
        now = time.monotonic()
        fps = None
        if (
            self._last_frame_index is not None
            and self._last_sample_time is not None
            and timing.m_nFrameIndex > self._last_frame_index
        ):
            elapsed = now - self._last_sample_time
            if elapsed > 0:
                fps = (timing.m_nFrameIndex - self._last_frame_index) / elapsed

        self._last_frame_index = timing.m_nFrameIndex
        self._last_sample_time = now
        if fps is not None and 0.1 <= fps <= 1_000:
            return round(fps, 1), None
        return None, None

    def read(self):
        """Return current VR application FPS data, or ``None`` if unavailable."""
        with self._lock:
            if not self.available and not self.initialize():
                return None

            timing = _CompositorFrameTiming()
            timing.m_nSize = ctypes.sizeof(_CompositorFrameTiming)
            try:
                if not self._compositor.GetFrameTiming(ctypes.byref(timing), 0):
                    self._set_status("SteamVR 无帧数据")
                    self._log_once(
                        "frame-timing-unavailable",
                        "SteamVR 暂无可用的 VR 应用帧时序数据",
                        "DEBUG",
                    )
                    return None

                fps, frame_time_ms = self._calculate_fps(timing)
                if fps is None:
                    self._set_status("SteamVR 无应用帧数据")
                    return None

                self._set_status("已读取")
                self._last_log_key = None
                return {
                    "FPS": fps,
                    "Frame Time (ms)": frame_time_ms,
                    "Frame Index": int(timing.m_nFrameIndex),
                    "Dropped Frames": int(timing.m_nNumDroppedFrames),
                    "Frame Presents": int(timing.m_nNumFramePresents),
                }
            except Exception as exc:
                self._log_once(
                    "frame-timing-read-failed",
                    f"SteamVR FPS 数据读取失败: {exc}",
                    "WARN",
                )
                return None

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._shutdown_session()
            self._dll = None
            self._closed = True
