"""MiniMax H3 Director — timeline UI + official MiniMax H3 AV execution."""

from __future__ import annotations

import json

import torch

import comfy.samplers

from ..director.executor_core import execute_director_plan_core
from .director_common import (
    finalize_director_outputs,
    prepare_director_plan,
    timeline_required_inputs,
    director_perf_inputs,
)

_CATEGORY = "MiniMaxH3"

_DEFAULT_GLOBAL_PROMPT = "A cinematic scene with natural motion and synchronized ambience"


def director_timeline_required_inputs() -> dict:
    """Timeline widgets — defaults aligned with official MiniMax H3 workflow templates."""
    inputs = timeline_required_inputs()
    combo_options, combo_meta = inputs["task_type"]

    gp_meta = dict(inputs["global_prompt"][1])
    gp_meta["default"] = _DEFAULT_GLOBAL_PROMPT
    gp_meta["tooltip"] = (
        "User prompt — sent directly to MiniMaxH3ImageToVideo / ReferenceToVideo. "
        "r2v: <Picture 1>. v2v: source-timeline edit (<Video 1>). "
        "rv2v: source timeline + reference images (<Video 1> + <Picture N>)."
    )

    frames_meta = dict(inputs["total_frames"][1])
    frames_meta["default"] = 124
    frames_meta["tooltip"] = (
        "Frame count at 24 fps; snapped to MiniMax 17k+5 grid (124 ≈ 5s)."
    )

    return {
        **inputs,
        "task_type": (combo_options, combo_meta),
        "global_prompt": ("STRING", gp_meta),
        "total_frames": ("INT", frames_meta),
    }


