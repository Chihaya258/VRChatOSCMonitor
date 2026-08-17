# OSC 调试接收端

`osc_receiver.py` 是独立的 OSC UDP 接收工具，用来查看 VRChat 或其他程序实际发出的 OSC 地址、参数类型、参数值和发送端口。

## 快速启动

双击 `start_receiver.bat`，默认监听 `0.0.0.0:9001`。这是 VRChat 常用的 OSC 输出端口。

也可以在终端运行：

```powershell
python osc_receiver.py
```

收到消息时会显示为：

```text
[12:34:56.789] 127.0.0.1:51344 | /avatar/parameters/AFK | bool(false)
```

按 `Ctrl+C` 结束。

## 常用选项

```powershell
# 监听其他端口
python osc_receiver.py --port 9002

# 只接收本机消息
python osc_receiver.py --host 127.0.0.1

# 只显示某类地址
python osc_receiver.py --filter /avatar/parameters

# 同时记录到文件
python osc_receiver.py --log logs\osc.txt
```

`--filter` 可以重复使用，例如：

```powershell
python osc_receiver.py --filter /avatar --filter /chatbox
```

## 打包为独立 EXE

双击 `build_receiver.bat`。成功后可在 `dist\osc_receiver.exe` 找到单文件程序，无需运行主硬件监控程序。
