"""
日志系统模块

提供统一的带级别、带时间戳的日志输出功能。
支持 INFO / DEBUG / WARN / ERROR 四个级别。
"""

import os
import sys
import time

from utils.config import GPUZ_DOWNLOAD_URL
import utils.config as _cfg


# ============================================================================
# 日志系统
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
    if _cfg._config is not None and not _cfg._config.get("debug", True) and level == "DEBUG":
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
