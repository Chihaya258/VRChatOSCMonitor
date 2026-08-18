"""Read VRChat's presentation rate with built-in Windows ETW APIs.

The module uses ``ctypes`` and Windows APIs already present on Windows 10/11.
It does not start SteamVR, load OpenVR, inject into VRChat, or require a
vendor SDK / external monitoring application.
"""

import atexit
import ctypes
from collections import deque
import os
import threading
import time
import uuid

import psutil

from utils.logger import debug_log


# Microsoft-Windows-DxgKrnl.  The Present keyword and task are exposed by the
# provider manifest installed with Windows.
_DXGKRNL_PROVIDER = uuid.UUID("802ec45a-1e99-4b83-9920-87c98277ba9d")
_DXGKRNL_PRESENT_KEYWORD = 0x08000000
_DXGKRNL_PRESENT_TASK = 107
_DXGKRNL_PRESENT_EVENT_ID = 184

_ERROR_SUCCESS = 0
_ERROR_ALREADY_EXISTS = 183
_ERROR_ACCESS_DENIED = 5
_INVALID_PROCESSTRACE_HANDLE = ctypes.c_uint64(-1).value

_EVENT_TRACE_REAL_TIME_MODE = 0x00000100
_EVENT_TRACE_CONTROL_STOP = 1
_EVENT_CONTROL_CODE_ENABLE_PROVIDER = 1
_TRACE_LEVEL_VERBOSE = 5

_PROCESS_TRACE_MODE_REAL_TIME = 0x00000100
_PROCESS_TRACE_MODE_EVENT_RECORD = 0x10000000

_FILETIME_UNIX_EPOCH_OFFSET = 11644473600
_HUNDRED_NANOSECONDS_PER_SECOND = 10_000_000


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_uuid(cls, value):
        result = cls()
        ctypes.memmove(ctypes.byref(result), value.bytes_le, ctypes.sizeof(result))
        return result


class _WNODE_HEADER(ctypes.Structure):
    _fields_ = [
        ("BufferSize", ctypes.c_uint32),
        ("ProviderId", ctypes.c_uint32),
        ("HistoricalContext", ctypes.c_uint64),
        ("TimeStamp", ctypes.c_int64),
        ("Guid", _GUID),
        ("ClientContext", ctypes.c_uint32),
        ("Flags", ctypes.c_uint32),
    ]


class _EVENT_TRACE_PROPERTIES(ctypes.Structure):
    _fields_ = [
        ("Wnode", _WNODE_HEADER),
        ("BufferSize", ctypes.c_uint32),
        ("MinimumBuffers", ctypes.c_uint32),
        ("MaximumBuffers", ctypes.c_uint32),
        ("MaximumFileSize", ctypes.c_uint32),
        ("LogFileMode", ctypes.c_uint32),
        ("FlushTimer", ctypes.c_uint32),
        ("EnableFlags", ctypes.c_uint32),
        ("AgeLimit", ctypes.c_int32),
        ("NumberOfBuffers", ctypes.c_uint32),
        ("FreeBuffers", ctypes.c_uint32),
        ("EventsLost", ctypes.c_uint32),
        ("BuffersWritten", ctypes.c_uint32),
        ("LogBuffersLost", ctypes.c_uint32),
        ("RealTimeBuffersLost", ctypes.c_uint32),
        ("LoggerThreadId", ctypes.c_void_p),
        ("LogFileNameOffset", ctypes.c_uint32),
        ("LoggerNameOffset", ctypes.c_uint32),
    ]


class _EVENT_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("Id", ctypes.c_uint16),
        ("Version", ctypes.c_ubyte),
        ("Channel", ctypes.c_ubyte),
        ("Level", ctypes.c_ubyte),
        ("Opcode", ctypes.c_ubyte),
        ("Task", ctypes.c_uint16),
        ("Keyword", ctypes.c_uint64),
    ]