class MiniMaxH3Director:
    """In-node timeline Director using ComfyUI official MiniMax H3 pipeline."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (
                    "MODEL",
                    {"tooltip": "MiniMax H3 UNET (UNETLoader)."},
                ),
                "video_vae": (
                    "VAE",
                    {"tooltip": "MiniMax H3 video VAE (minimax_h3_video_vae)."},
                ),
                "audio_vae": (
                    "VAE",
                    {"tooltip": "MiniMax H3 audio VAE (minimax_h3_audio_vae). Required for r2v / v2v / rv2v."},
                ),
                "clip": (
                    "CLIP",
                    {"tooltip": "CLIPLoader type=minimax (qwen3vl)."},
                ),
                **director_timeline_required_inputs(),
            },
            "optional": {
                "i2v_groups": (
                    "MMX_DIR_GROUP",
                    {
                        "tooltip": (
                            "External Image to Video group(s) (t2v / i2v / fl2v). "
                            "When connected, overrides UI cards for execution (external priority). "
                            "Connect Group (Image to Video).group, or Groups Combine."
                        ),
                    },
                ),
                "r2v_groups": (
                    "MMX_DIR_GROUP",
                    {
                        "tooltip": (
                            "External Reference to Video group(s). "
                            "When connected, overrides UI cards for execution (external priority). "
                            "Connect Group (Reference to Video).group, or Groups Combine."
                        ),
                    },
                ),
                "refine": (
                    "MMX_DIR_REFINE",
                    {
                        "tooltip": (
                            "Optional Refine node. When connected, each segment runs a second "
                            "sample pass (same-size refine, or upscale then sample). "
                            "Wire a MODEL into Refine.refine_model to use a different UNET for that pass; "
                            "unwired uses this Director model. "
                            "images is the refined result; images_pre_refine is the first pass. "
                            "Unconnected = single-pass (current behavior)."
                        ),
                    },
                ),
                "script_timeline": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": (
                            "可选：外部剧本 .json 经 H3 Director Script Loader 生成的 timeline_data 字符串。"
                            "连接后覆盖本节点的 timeline_data / global_prompt / total_frames widget，"
                            "实现『提示词配置单』外置、免 build 换剧本。"
                        ),
                    },
                ),
                "bd_grp_advanced": ("BDGROUP", {"default": "高级采样"}),
                "steps": (
                    "INT",
                    {
                        "default": 25,
                        "min": 1,
                        "max": 200,
                        "tooltip": "Sampling steps — official template: 25.",
                    },
                ),
                "sampler": (
                    comfy.samplers.KSampler.SAMPLERS,
                    {
                        "default": "res_multistep",
                        "tooltip": "Official template: KSamplerSelect res_multistep.",
                    },
                ),
                "scheduler": (
                    comfy.samplers.KSampler.SCHEDULERS,
                    {
                        "default": "simple",
                        "tooltip": "Official template: BasicScheduler simple.",
                    },
                ),
                "shift_video": (
                    "FLOAT",
                    {"default": 12.0, "min": 0.01, "max": 100.0, "step": 0.01, "tooltip": "MiniMaxH3SigmaShift shift_video."},
                ),
                "shift_audio": (
                    "FLOAT",
                    {"default": 3.0, "min": 0.01, "max": 100.0, "step": 0.01, "tooltip": "MiniMaxH3SigmaShift shift_audio."},
                ),
                **director_perf_inputs(),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    @classmethod
    def VALIDATE_INPUTS(cls, input_types=None, **_kwargs):
        if input_types is not None:
            expected = {
                "model": "MODEL",
                "video_vae": "VAE",
                "audio_vae": "VAE",
                "clip": "CLIP",
            }
            for name, want in expected.items():
                got = input_types.get(name)
                if got is not None and got != want:
                    return f"{name}: expected {want}, linked node returns {got}."
        return True

    @classmethod
    def IS_CHANGED(cls, unique_id=None, **kwargs):
        # Do not return NaN: that would re-run every Director queue even when
        # confirm_first_pass is off. Linked Refine is None here, so fingerprint
        # the .pre cache files that only the confirmation hold writes.
        del kwargs
        from ..director.segment_cache import first_pass_cache_disk_signature

        return first_pass_cache_disk_signature(unique_id)

    # 追加输出（槽位 7~10）：global_prompt 与去重后的参考图。
    # 只在末尾追加，旧工作流对槽位 0~6 的连线不受影响。
    RETURN_TYPES = ("IMAGE", "AUDIO", "FLOAT", "INT", "IMAGE", "STRING", "IMAGE", "STRING", "IMAGE", "IMAGE", "IMAGE", "STRING", "IMAGE", "IMAGE", "AUDIO")
    RETURN_NAMES = ("images", "audio", "fps", "frame_count", "source_images", "report", "images_pre_refine", "global_prompt", "ref_image_0", "ref_image_1", "ref_image_2", "timeline_data", "all_ref_images", "segment_images", "segment_audios")
    OUTPUT_IS_LIST = (True, True, False, False, True, False, True, False, False, False, False, False, False, True, True)
    FUNCTION = "execute"
    CATEGORY = _CATEGORY
    DESCRIPTION = (
        "MiniMax H3 Director: MiniMaxH3ImageToVideo / ReferenceToVideo conditioning, "
        "single-stage KSampler + MiniMaxH3SigmaShift, LTXVSeparateAVLatent decode. "
        "Supports t2v / i2v / fl2v / r2v / v2v / rv2v. "
        "Optional i2v_groups / r2v_groups accept multi-group packs from Director Group nodes "
        "(external priority over UI cards). Optional refine accepts MiniMax H3 Director Refine "
        "(second sample / upscale). images_pre_refine is the first-pass video before refine. "
        "Defaults: 0.4MP 16:9 (864×480), 5s / 124 frames @ 24 fps."
    )

    def execute(
        self,
        model,
        video_vae,
        audio_vae,
        clip,
        task_type,
        global_prompt,
        frame_rate,
        width,
        height,
        ref_max_size,
        total_frames,
        timeline_data,
        unique_id=None,
        i2v_groups=None,
        r2v_groups=None,
        refine=None,
        steps=25,
        sampler="res_multistep",
        scheduler="simple",
        cfg=1.0,
        seed=0,
        shift_video=12.0,
        shift_audio=3.0,
        clear_vram_between_segments=True,
        export_source_images=False,
        script_timeline="",
        **kwargs,
    ):
        del kwargs

        # 外部剧本覆盖：script_timeline 由 H3ScriptLoader 提供时，优先用文件里的
        # timeline / 全局提示词 / 总帧数，覆盖本节点对应的 widget。
        if script_timeline and script_timeline.strip():
            try:
                _ext = json.loads(script_timeline)
            except Exception as _e:
                # 容错：外部剧本解析失败不要直接炸（否则数百秒渲染白跑）。
                # 回退到导演台前端 widgets 里的剧本，并打印问题内容前 240 字符便于排查来源。
                _preview = script_timeline[:240].replace("\n", " ⏎ ").replace("\r", "")
                print(
                    f"[MiniMax H3 Director] ⚠️ script_timeline 不是合法 JSON，已回退到节点内置剧本：{_e} | 内容预览: {_preview!r}"
                )
                _ext = None
            if _ext is None:
                # 解析失败：保持 timeline_data=节点内置剧本（不覆盖），跳过全局提示词/总帧数提取
                pass
            else:
                timeline_data = script_timeline
                _gp = (_ext.get("global") or {}).get("prompt")
                if _gp:
                    global_prompt = _gp
                _tf = _ext.get("totalFrames")
                if _tf:
                    total_frames = int(_tf)

        plan = prepare_director_plan(
            timeline_data=timeline_data,
            task_type=task_type,
            global_prompt=global_prompt,
            total_frames=total_frames,
            frame_rate=frame_rate,
            width=width,
            height=height,
            ref_max_size=ref_max_size,
            unique_id=unique_id,
            i2v_groups=i2v_groups,
            r2v_groups=r2v_groups,
            refine=refine,
        )

        combined, segment_outputs, segment_audios, report, export_frame_counts, pre_combined, pre_segments, held_for_confirmation = (
            execute_director_plan_core(
                plan,
                node_id=unique_id,
                model=model,
                vae=video_vae,
                audio_vae=audio_vae,
                clip=clip,
                cfg=cfg,
                seed=seed,
                steps=steps,
                sampler=sampler,
                scheduler=scheduler,
                shift_video=shift_video,
                shift_audio=shift_audio,
                clear_vram_between_segments=clear_vram_between_segments,
            )
        )

        result = finalize_director_outputs(
            plan,
            combined,
            segment_outputs,
            report,
            export_source_images=export_source_images,
            segment_audios=segment_audios,
            segment_frame_counts=export_frame_counts,
            pre_refine_combined=pre_combined,
            pre_refine_segments=pre_segments,
            block_final_images=held_for_confirmation,
        )

        # 追加输出：全局提示词原文 + 合并去重后的参考图（供二采/放大链直连）。
        ref0, ref1, ref2 = _merged_unique_ref_images(plan)
        all_ref = _all_ref_images(plan)
        # 每段独立输出（与 all_ref_images 对称：始终暴露全量，不依赖 export_mode 分段开关）。
        seg_videos = segment_outputs
        seg_audios_out = [a for a in (segment_audios or []) if a is not None]
        return (*result, plan.global_prompt, ref0, ref1, ref2, timeline_data, all_ref, seg_videos, seg_audios_out)


def _merged_unique_ref_images(plan):
    """合并 global_refs 与各段 refs，按文件名（退化用张量 id）去重，取前 3 张。

    返回 (ref0, ref1, ref2)，不足的位置为 None（下游 ref_image_N 为 optional 输入）。
    """
    seen: dict = {}
    # 全局参考优先，再按段顺序补
    candidates = list(getattr(plan, "global_refs", None) or [])
    for seg in getattr(plan, "segments", None) or []:
        candidates.extend(seg.refs or [])
    for ref in candidates:
        key = (getattr(ref, "image_file", "") or "").strip()
        if not key:
            key = f"__tensor_{id(ref.tensor)}"
        if key in seen:
            continue
        tensor = getattr(ref, "tensor", None)
        if tensor is None:
            continue
        # IMAGE 张量 [N,H,W,C]；参考图取首帧即可
        if tensor.ndim == 4 and int(tensor.shape[0]) > 1:
            tensor = tensor[:1]
        seen[key] = tensor.cpu().float()
        if len(seen) >= 3:
            break
    values = list(seen.values())
    return (values[0] if len(values) > 0 else None,
            values[1] if len(values) > 1 else None,
            values[2] if len(values) > 2 else None)


def _all_ref_images(plan):
    """合并 global_refs 与各段 refs，按文件名（退化用张量 id）去重，返回全部参考图 stack 成的 [N,H,W,C] 单张量。

    与 _merged_unique_ref_images 不同：这里不截断前 3 张，返回模型支持的全部（≤ MAX_REFERENCE_IMAGES=9）。
    无参考图时返回 None。下游节点（如放大二采 / 预览）可从这一个端口拿到所有参考图，无需逐个接线。
    """
    seen: dict = {}
    candidates = list(getattr(plan, "global_refs", None) or [])
    for seg in getattr(plan, "segments", None) or []:
        candidates.extend(seg.refs or [])
    tensors = []
    for ref in candidates:
        key = (getattr(ref, "image_file", "") or "").strip()
        if not key:
            key = f"__tensor_{id(ref.tensor)}"
        if key in seen:
            continue
        tensor = getattr(ref, "tensor", None)
        if tensor is None:
            continue
        # IMAGE 张量 [N,H,W,C]；参考图取首帧即可
        if tensor.ndim == 4 and int(tensor.shape[0]) > 1:
            tensor = tensor[:1]
        seen[key] = True
        tensors.append(tensor.cpu().float())
    if not tensors:
        return None
    # 参考图可能来自不同段/不同原始尺寸（如 1086 vs 514），无法直接在 batch 维拼接。
    # 统一对齐到首张的 H、W 后再 cat（下游仅作预览/放大二采链输入，resize 影响极小）。
    target_h, target_w = int(tensors[0].shape[1]), int(tensors[0].shape[2])
    aligned = []
    for t in tensors:
        if int(t.shape[1]) != target_h or int(t.shape[2]) != target_w:
            # IMAGE 为 [1,H,W,C] -> 转 [1,C,H,W] 做插值 -> 转回 [1,H,W,C]
            thw = t.permute(0, 3, 1, 2)
            thw = torch.nn.functional.interpolate(
                thw, size=(target_h, target_w), mode="bilinear", align_corners=False
            )
            t = thw.permute(0, 2, 3, 1).contiguous()
        aligned.append(t)
    return torch.cat(aligned, dim=0)
