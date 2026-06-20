"""
HardwareMonitor-VRChatOSC

通过 GPU-Z 共享内存读取硬件信息，定时发送至 VRChat 聊天框 (OSC 协议)。

用法:
    python main.py
"""

import os
import platform
import threading
import time

import psutil
import win32gui
import win32process
from pythonosc import udp_client

import utils.config as _cfg
import utils.display_config as _disp_cfg
from utils.gpuz_search import start_gpuz
from utils.gpu_reader import detect_gpu_vendor, get_GPU_info, set_gpu_vendor
from utils.logger import debug_log
from utils.osc_sender import format_osc_message


status_data = {
    "cpu": 0.0, "gpu": 0.0,
    "ram_used": "N/A", "ram_total": "N/A",
    "vram_used": "N/A", "vram_total": "N/A",
    "gpu_name": "GPU", "text": "",
    "window_title": "",
}
data_lock = threading.Lock()


def _get_cpu_name():
    try:
        import wmi
        c = wmi.WMI()
        for p in c.Win32_Processor():
            if p.Name:
                return p.Name.strip()
    except Exception:
        pass
    return platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown")


SYS_CPU = _get_cpu_name()
SYS_RAM = f"{round(psutil.virtual_memory().total / (1024**3))}GB"


def hardware_monitor():
    interval = _cfg._config.get("update_interval", 5) if _cfg._config else 5
    custom_gpu_name = _cfg._config.get("gpu_name", "").strip() if _cfg._config else ""
    custom_vram = _cfg._config.get("vram_total_gb", 0) if _cfg._config else 0
    custom_ram = _cfg._config.get("ram_total_gb", 0) if _cfg._config else 0

    if custom_gpu_name:
        debug_log(f"GPU 名称已覆盖: {custom_gpu_name}", "INFO")
    if custom_vram > 0:
        debug_log(f"显存上限已覆盖: {custom_vram}GB", "INFO")
    if custom_ram > 0:
        debug_log(f"内存上限已覆盖: {custom_ram}GB", "INFO")

    debug_log(f"硬件监控线程已启动 (间隔 {interval}s)", "INFO")

    # ── 报告已关闭的显示项 ──
    if _disp_cfg._display_config:
        off_items = [k for k, v in _disp_cfg._display_config.items() if v == "OFF"]
        if off_items:
            debug_log(f"以下显示项已关闭: {', '.join(off_items)}", "INFO")

    while True:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        ram_used = round(mem.used / (1024 ** 3), 2)
        ram_total = custom_ram if custom_ram > 0 else round(mem.total / (1024 ** 3), 2)

        gpu = get_GPU_info()

        # ── 应用 GPU 名称 / 显存自定义覆盖 ──
        if gpu is not None:
            if custom_gpu_name:
                gpu["CardName"] = custom_gpu_name
            if custom_vram > 0:
                gpu["MemSize"] = custom_vram

        debug_log(f"CPU: {SYS_CPU} | 负载 {cpu_percent:.1f}% | 内存 {ram_used}GB/{ram_total}GB", "DEBUG")
        if gpu is not None:
            debug_log(
                f"GPU: {gpu['CardName']} | "
                f"负载 {gpu['GPU Load']:.1f}% | "
                f"显存 {gpu['Memory Used (Dedicated)']}GB/{gpu['MemSize']}GB",
                "DEBUG",
            )

        # ── 活动窗口检测 ──
        if _disp_cfg._display_config.get("WINDOW", "OFF") == "ON":
            window_title = ""
            window_label = ""
            try:
                hwnd = win32gui.GetForegroundWindow()
                if hwnd:
                    title = win32gui.GetWindowText(hwnd)
                    if title:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        proc_name = psutil.Process(pid).name()
                        if proc_name.lower() == "vrchat.exe":
                            window_title = ""
                            window_label = "VRChat不显示输出"
                        else:
                            t = title[:120] if len(title) > 120 else title
                            window_title = t
                            window_label = t
                    else:
                        window_title = "N/A"
                        window_label = "N/A"
                else:
                    window_title = "N/A"
                    window_label = "N/A"
            except Exception as e:
                debug_log(f"窗口检测失败: {e}", "DEBUG")
        else:
            window_title = ""
            window_label = "(已关闭输出)"

        if window_label:
            debug_log(f"窗口: {window_label}", "DEBUG")

        with data_lock:
            status_data["cpu"] = cpu_percent
            status_data["ram_used"] = ram_used
            status_data["ram_total"] = ram_total
            if gpu is not None:
                status_data["gpu"] = gpu["GPU Load"]
                status_data["vram_used"] = f"{gpu['Memory Used (Dedicated)']}GB" if gpu["Memory Used (Dedicated)"] is not None else "N/A"
                status_data["vram_total"] = f"{gpu['MemSize']}GB" if gpu["MemSize"] is not None else "N/A"
                status_data["gpu_name"] = gpu["CardName"] or "GPU"
            status_data["window_title"] = window_title
        time.sleep(interval)


