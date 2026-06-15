# VRChatOSCMonitor


实时采集 CPU、GPU、内存等硬件信息，通过 OSC 协议发送至 VRChat 聊天框显示。

## GPU 数据源

程序支持两种 GPU 数据采集方式，按优先级自动选择：

| 方案 | NVIDIA | AMD | Intel Arc |
|---|---|---|---|
| **NVML (pynvml)** | ✅ 官方驱动 | ❌ | ❌ |
| **GPU-Z 共享内存** | ✅ | ✅ | ✅（理论支持） |

- **NVIDIA 用户**：优先使用 NVML（`pynvml`），GPU 数据直接从显卡驱动获取，**无需安装 GPU-Z**。
- **AMD / Intel 用户**：自动回退到 GPU-Z 共享内存方案，GPU-Z 能识别的显卡均可读取。
- 也可通过 `gpu_source` 配置项强制指定使用哪种方式（见下方配置说明）。

## 快速开始

### 1. 安装 GPU-Z（AMD / Intel 用户）

前往 [GPU-Z 官网](https://www.techpowerup.com/download/techpowerup-gpu-z/) 下载并安装，启动后进入 Sensors 标签页，勾选 **Shared Memory** 选项。

> **NVIDIA 用户可跳过此步骤**，程序会直接通过显卡驱动（NVML）读取 GPU 数据，无需安装 GPU-Z。

### 2. 运行程序

#### 方式一：exe 直接运行（推荐）

1. 前往 [Releases](https://github.com/Chihaya258/VRChatOSCMonitor) 下载 `monitor_gpuz.exe`
2. 双击运行，程序会自动生成 `config.json`
3. 在 VRChat 中开启 OSC（圆盘菜单 → OSC → 端口 9000）

#### 方式二：从源码运行

```bash
# 安装依赖（或直接双击 start.bat 自动完成）
pip install -r requirements.txt

# 启动
python main.py
```

双击 `start.bat` 可自动创建虚拟环境并安装依赖，无需手动操作。

#### 方式三：自行打包

双击 `build.bat` 即可打包为单文件 exe，输出在 `dist\monitor_gpuz.exe`。

### VRChat 显示效果

聊天框将自动显示硬件信息：

```
CPU[Intel i7-13700K]: 35.2%
RAM: 12.5GB/32GB
GPU[RTX 4090]: 82.1%
VRAM: 18.2GB/24GB
```

---

## config.json 完整配置

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `gpuz_path` | string | `""` | GPU-Z.exe 的完整路径，留空则自动搜索 |
| `osc_ip` | string | `"127.0.0.1"` | OSC 目标 IP 地址 |
| `osc_port` | int | `9000` | OSC 目标端口 |
| `update_interval` | int | `5` | 数据刷新间隔（秒） |
| `debug` | bool | `true` | 是否输出调试日志 |
| `gpu_source` | string | `"auto"` | GPU 数据源：`"auto"` `"nvidia"` `"gpuz"` |
| `cpu_name` | string | `""` | CPU 名称覆盖（留空 = 自动检测） |
| `gpu_name` | string | `""` | GPU 名称覆盖（留空 = 自动检测） |
| `ram_total_gb` | float | `0` | 内存上限覆盖（`0` = 自动检测） |
| `vram_total_gb` | float | `0` | 显存上限覆盖（`0` = 自动检测） |

### 常用场景

**NVIDIA 用户（无需 GPU-Z）**：默认 `"auto"` 已自动选择 NVML，无需额外配置。

**强制使用 GPU-Z**（如 pynvml 行为异常）：

```json
{
    "gpu_source": "gpuz"
}
```

**调整刷新频率**：

```json
{
    "update_interval": 3
}
```

**关闭调试日志**：

```json
{
    "debug": false
}
```

**多实例 / 远程 VRChat**：

```json
{
    "osc_ip": "192.168.1.100",
    "osc_port": 9000
}
```

**自定义硬件名称/数值**：覆盖自动检测的数据，填 `""` 或 `0` 表示使用自动检测值。

```json
{
    "cpu_name": "AMD Ryzen 7 7800X3D @ 5.0GHz",
    "gpu_name": "NVIDIA GeForce RTX 4090",
    "ram_total_gb": 32,
    "vram_total_gb": 24
}
```

---

## 常见问题

### GPU-Z 未找到（AMD / Intel 用户）

程序会按以下顺序自动搜索 GPU-Z：

1. `config.json` 中指定的路径
2. 当前程序目录
3. Windows 注册表（已安装的 GPU-Z）
4. 系统 PATH 环境变量
5. 所有盘符的 `Program Files` 目录
6. 用户的 `Downloads` 和 `Desktop` 目录

若自动搜索失败，在 `config.json` 中手动设置 `gpuz_path` 或前往 [GPU-Z 官网](https://www.techpowerup.com/download/techpowerup-gpu-z/) 安装。

### VRChat 中未显示信息

1. 确认 VRChat 的 OSC 已开启（Settings → OSC）
2. 确认 OSC 端口与 `config.json` 中 `osc_port` 一致（默认 9000）
3. AMD / Intel 用户确认 GPU-Z 已启动
4. NVIDIA 用户确认 pynvml 依赖已安装（`pip install pynvml`）

### 依赖安装失败

部分 Python 库（如 `pywin32`）依赖 Microsoft Visual C++ 运行时。若 `pip install` 提示编译错误，请先安装 [VC Redist](https://aka.ms/vs/17/release/vc_redist.x64.exe) 后重试。

---

## 系统要求

- Windows 10 / 11
- Python 3.8+（仅源码运行需要；exe 无需 Python）
- NVIDIA 显卡：安装显卡驱动即可（无需 GPU-Z）
- AMD / Intel 显卡：需安装 GPU-Z 并开启共享内存（GPU-Z → Sensors → 勾选 Shared Memory）

## 已知问题

- **Intel Arc 显卡**：GPU-Z 共享内存方案理论上支持，但因缺少测试设备，尚未验证实际兼容性。如果你使用 Intel Arc 显卡，欢迎反馈测试结果。

---

## 更新日志

### v2.0 (2026-06)

- **NVIDIA NVML 支持**：新增 `pynvml` 数据源，NVIDIA 用户无需安装 GPU-Z 即可使用
- **模块化重构**：单文件拆分为 `main.py` + `utils/` 包（config / logger / gpuz_search / gpu_reader / osc_sender），便于维护和扩展
- **config.json 自定义覆盖**：新增 `cpu_name` `gpu_name` `ram_total_gb` `vram_total_gb` 字段，可覆盖自动检测的硬件信息
- **GPU 数据源手动指定**：新增 `gpu_source` 字段，支持 `auto` / `nvidia` / `gpuz`
- **一键部署**：`start.bat` 自动创建虚拟环境并安装依赖，双击即用
- **build.bat 更新**：适配新代码结构，添加 `--hidden-import` 确保可选依赖正常打包
- **中文控制台输出**：所有日志、提示信息改为中文
- **清理无用依赖**：移除 `GPUtil` `pyadl` `python-dateutil` `pytz` `six` `tzdata`

### v1.0

- 初始版本：基于 GPU-Z 共享内存的硬件监控
- OSC 协议发送至 VRChat 聊天框
- 自动搜索 GPU-Z 安装路径
