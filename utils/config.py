"""
配置管理模块

负责加载、保存和合并 config.json 配置文件。
提供 DEFAULT_CONFIG 常量作为默认值，确保向后兼容。
"""

import json
import os

# ============================================================================
# 默认配置常量
# ============================================================================

DEFAULT_CONFIG = {
    "gpuz_path": "",          # GPU-Z.exe 的完整路径，留空则自动搜索
    "osc_ip": "127.0.0.1",    # OSC 目标 IP (VRChat 默认本地)
    "osc_port": 9000,         # OSC 目标端口 (VRChat 默认 9000)
    "update_interval": 5,     # 数据刷新间隔 (秒)
    "debug": True,            # 是否输出详细调试日志
    "gpu_source": "auto",     # GPU 数据源: "auto" / "nvidia" / "gpuz"
    "cpu_name": "",           # CPU 名称覆盖 (留空 = 自动检测)
    "gpu_name": "",           # GPU 名称覆盖 (留空 = 自动检测)
    "ram_total_gb": 0,        # 内存上限覆盖 (0 = 自动检测)
    "vram_total_gb": 0,       # 显存上限覆盖 (0 = 自动检测)
}

CONFIG_FILE = "config.json"
GPUZ_DOWNLOAD_URL = "https://www.techpowerup.com/download/techpowerup-gpu-z/"

# 模块级配置缓存，在 main 中赋值
_config = None


# ============================================================================
# 配置文件管理
# ============================================================================

def load_config():
    """加载 config.json 配置文件。

    若文件存在且合法，读取其内容并与默认值合并 (确保所有键都存在)。
    若文件不存在，自动创建包含默认值的 config.json。
    若文件存在但解析失败，打印警告并回退到默认配置。

    Returns:
        dict: 合并后的完整配置字典
    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            # 将默认值中缺失的键补充到用户配置中 (向后兼容)
            for key, value in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = value
            print(f"[INFO] 已加载配置文件: {CONFIG_FILE}")
            return config
        except (json.JSONDecodeError, IOError) as e:
            print(f"[WARN] 配置文件读取失败 ({e})，使用默认配置")

    # 配置文件不存在 → 创建默认配置
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
        print(f"[INFO] 已创建默认配置文件: {CONFIG_FILE}")
    except IOError as e:
        print(f"[WARN] 无法创建配置文件: {e}")
    return dict(DEFAULT_CONFIG)


def save_config(config):
    """保存当前配置到 config.json。

    Args:
        config: 要保存的配置字典
    """
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except IOError as e:
        print(f"[WARN] 无法保存配置文件: {e}")