class _EVENT_HEADER(ctypes.Structure):
    _fields_ = [
        ("Size", ctypes.c_uint16),
        ("HeaderType", ctypes.c_uint16),
        ("Flags", ctypes.c_uint16),
        ("EventProperty", ctypes.c_uint16),
        ("ThreadId", ctypes.c_uint32),
        ("ProcessId", ctypes.c_uint32),
        ("TimeStamp", ctypes.c_int64),
        ("ProviderId", _GUID),
        ("EventDescriptor", _EVENT_DESCRIPTOR),
        ("ProcessorTime", ctypes.c_uint64),
        ("ActivityId", _GUID),
    ]


class _ETW_BUFFER_CONTEXT(ctypes.Structure):
    _fields_ = [
        ("ProcessorNumber", ctypes.c_ubyte),
        ("Alignment", ctypes.c_ubyte),
        ("LoggerId", ctypes.c_uint16),
    ]


class _EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("EventHeader", _EVENT_HEADER),
        ("BufferContext", _ETW_BUFFER_CONTEXT),
        ("ExtendedDataCount", ctypes.c_uint16),
        ("UserDataLength", ctypes.c_uint16),
        ("ExtendedData", ctypes.c_void_p),
        ("UserData", ctypes.c_void_p),
        ("UserContext", ctypes.c_void_p),
    ]


class _EVENT_TRACE_HEADER(ctypes.Structure):
    _fields_ = [
        ("Size", ctypes.c_uint16),
        ("FieldTypeFlags", ctypes.c_uint16),
        ("Version", ctypes.c_uint32),
        ("ThreadId", ctypes.c_uint32),
        ("ProcessId", ctypes.c_uint32),
        ("TimeStamp", ctypes.c_int64),
        ("Guid", _GUID),
        ("ProcessorTime", ctypes.c_uint64),
    ]


class _EVENT_TRACE(ctypes.Structure):
    _fields_ = [
        ("Header", _EVENT_TRACE_HEADER),
        ("InstanceId", ctypes.c_uint32),
        ("ParentInstanceId", ctypes.c_uint32),
        ("ParentGuid", _GUID),
        ("MofData", ctypes.c_void_p),
        ("MofLength", ctypes.c_uint32),
        ("ClientContext", ctypes.c_uint32),
    ]


class _SYSTEMTIME(ctypes.Structure):
    _fields_ = [
        ("wYear", ctypes.c_uint16),
        ("wMonth", ctypes.c_uint16),
        ("wDayOfWeek", ctypes.c_uint16),
        ("wDay", ctypes.c_uint16),
        ("wHour", ctypes.c_uint16),
        ("wMinute", ctypes.c_uint16),
        ("wSecond", ctypes.c_uint16),
        ("wMilliseconds", ctypes.c_uint16),
    ]


class _TIME_ZONE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Bias", ctypes.c_int32),
        ("StandardName", ctypes.c_wchar * 32),
        ("StandardDate", _SYSTEMTIME),
        ("StandardBias", ctypes.c_int32),
        ("DaylightName", ctypes.c_wchar * 32),
        ("DaylightDate", _SYSTEMTIME),
        ("DaylightBias", ctypes.c_int32),
    ]


class _TRACE_LOGFILE_HEADER(ctypes.Structure):
    _fields_ = [
        ("BufferSize", ctypes.c_uint32),
        ("Version", ctypes.c_uint32),
        ("ProviderVersion", ctypes.c_uint32),
        ("NumberOfProcessors", ctypes.c_uint32),
        ("EndTime", ctypes.c_int64),
        ("TimerResolution", ctypes.c_uint32),
        ("MaximumFileSize", ctypes.c_uint32),
        ("LogFileMode", ctypes.c_uint32),
        ("BuffersWritten", ctypes.c_uint32),
        ("LogInstanceGuid", _GUID),
        ("LoggerName", ctypes.c_wchar_p),
        ("LogFileName", ctypes.c_wchar_p),
        ("TimeZone", _TIME_ZONE_INFORMATION),
        ("BootTime", ctypes.c_int64),
        ("PerfFreq", ctypes.c_int64),
        ("StartTime", ctypes.c_int64),
        ("ReservedFlags", ctypes.c_uint32),
        ("BuffersLost", ctypes.c_uint32),
    ]


_EVENT_RECORD_CALLBACK = ctypes.WINFUNCTYPE(None, ctypes.POINTER(_EVENT_RECORD))


