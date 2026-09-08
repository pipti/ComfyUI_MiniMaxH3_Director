# -*- coding: utf-8 -*-
"""H3ScriptLoader —— 把「提示词配置单」(.json) 读入导演台，免 build 注入。

剧本 .json 结构（与现有 build_*.py 里的 SCRIPT 字典一致）：
{
  "title": "片名",
  "characters": "<Subject 1> 铁牛 ... <Subject 2> 豚叔 ...",
  "scene_setting": "<Scene> 白天海岸公路 ...",
  "segments": [
    {
      "id": "p_capsule_summon",
      "durationSec": 4.0,
      "prompt": "summary:\n[reference generation] ...",
      "refs": [{"index": 0, "imageFile": "kitchen_couple_reference.jpg",
                "type": "input", "subfolder": ""}],
      "continuityFromPrev": false
    }
  ]
}

参考图/参考视频在 segments[].refs / refVideos 里只存文件名，不塞字节；
实体文件须已在 ComfyUI/input/（与原来的工作方式一致）。
"""
from __future__ import annotations

import json
import os


def _build_timeline(script, *, ref_image="", fps=24, width=864, height=480, ref_max_size=864):
    """把 SCRIPT 字典转成导演台 timeline_data（与 build_*.py 的 build_timeline 对齐）。"""
    segments, cur = [], 0
    for seg in script["segments"]:
        n = int(round(seg["durationSec"] * fps))
        segments.append({
            "id": seg["id"], "start": cur, "length": n, "frameCount": n,
            "durationSec": seg["durationSec"], "prompt": seg["prompt"],
            "negativePrompt": "", "taskType": "",
            "refs": seg.get("refs", []), "refAudios": [], "refVideos": [],
            "genImage": {"imageFile": "", "fileName": ""},
            "continuityFromPrev": seg.get("continuityFromPrev", False),
        })
        cur += n

    global_prompt = f"subject_definitions:\n{script['characters']}\n\n{script['scene_setting']}\n\n"
    timeline = {
        "version": 5, "editMode": "segment", "totalFrames": cur, "frameRate": fps,
        "video": {"fileName": "", "videoFile": "", "subfolder": "", "type": "input",
                  "frames": [], "frameMap": [], "sourceFrameCount": 0, "deletedSourceRanges": []},
        "videoClips": [],
        "global": {
            "taskType": "r2v — 参考主体生视频(Reference to Video)",
            "prompt": global_prompt,
            "refs": [{"index": 0, "imageFile": ref_image, "fileName": "", "type": "input", "subfolder": ""}],
            "referenceVideo": {"videoFile": "", "fileName": "", "type": "input", "subfolder": ""},
            "continuousReference": False, "genImage": {"imageFile": ""},
            "sourceWidth": 768, "sourceHeight": 1024,
            "refAudios": [], "commonEnabled": True, "commonCollapsed": True, "refVideos": [],
        },
        "output": {
            "mode": "fixed", "aspectRatio": "16:9 (宽屏)", "megapixels": 0.4,
            "multiple": 32, "longEdge": width, "width": width, "height": height,
            "maxExportFrames": 0, "exportMode": "all", "audioMode": "source",
            "continuityEnabled": True, "continuityOverlapFrames": 22,
        },
        "runSelectEnabled": False, "runSelection": [], "segments": segments,
    }
    return timeline, global_prompt


class H3ScriptLoader:
    """读取提示词配置单 .json，输出 timeline_data 直连导演台（global_prompt 由导演台从 timeline_data 自行解析，不重复暴露）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "script_path": (
                    "STRING",
                    {"default": "", "multiline": False,
                     "tooltip": "提示词配置单 .h3dp/.json 的绝对路径。点节点上『Browse...』按钮弹原生选择框；也可直接粘贴。"},
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("timeline_data",)
    FUNCTION = "load"
    CATEGORY = "MiniMaxH3"

    def load(self, script_path):
        if not script_path or not str(script_path).strip():
            raise ValueError("script_path 为空：请填写 .h3dp/.json 绝对路径（可点节点上『Browse...』按钮选）")
        sp = str(script_path).strip()
        if not os.path.isabs(sp):
            raise ValueError(f"script_path 须为绝对路径：{sp}")
        if not os.path.exists(sp):
            raise ValueError(f"找不到剧本文件：{sp}")
        with open(sp, "r", encoding="utf-8") as f:
            script = json.load(f)
        # 兼容两种配置单格式：
        #  - timeline 原文（含 "version" 字段，如导演台导出的 _promote.h3dp / 手搓片）：直接透传，零损失
        #  - SCRIPT 格式（含 characters / scene_setting / segments，如 build_*.py 的剧本）：走 _build_timeline 重新拼装
        if isinstance(script.get("version"), int):
            std_keys = {"version", "editMode", "totalFrames", "frameRate", "video", "videoClips",
                        "global", "output", "runSelectEnabled", "runSelection", "segments"}
            clean = {k: v for k, v in script.items() if k in std_keys}
            return (json.dumps(clean, ensure_ascii=False),)
        timeline, _ = _build_timeline(script)
        return (json.dumps(timeline, ensure_ascii=False),)

    @classmethod
    def IS_CHANGED(cls, script_path, **kwargs):
        # 文件内容变化（mtime）即视为变更，强制下游导演台重跑。
        del kwargs
        sp = (script_path or "").strip()
        if not sp or not os.path.isabs(sp) or not os.path.exists(sp):
            return False
        try:
            return float(os.path.getmtime(sp))
        except OSError:
            return False
