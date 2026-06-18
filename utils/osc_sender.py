"""
OSC 消息格式化模块

负责将硬件状态数据组装为 VRChat 聊天框格式的多行消息文本。
提供设备名称精简功能，去除冗长的厂商前缀和冗余信息。
"""

import re


def simplify_cpu_name(name):
    """从完整 CPU 名称中提取型号标识。

    处理常见格式：
      Intel: "Intel(R) Core(TM) i7-13700K CPU @ 3.40GHz"  → "i7-13700K"
             "Intel(R) Core(TM) Ultra 7 155H CPU @ 3.80GHz" → "Ultra 7 155H"
             "Intel(R) Xeon(R) Gold 6248R CPU @ 3.00GHz"    → "Gold 6248R"
      AMD:   "AMD Ryzen 7 7800X3D 8-Core Processor"         → "7800X3D"
             "AMD Ryzen Threadripper 7980X 64-Core Processor" → "7980X"

    Args:
        name: 原始 CPU 名称字符串

    Returns:
        str: 精简后的型号标识
    """
    cleaned = re.sub(r'\([Rr]\)|\([Tt][Mm]\)|\(tm\)', '', name).strip()

    patterns = [
        r'\bCore\s+(Ultra\s+\d+\s+\w+)',
        r'\bCore\s+(i[3-9]-\w+)',
        r'\bXeon\s+(\w+\s+\w+)',
        r'\bAtom\s+(\w+-\w+)',
        r'\bCeleron\s+(\w+)',
        r'\bPentium\s+(\w+\s*\w*)',
        r'Ryzen\s+Threadripper\s+(\w+)',
        r'Ryzen\s+\d+\s+(\w+)',
        r'FX\s*-\s*(\w+)',
    ]

    for pattern in patterns:
        m = re.search(pattern, cleaned)
        if m:
            return m.group(1).strip()
    return cleaned


def simplify_gpu_name(name):
    """精简 GPU 名称，去掉 NVIDIA/AMD/Intel 等厂商前缀。

    处理常见格式：
      "NVIDIA GeForce RTX 4090" → "RTX 4090"
      "NVIDIA GeForce GTX 1080 Ti" → "GTX 1080 Ti"
      "AMD Radeon RX 7900 XTX" → "RX 7900 XTX"
      "Intel Arc A770" → "Arc A770"

    Args:
        name: 原始 GPU 名称字符串

    Returns:
        str: 精简后的型号标识
    """
    prefixes = ["NVIDIA GeForce ", "AMD Radeon ", "NVIDIA ", "AMD ", "Intel "]
    for prefix in prefixes:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def format_osc_message(data, sys_cpu, display_config=None):
    """将硬件状态数据格式化为 OSC 聊天框消息。

    根据 display_config 控制每行是否显示，设为 OFF 的行不包含在消息中。

    Args:
        data: dict (cpu, ram_used, ram_total, gpu_name, gpu, vram_used, vram_total, text, window_title)
        sys_cpu: CPU 名称字符串
        display_config: dict 或 None，display.conf 配置项，为 None 时全部显示

    Returns:
        str: 格式化的多行消息
    """
    parts = []

    if not display_config or display_config.get("CPU", "ON") == "ON":
        parts.append(f"CPU[{simplify_cpu_name(sys_cpu)}]: {data['cpu']:.1f}%")

    if not display_config or display_config.get("RAM", "ON") == "ON":
        parts.append(f"内存: {data['ram_used']}GB/{data['ram_total']}GB")

    if not display_config or display_config.get("GPU", "ON") == "ON":
        parts.append(f"显卡[{simplify_gpu_name(data['gpu_name'])}]: {data['gpu']:.1f}%")

    if not display_config or display_config.get("VRAM", "ON") == "ON":
        parts.append(f"显存: {data['vram_used']}/{data['vram_total']}")

    if data.get("text") and (not display_config or display_config.get("TEXT", "ON") == "ON"):
        parts.append(f'"{data["text"].strip()}"')

    if data.get("window_title") and (not display_config or display_config.get("WINDOW", "ON") == "ON"):
        parts.append(f"当前窗口：{data['window_title']}")

    return "\n".join(parts)
