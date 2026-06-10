# HardwareMonitor-VRChatOSC

通过读取设备硬件信息(包括CPU,GPU,内存等数据)，实时显示在 VRChat 聊天框中。
其中GPU的读取采用GPU-Z 共享内存方案

## 为什么选择 GPU-Z 共享内存方案？

传统的 GPU 监控方案存在明显的兼容性问题：

| 方案 | NVIDIA | AMD | Intel Arc |
|---|---|---|---|
| nvidia-smi / NVML | ✅ | ❌ | ❌ |
| AMD ADL SDK | ❌ | ✅ | ❌ |
| GPU-Z 共享内存 | ✅ | ✅ | ✅ |

- **nvidia-smi / NVML**：只能读取 NVIDIA 显卡信息，AMD 和 Intel 显卡完全无法使用
- **AMD ADL SDK**：仅适用于 AMD 显卡，且需要额外的驱动依赖
- **GPU-Z 共享内存**：GPU-Z 本身支持所有主流显卡品牌，通过读取其共享内存数据，无需针对特定厂商编写代码，即可获得 GPU 负载、显存、温度等传感器信息

本项目正是基于 GPU-Z 共享内存方案，**理论上适配任意显卡**（只要 GPU-Z 能识别）。

## 快速开始

### 1. 安装 GPU-Z

前往 [GPU-Z 官网](https://www.techpowerup.com/download/techpowerup-gpu-z/) 下载并安装最新版本。



### 2. 运行程序

从 [Releases](https://github.com/luo3House/HardwareMonitor-VRChatOSC/releases) 下载 `monitor_gpuz.exe`，直接运行即可。

程序会自动在当前目录下生成 `config.json` 配置文件，按需修改配置后重新运行即可生效。一般用户无需修改直接启动exe即可

### 3. 在 VRChat 中启用 OSC

1. 打开 VRChat
2. 进入 **圆盘菜单** > **OSC**
3. 确保 OSC 已开启（默认端口 9000）

聊天框将自动显示硬件信息：

```
CPU[Intel i7-13700K]: 35.2%
RAM: 12.5GB/32GB
GPU[RTX 4090]: 82.1%
VRAM: 18.2GB/24GB
```

## config.json 配置说明

程序运行目录下的 `config.json` 支持以下高级配置：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `gpuz_path` | string | `""` | GPU-Z.exe 的完整路径，留空则自动搜索 |
| `osc_ip` | string | `"127.0.0.1"` | OSC 目标 IP 地址 |
| `osc_port` | int | `9000` | OSC 目标端口 |
| `update_interval` | int | `5` | 数据刷新间隔（秒） |
| `debug` | bool | `true` | 是否输出调试日志 |

### 示例配置

```json
{
    "gpuz_path": "D:\\Tools\\GPU-Z.exe",
    "osc_ip": "127.0.0.1",
    "osc_port": 9000,
    "update_interval": 3,
    "debug": false
}
```

### 常用配置场景

**自定义 GPU-Z 路径**：若 GPU-Z 不在项目目录下，指定完整路径即可：

```json
{
    "gpuz_path": "D:\\Software\\GPU-Z.exe"
}
```

**调整刷新频率**：默认 5 秒刷新一次，可按需调整（单位：秒）：

```json
{
    "update_interval": 3
}
```

**关闭调试日志**：生产环境下关闭详细日志输出：

```json
{
    "debug": false
}
```

**多实例 / 远程 VRChat**：若 VRChat 运行在其他设备上（如同一局域网的 PC），修改 OSC 目标地址：

```json
{
    "osc_ip": "192.168.1.100",
    "osc_port": 9000
}
```

## 常见问题

### GPU-Z 未找到

程序会按以下顺序自动搜索 GPU-Z：

1. `config.json` 中指定的路径
2. 当前程序目录
3. Windows 注册表（已安装的 GPU-Z）
4. 系统 PATH 环境变量
5. 所有盘符的 `Program Files` 目录
6. 用户的 `Downloads` 和 `Desktop` 目录

若自动搜索失败，可在 `config.json` 中手动设置 `gpuz_path`。

### VRChat 中未显示信息

1. 确认 VRChat 的 OSC 已开启（Settings > OSC）
2. 确认 OSC 端口与 `config.json` 中的 `osc_port` 一致（默认 9000）
3. 确认 GPU-Z 已启动

### 从源码运行（Python）

如需从源码运行而非使用 exe：

```bash
# 安装依赖
pip install -r requirements.txt

# 启动监控
python monitor_gpuz.py
```

### 自行打包

如需自行打包为 exe：

```bash
pip install pyinstaller
pyinstaller --onefile --clean --name monitor_gpuz monitor_gpuz.py
```

### 依赖安装失败（源码运行）

部分 Python 库（如 `pywin32`）依赖 Microsoft Visual C++ 运行时。若 `pip install` 时提示编译错误，请先安装 [Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) 后重试。

## 系统要求

- Windows 10 / 11
- GPU-Z（需手动下载）
- 使用 `monitor_gpuz.exe` 无需 Python 环境；如需从源码运行，需 Python 3.8 或更高版本

## 许可

本项目大部分代码由 AI 生成。
