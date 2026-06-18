"""
显示项配置模块

管理 display.conf 配置文件，控制每行显示内容是否在 OSC 消息中出现。
格式: 标识=ON/OFF

支持的标识:
    CPU   — CPU 负载行
    RAM   — 内存使用行
    GPU   — 显卡负载行
    VRAM  — 显存使用行
    TEXT  — 控制台自定义文本
    WINDOW — 当前活动窗口标题
"""

import os

DISPLAY_CONFIG_FILE = "display.conf"

DEFAULT_DISPLAY_CONFIG = {
    "CPU": "ON",
    "RAM": "ON",
    "GPU": "ON",
    "VRAM": "ON",
    "TEXT": "ON",
    "WINDOW": "OFF",
}

# 模块级缓存，在 main 中赋值
_display_config = None


def load_display_config():
    """加载 display.conf，缺失项用默认值补充。

    若文件不存在则自动创建默认配置。
    只识别 DEFAULT_DISPLAY_CONFIG 中定义的键，未知键忽略。

    Returns:
        dict: 完整显示配置 {"标识": "ON"/"OFF"}
    """
    config = dict(DEFAULT_DISPLAY_CONFIG)

    if os.path.exists(DISPLAY_CONFIG_FILE):
        try:
            with open(DISPLAY_CONFIG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, val = line.split("=", 1)
                        key = key.strip().upper()
                        val = val.strip().upper()
                        if key in config:
                            config[key] = val if val in ("ON", "OFF") else "ON"
        except Exception as e:
            print(f"[WARN] 读取 display.conf 失败: {e}")

    # 文件不存在 → 创建默认配置
    if not os.path.exists(DISPLAY_CONFIG_FILE):
        try:
            with open(DISPLAY_CONFIG_FILE, "w", encoding="utf-8") as f:
                for k, v in DEFAULT_DISPLAY_CONFIG.items():
                    f.write(f"{k}={v}\n")
            print(f"[INFO] 已创建默认配置文件: {DISPLAY_CONFIG_FILE}")
        except IOError as e:
            print(f"[WARN] 无法创建 {DISPLAY_CONFIG_FILE}: {e}")

    return config
