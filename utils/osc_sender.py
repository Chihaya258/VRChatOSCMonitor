"""
OSC 消息格式化模块

负责将硬件状态数据组装为 VRChat 聊天框格式的多行消息文本。
"""


def format_osc_message(data, sys_cpu):
    """将硬件状态数据格式化为 OSC 聊天框消息。

    Args:
        data: dict (cpu, ram_used, ram_total, gpu_name, gpu, vram_used, vram_total, text)
        sys_cpu: CPU 名称字符串

    Returns:
        str: 格式化的多行消息
    """
    parts = [
        f"CPU[{sys_cpu}]: {data['cpu']:.1f}%",
        f"RAM: {data['ram_used']}GB/{data['ram_total']}GB",
        f"GPU[{data['gpu_name']}]: {data['gpu']:.1f}%",
        f"VRAM: {data['vram_used']}/{data['vram_total']}",
    ]
    if data.get("text"):
        parts.append(f'"{data["text"].strip()}"')
    return "\n".join(parts)