class _EVENT_TRACE_LOGFILEW(ctypes.Structure):
    _fields_ = [
        ("LogFileName", ctypes.c_wchar_p),
        ("LoggerName", ctypes.c_wchar_p),
        ("CurrentTime", ctypes.c_int64),
        ("BuffersRead", ctypes.c_uint32),
        ("ProcessTraceMode", ctypes.c_uint32),
        ("CurrentEvent", _EVENT_TRACE),
        ("LogfileHeader", _TRACE_LOGFILE_HEADER),
        ("BufferCallback", ctypes.c_void_p),
        ("BufferSize", ctypes.c_uint32),
        ("Filled", ctypes.c_uint32),
        ("EventsLost", ctypes.c_uint32),
        ("EventRecordCallback", _EVENT_RECORD_CALLBACK),
        ("IsKernelTrace", ctypes.c_uint32),
        ("Context", ctypes.c_void_p),
    ]


class VRChatFPSReader:
    """Continuously calculate VRChat's Windows graphics Present rate."""

    _SAMPLE_WINDOW_SECONDS = 2.0
    _STALE_AFTER_SECONDS = 2.5
    _PROCESS_REFRESH_SECONDS = 1.0

    def __init__(self):
        self._lock = threading.RLock()
        self._frames = deque()
        self._target_pids = set()
        self._last_process_refresh = 0.0
        self._status = "等待 VRChat 帧数据"
        self._last_log_key = None
        self._closed = False
        self._started = False
        self._session_handle = ctypes.c_uint64()
        self._trace_handle = ctypes.c_uint64(_INVALID_PROCESSTRACE_HANDLE)
        self._session_name = f"VRChatOSCMonitor-FPS-{os.getpid()}"
        self._session_name_buffer = None
        self._properties_buffer = None
        self._properties = None
        self._callback = _EVENT_RECORD_CALLBACK(self._on_event)
        self._consumer_thread = None
        self._advapi32 = None
        self._provider_guid = _GUID.from_uuid(_DXGKRNL_PROVIDER)
        atexit.register(self.close)

    @property
    def status(self):
        with self._lock:
            return self._status

    def _set_status(self, status):
        self._status = status

    def _log_once(self, key, message, level="DEBUG"):
        if self._last_log_key != key:
            debug_log(message, level)
            self._last_log_key = key

    @staticmethod
    def _guid_equal(left, right):
        return bytes(left) == bytes(right)

    @staticmethod
    def _filetime_now():
        return int(
            (time.time() + _FILETIME_UNIX_EPOCH_OFFSET)
            * _HUNDRED_NANOSECONDS_PER_SECOND
        )

    def _refresh_target_pids(self, force=False):
        now = time.monotonic()
        if not force and now - self._last_process_refresh < self._PROCESS_REFRESH_SECONDS:
            return

        pids = set()
        try:
            for process in psutil.process_iter(["name"]):
                if (process.info.get("name") or "").lower() == "vrchat.exe":
                    pids.add(process.pid)
        except (psutil.Error, OSError):
            pass

        with self._lock:
            previous = self._target_pids
            self._target_pids = pids
            self._last_process_refresh = now
            if pids != previous:
                self._frames.clear()
            if not pids:
                self._set_status("等待 VRChat 启动")
            elif not self._frames:
                self._set_status("等待 VRChat 帧数据")

    def _build_properties(self):
        name_size = (len(self._session_name) + 1) * ctypes.sizeof(ctypes.c_wchar)
        total_size = ctypes.sizeof(_EVENT_TRACE_PROPERTIES) + name_size
        buffer = ctypes.create_string_buffer(total_size)
        properties = ctypes.cast(
            buffer, ctypes.POINTER(_EVENT_TRACE_PROPERTIES)
        ).contents
        properties.Wnode.BufferSize = total_size
        properties.Wnode.ClientContext = 2  # System-time FILETIME timestamps.
        properties.Wnode.Flags = 0x00020000  # WNODE_FLAG_TRACED_GUID
        properties.LogFileMode = _EVENT_TRACE_REAL_TIME_MODE
        properties.BufferSize = 64
        properties.MinimumBuffers = 5
        properties.MaximumBuffers = 32
        properties.FlushTimer = 1
        properties.LoggerNameOffset = ctypes.sizeof(_EVENT_TRACE_PROPERTIES)
        name_address = ctypes.addressof(buffer) + properties.LoggerNameOffset
        ctypes.memmove(
            name_address,
            ctypes.create_unicode_buffer(self._session_name),
            name_size,
        )
        self._properties_buffer = buffer
        self._properties = properties

    def _configure_api(self):
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._advapi32.StartTraceW.argtypes = [
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_wchar_p,
            ctypes.POINTER(_EVENT_TRACE_PROPERTIES),
        ]
        self._advapi32.StartTraceW.restype = ctypes.c_uint32
        self._advapi32.EnableTraceEx2.argtypes = [
            ctypes.c_uint64,
            ctypes.POINTER(_GUID),
            ctypes.c_uint32,
            ctypes.c_ubyte,
            ctypes.c_uint64,
            ctypes.c_uint64,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        self._advapi32.EnableTraceEx2.restype = ctypes.c_uint32
        self._advapi32.OpenTraceW.argtypes = [ctypes.POINTER(_EVENT_TRACE_LOGFILEW)]
        self._advapi32.OpenTraceW.restype = ctypes.c_uint64
        self._advapi32.ProcessTrace.argtypes = [
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._advapi32.ProcessTrace.restype = ctypes.c_uint32
        self._advapi32.CloseTrace.argtypes = [ctypes.c_uint64]
        self._advapi32.CloseTrace.restype = ctypes.c_uint32
        self._advapi32.ControlTraceW.argtypes = [
            ctypes.c_uint64,
            ctypes.c_wchar_p,
            ctypes.POINTER(_EVENT_TRACE_PROPERTIES),
            ctypes.c_uint32,
        ]
        self._advapi32.ControlTraceW.restype = ctypes.c_uint32

    def _on_event(self, event_record):
        try:
            header = event_record.contents.EventHeader
            descriptor = header.EventDescriptor
            if (
                descriptor.Task != _DXGKRNL_PRESENT_TASK
                # Event 184 is the DxgKrnl Present event emitted once for each
                # application frame. Other events using the Present keyword
                # track queues, overlays, and compositor internals instead.
                or descriptor.Id != _DXGKRNL_PRESENT_EVENT_ID
                or not self._guid_equal(header.ProviderId, self._provider_guid)
            ):
                return

            with self._lock:
                if header.ProcessId not in self._target_pids:
                    return
                self._frames.append(int(header.TimeStamp))
        except Exception:
            # Exceptions must never escape a ctypes callback into ETW.
            return

    def _consume(self):
        result = self._advapi32.ProcessTrace(
            ctypes.byref(self._trace_handle), 1, None, None
        )
        if not self._closed and result != _ERROR_SUCCESS:
            with self._lock:
                self._set_status("Windows 图形追踪已停止")
            self._log_once(
                "process-trace-failed",
                f"ETW graphics trace stopped (error {result})",
                "WARN",
            )

    def start(self):
        with self._lock:
            if self._started:
                return True
            if self._closed or os.name != "nt":
                self._set_status("Windows ETW 不可用")
                return False

            try:
                self._configure_api()
                self._build_properties()
                self._session_name_buffer = ctypes.create_unicode_buffer(
                    self._session_name
                )
                result = self._advapi32.StartTraceW(
                    ctypes.byref(self._session_handle),
                    self._session_name_buffer,
                    ctypes.byref(self._properties),
                )
                if result == _ERROR_ALREADY_EXISTS:
                    raise RuntimeError("A trace session with this name already exists")
                if result != _ERROR_SUCCESS:
                    raise OSError(result, "StartTraceW failed")

                result = self._advapi32.EnableTraceEx2(
                    self._session_handle,
                    ctypes.byref(self._provider_guid),
                    _EVENT_CONTROL_CODE_ENABLE_PROVIDER,
                    _TRACE_LEVEL_VERBOSE,
                    _DXGKRNL_PRESENT_KEYWORD,
                    0,
                    0,
                    None,
                )
                if result != _ERROR_SUCCESS:
                    raise OSError(result, "EnableTraceEx2 failed")

                logfile = _EVENT_TRACE_LOGFILEW()
                logfile.LoggerName = ctypes.cast(
                    self._session_name_buffer, ctypes.c_wchar_p
                )
                logfile.ProcessTraceMode = (
                    _PROCESS_TRACE_MODE_REAL_TIME
                    | _PROCESS_TRACE_MODE_EVENT_RECORD
                )
                logfile.EventRecordCallback = self._callback
                trace_handle = self._advapi32.OpenTraceW(ctypes.byref(logfile))
                if trace_handle == _INVALID_PROCESSTRACE_HANDLE:
                    raise OSError(ctypes.get_last_error(), "OpenTraceW failed")

                self._trace_handle = ctypes.c_uint64(trace_handle)
                self._started = True
                self._refresh_target_pids(force=True)
                self._consumer_thread = threading.Thread(
                    target=self._consume,
                    daemon=True,
                    name="VRChat-ETW-FPS",
                )
                self._consumer_thread.start()
                self._last_log_key = None
                debug_log(
                    "Windows ETW FPS monitor started (no SteamVR dependency)",
                    "INFO",
                )
                return True
            except OSError as exc:
                code = exc.errno
                self._stop_session()
                if code == _ERROR_ACCESS_DENIED:
                    self._set_status("ETW 权限不足，请以管理员身份运行")
                    self._log_once(
                        "etw-access-denied",
                        "ETW FPS monitor needs administrator rights or Performance Log Users membership",
                        "WARN",
                    )
                else:
                    self._set_status("Windows ETW FPS 监控不可用")
                    self._log_once(
                        "etw-start-failed",
                        f"Unable to start ETW FPS monitor: {exc}",
                        "WARN",
                    )
                return False
            except Exception as exc:
                self._stop_session()
                self._set_status("Windows ETW FPS 监控不可用")
                self._log_once(
                    "etw-start-failed",
                    f"Unable to start ETW FPS monitor: {exc}",
                    "WARN",
                )
                return False

    def _stop_session(self):
        if self._advapi32 is not None and self._session_handle.value:
            try:
                self._advapi32.ControlTraceW(
                    self._session_handle,
                    self._session_name,
                    ctypes.byref(self._properties),
                    _EVENT_TRACE_CONTROL_STOP,
                )
            except (OSError, ctypes.ArgumentError):
                pass
        self._session_handle = ctypes.c_uint64()

    def read(self):
        """Return VRChat's app Present FPS, or ``None`` while unavailable."""
        if not self._started and not self.start():
            return None

        self._refresh_target_pids()
        now = self._filetime_now()
        oldest = now - int(
            self._SAMPLE_WINDOW_SECONDS * _HUNDRED_NANOSECONDS_PER_SECOND
        )

        with self._lock:
            while self._frames and self._frames[0] < oldest:
                self._frames.popleft()

            if not self._target_pids:
                return None
            if not self._frames:
                self._set_status("等待 VRChat 帧数据")
                return None

            latest = self._frames[-1]
            if now - latest > int(
                self._STALE_AFTER_SECONDS * _HUNDRED_NANOSECONDS_PER_SECOND
            ):
                self._set_status("VRChat 未提交图形帧")
                return None

            if len(self._frames) < 2:
                self._set_status("正在收集 VRChat 帧样本")
                return None

            elapsed = (latest - self._frames[0]) / _HUNDRED_NANOSECONDS_PER_SECOND
            if elapsed <= 0:
                return None
            fps = (len(self._frames) - 1) / elapsed
            if not 0.1 <= fps <= 1000:
                self._set_status("VRChat 帧数据无效")
                return None

            self._set_status("")
            self._last_log_key = None
            return {
                "FPS": round(fps, 1),
                "Frame Time (ms)": round(1000.0 / fps, 2),
            }

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True

            if self._trace_handle.value != _INVALID_PROCESSTRACE_HANDLE:
                try:
                    self._advapi32.CloseTrace(self._trace_handle)
                except (OSError, ctypes.ArgumentError, AttributeError):
                    pass
                self._trace_handle = ctypes.c_uint64(_INVALID_PROCESSTRACE_HANDLE)

            self._stop_session()
            self._started = False
