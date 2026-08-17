# OSC 调试接收端

`debug\osc_receiver.py` 是独立的 OSC UDP 接收工具，用来查看 VRChat 或其他程序实际发出的 OSC 地址、参数类型、参数值和发送端口。

项目主程序默认将消息发送到 `127.0.0.1:9000`，接收端也默认监听该端口。因此同时运行 `start.bat` 和 `start_receiver.bat` 时，接收端能直接看到主程序发出的 `/chatbox/input` 消息。

## 快速启动

双击 `debug\start_receiver.bat`，默认监听 `0.0.0.0:9000`。这是项目主程序和 VRChat 常用的 OSC 输入端口。

也可以在终端运行：

```powershell
python debug\osc_receiver.py
```

收到消息时会显示为：

```text
[12:34:56.789] 127.0.0.1:51344 | /avatar/parameters/AFK | bool(false)
```

按 `Ctrl+C` 结束。

## 常用选项

```powershell
# 监听其他端口
python debug\osc_receiver.py --port 9002

# 只接收本机消息
python debug\osc_receiver.py --host 127.0.0.1

# 只显示某类地址
python debug\osc_receiver.py --filter /avatar/parameters

# 同时记录到文件
python debug\osc_receiver.py --log logs\osc.txt
```

`--filter` 可以重复使用，例如：

```powershell
python debug\osc_receiver.py --filter /avatar --filter /chatbox
```

> 调试时不要同时让 VRChat 和接收端监听 `9000`，否则后启动的程序会提示端口被占用。需要调试主程序输出时，关闭 VRChat 的 OSC 或退出 VRChat，再启动接收端即可。

## 打包为独立 EXE

双击 `debug\build_receiver.bat`。成功后可在 `debug\dist\osc_receiver.exe` 找到单文件程序，无需运行主硬件监控程序。
