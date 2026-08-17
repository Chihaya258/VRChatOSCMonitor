"""
轻量级 OSC 接收端，用于调试 VRChat 或其他 OSC 发送端。

默认监听 VRChat 的 OSC 输入端口 9000：
    python osc_receiver.py

按 Ctrl+C 停止。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Iterable, TextIO

from pythonosc import dispatcher, osc_server


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="接收并打印 OSC UDP 消息（默认监听 VRChat 的输入端口 9000）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="监听地址。使用 127.0.0.1 时仅接收本机消息。",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="监听 UDP 端口。",
    )
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="PREFIX",
        help="仅显示以此前缀开头的 OSC 地址；可重复指定。",
    )
    parser.add_argument(
        "--log",
        type=Path,
        metavar="FILE",
        help="将已显示的消息同时追加保存至 UTF-8 文本文件。",
    )
    return parser.parse_args()


def format_value(value: Any) -> str:
    """返回带类型信息、适合终端显示的 OSC 参数文本。"""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return f"bool({str(value).lower()})"
    if isinstance(value, int):
        return f"int({value})"
    if isinstance(value, float):
        return f"float({value:.6g})"
    if isinstance(value, str):
        return f"string({value!r})"
    if isinstance(value, (bytes, bytearray)):
        preview = bytes(value[:32]).hex(" ")
        suffix = " …" if len(value) > 32 else ""
        return f"blob({len(value)} bytes: {preview}{suffix})"
    if isinstance(value, (list, tuple)):
        return f"{type(value).__name__}([{', '.join(format_value(item) for item in value)}])"
    return f"{type(value).__name__}({value!r})"


def format_message(client_address: tuple[str, int], address: str, args: Iterable[Any]) -> str:
    timestamp = time.strftime("%H:%M:%S")
    milliseconds = int((time.time() % 1) * 1000)
    values = ", ".join(format_value(value) for value in args) or "(无参数)"
    return f"[{timestamp}.{milliseconds:03d}] {client_address[0]}:{client_address[1]} | {address} | {values}"


class OscPrinter:
    def __init__(self, filters: list[str], log_file: TextIO | None) -> None:
        self.filters = filters
        self.log_file = log_file
        self.received_count = 0
        self.shown_count = 0

    def handle(self, client_address: tuple[str, int], address: str, *args: Any) -> None:
        self.received_count += 1
        if self.filters and not any(address.startswith(prefix) for prefix in self.filters):
            return

        line = format_message(client_address, address, args)
        print(line, flush=True)
        if self.log_file:
            self.log_file.write(line + "\n")
            self.log_file.flush()
        self.shown_count += 1


def main() -> int:
    args = parse_args()
    if not 1 <= args.port <= 65535:
        print("[ERROR] 端口必须在 1 到 65535 之间。", file=sys.stderr)
        return 2

    log_file: TextIO | None = None
    try:
        if args.log:
            args.log.parent.mkdir(parents=True, exist_ok=True)
            log_file = args.log.open("a", encoding="utf-8")

        printer = OscPrinter(args.filter, log_file)
        osc_dispatcher = dispatcher.Dispatcher()
        osc_dispatcher.set_default_handler(printer.handle, needs_reply_address=True)
        server = osc_server.ThreadingOSCUDPServer((args.host, args.port), osc_dispatcher)
    except OSError as error:
        if log_file:
            log_file.close()
        print(f"[ERROR] 无法监听 {args.host}:{args.port}: {error}", file=sys.stderr)
        print("        请确认端口未被占用，并检查监听地址是否正确。", file=sys.stderr)
        return 1

    print("=" * 68)
    print("  OSC Debug Receiver")
    print("=" * 68)
    print(f"  Listening: {args.host}:{args.port} (UDP)")
    print(f"  Filter:    {', '.join(args.filter) if args.filter else '全部地址'}")
    print(f"  Log:       {args.log.resolve() if args.log else '未启用'}")
    print("  按 Ctrl+C 停止。")
    print("=" * 68)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] 正在停止接收端...")
    finally:
        server.server_close()
        if log_file:
            log_file.close()
        print(f"[INFO] 共接收 {printer.received_count} 条，显示 {printer.shown_count} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