def send_osc():
    interval = _cfg._config.get("update_interval", 5) if _cfg._config else 5
    osc_ip = _cfg._config.get("osc_ip", "127.0.0.1") if _cfg._config else "127.0.0.1"
    osc_port = _cfg._config.get("osc_port", 9000) if _cfg._config else 9000

    debug_log(f"OSC 发送线程已启动 -> {osc_ip}:{osc_port}", "INFO")
    client = udp_client.SimpleUDPClient(osc_ip, osc_port)

    while True:
        with data_lock:
            data = status_data.copy()
        message = format_osc_message(data, SYS_CPU, _disp_cfg._display_config)
        try:
            client.send_message("/chatbox/input", [message, True])
            debug_log("OSC 消息已发送", "DEBUG")
        except Exception as e:
            debug_log(f"OSC 发送失败 (VRChat 是否运行? OSC 是否启用?): {e}", "WARN")
        time.sleep(interval)


def input_handler():
    debug_log("控制台输入线程就绪", "INFO")
    while True:
        try:
            new_text = input().strip()
            with data_lock:
                status_data["text"] = new_text + " " if new_text else ""
        except EOFError:
            pass
        except Exception as e:
            debug_log(f"输入错误: {e}", "DEBUG")


def run():
    _cfg._config = _cfg.load_config()
    _disp_cfg._display_config = _disp_cfg.load_display_config()

    global SYS_CPU, SYS_RAM

    # ── 自定义名称／数值覆盖 ──
    custom_cpu = _cfg._config.get("cpu_name", "").strip()
    if custom_cpu:
        SYS_CPU = custom_cpu
        debug_log(f"CPU 名称已覆盖: {custom_cpu}", "INFO")

    custom_ram = _cfg._config.get("ram_total_gb", 0)
    if custom_ram > 0:
        SYS_RAM = f"{custom_ram}GB"
        debug_log(f"内存上限已覆盖: {custom_ram}GB", "INFO")

    # ── Banner ──

    print("=" * 60)
    print("  HardwareMonitor-VRChatOSC")
    print("  Hardware Monitor -> VRChat OSC Chatbox")
    print("=" * 60)
    print(f"  CPU:      {SYS_CPU}")
    print(f"  RAM:      {SYS_RAM}")
    print(f"  OSC:      {_cfg._config.get('osc_ip', '127.0.0.1')}:{_cfg._config.get('osc_port', 9000)}")
    print(f"  Interval: {_cfg._config.get('update_interval', 5)}s")
    print(f"  Debug:    {'ON' if _cfg._config.get('debug', True) else 'OFF'}")
    print("=" * 60)

    vendor = detect_gpu_vendor()
    set_gpu_vendor(vendor)
    if vendor == "nvidia":
        print("[INFO] 检测到 NVIDIA GPU，使用 pynvml (无需 GPU-Z)")
    else:
        print("[INFO] 未检测到 NVIDIA GPU 或 pynvml 不可用，使用 GPU-Z 共享内存")

    if vendor == "nvidia":
        print("[INFO] NVIDIA 模式: 跳过 GPU-Z 启动")
    else:
        gpuz_ready = start_gpuz()
        if gpuz_ready:
            print("[INFO] GPU-Z 已就绪，启动硬件监控...\n")
        else:
            print("[INFO] GPU-Z 未就绪，将保持重试\n")

    threading.Thread(target=hardware_monitor, daemon=True, name="HW-Monitor").start()
    threading.Thread(target=send_osc, daemon=True, name="OSC-Sender").start()
    threading.Thread(target=input_handler, daemon=True, name="Input-Handler").start()

    debug_log("全部线程已启动，按 Ctrl+C 退出程序", "INFO")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n程序已退出")


if __name__ == "__main__":
    run()
