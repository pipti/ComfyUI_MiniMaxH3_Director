# -*- coding: utf-8 -*-
"""独立子进程：弹 tkinter 文件选择框，把用户选中的绝对路径写到 stdout。

由 /minimax/director/select_script 路由用 subprocess.run([pythonw.exe, 本脚本, 初始路径])
异步调用，不阻塞 ComfyUI 主 event loop。空路径或超时代表用户取消。

为什么独立子进程：
  - tkinter.filedialog 是模态阻塞调用，若在 ComfyUI 主进程里跑，整个 server 会被卡住
  - 单独进程崩溃不影响主服务
  - pythonw.exe 无控制台窗口，弹框体验更干净
"""
from __future__ import annotations

import os
import sys


def _main() -> int:
    try:
        import tkinter as tk  # noqa: F401
        from tkinter import filedialog
    except Exception:
        # 静默失败：stdout 空，主进程视为取消
        sys.stdout.write("")
        sys.stdout.flush()
        return 2

    initial = sys.argv[1] if len(sys.argv) > 1 else ""
    initial_dir = ""
    if initial:
        try:
            cand = initial if os.path.isabs(initial) else os.path.abspath(initial)
            if os.path.isdir(cand):
                initial_dir = cand
            elif os.path.isfile(cand):
                initial_dir = os.path.dirname(cand) or ""
        except Exception:
            initial_dir = ""

    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        ftypes = [
            ("H3DP / JSON 配置单", "*.h3dp *.json"),
            ("所有文件", "*.*"),
        ]
        path = filedialog.askopenfilename(
            title="选择提示词配置单",
            filetypes=ftypes,
            initialdir=initial_dir or None,
        )
        try:
            root.destroy()
        except Exception:
            pass
    except Exception:
        path = ""

    sys.stdout.write(path or "")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
