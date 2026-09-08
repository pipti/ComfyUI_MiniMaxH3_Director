# -*- coding: utf-8 -*-
"""H3ScriptExporter —— 把导演台 / Loader 的 timeline_data 导出成提示词配置单 .h3dp。

与 H3ScriptLoader 对称：导出的 .h3dp 可直接回灌 H3ScriptLoader，实现
「导演台当前配置 → 文件 → 编辑 → 再导入」的闭环。

导出格式 = timeline 原文（含 version 字段），零损失；H3ScriptLoader 检测到 version
即透传回导演台。

out_path 默认由前端在加载工作流时自动填成「同目录 / <工作流名>_promote.h3dp」，
也可手动改成任意绝对路径。
"""
from __future__ import annotations

import json
import os


class H3ScriptExporter:
    """接收 timeline_data，导出为可编辑的提示词配置单 .h3dp（timeline 原文，零损失）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "timeline_data": (
                    "STRING",
                    {"multiline": True,
                     "tooltip": "要导出的 timeline_data（接导演台新增的 timeline_data 输出，或 H3ScriptLoader 的 timeline_data 输出）"},
                ),
                "out_path": (
                    "STRING",
                    {"default": "", "multiline": False,
                     "tooltip": "导出 .h3dp 的绝对路径。前端加载工作流时自动填「同目录/<工作流名>_promote.h3dp」，可改。"},
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("status",)
    FUNCTION = "export"
    CATEGORY = "MiniMaxH3"
    OUTPUT_NODE = True

    def export(self, timeline_data, out_path):
        if not timeline_data or not timeline_data.strip():
            raise ValueError("timeline_data 为空：请连接导演台 / Loader 的 timeline_data 输出")
        if not out_path or not out_path.strip():
            raise ValueError("out_path 为空：请填写导出 .h3dp 路径（前端加载工作流后会自动填默认 <工作流名>_promote.h3dp）")
        if not os.path.isabs(out_path):
            raise ValueError(f"out_path 须为绝对路径：{out_path}")
        try:
            tl = json.loads(timeline_data)
        except Exception as _e:
            raise ValueError(f"timeline_data 不是合法 JSON：{_e}")

        d = os.path.dirname(out_path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(tl, f, ensure_ascii=False, indent=2)
        n = len(tl.get("segments", []) or [])
        total = sum((s.get("durationSec") or 0) for s in tl.get("segments", []) or [])
        return (f"已导出 timeline（{n} 段 / {total:.1f}s）→ {out_path}",)
