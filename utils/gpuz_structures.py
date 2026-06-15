"""
GPU-Z 共享内存结构体模块

定义与 GPU-Z 内部 SH_MEM 布局一一对应的 ctypes 结构体。
通过命名共享内存 "GPUZShMem" 映射这些结构体来读取传感器数据。
"""

import ctypes


# ============================================================================
# GPU-Z 共享内存结构体 (与 GPU-Z 内部 SH_MEM 布局一一对应)
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
