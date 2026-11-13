"""
ComfyUI Custom Node Patch for MiniMax-H3-Image GGUF Models
Repository: https://huggingface.co/Abiray/MiniMax-H3-Image-GGUF

Installation:
Place this file directly inside your `ComfyUI/custom_nodes/` folder and restart ComfyUI.

What this fixes automatically in memory (without modifying ComfyUI core files on disk):
1. Injects the official 6-step PDD sigma schedule (`pdd_sigmas`) when UnetLoaderGGUF passes metadata=None.
2. Enforces `pdd_steps = 6` and `latents_dim = 24` on `MiniMaxH3Image` & `MiniMaxH3ImageModel` so flattened
   1D FP32 GGUF output heads slice cleanly from 576 -> 96 -> 24 channels instead of 144 channels.
3. Safeguards `MiniMaxH3ImageModelSampling` against missing `pdd_sigmas` keys in `unet_config`.
"""

import torch
import comfy.model_base
import comfy.ldm.minimax.model
import comfy.ldm.minimax.sampling

DEFAULT_PDD_SIGMAS = [
    1.0,
    0.9675236940383911,
    0.8875485062599182,
    0.75,
    0.5327739119529724,
    0.23200887441635132,
    0.0,
]

# 1. Patch MiniMaxH3Image in comfy.model_base 
if hasattr(comfy.model_base, "MiniMaxH3Image"):
    _orig_mb_init = comfy.model_base.MiniMaxH3Image.__init__

    if not getattr(_orig_mb_init, "_is_minimax_gguf_patched", False):
        def _patched_mb_init(self, model_config, *args, **kwargs):
            if model_config.unet_config.get("pdd_sigmas") is None:
                model_config.unet_config["pdd_sigmas"] = list(DEFAULT_PDD_SIGMAS)
            sigmas = model_config.unet_config["pdd_sigmas"]
            model_config.unet_config["pdd_steps"] = len(sigmas) - 1
            model_config.unet_config["latents_dim"] = 24
            return _orig_mb_init(self, model_config, *args, **kwargs)

        _patched_mb_init._is_minimax_gguf_patched = True
        comfy.model_base.MiniMaxH3Image.__init__ = _patched_mb_init

# 2. Patch MiniMaxH3ImageModel in comfy.ldm.minimax.model 
if hasattr(comfy.ldm.minimax.model, "MiniMaxH3ImageModel"):
    _orig_mm_init = comfy.ldm.minimax.model.MiniMaxH3ImageModel.__init__

    if not getattr(_orig_mm_init, "_is_minimax_gguf_patched", False):
        def _patched_mm_init(self, pdd_sigmas=None, pdd_steps=6, **kwargs):
            if pdd_sigmas is None:
                pdd_sigmas = list(DEFAULT_PDD_SIGMAS)
            pdd_steps = len(pdd_sigmas) - 1
            kwargs["latents_dim"] = 24
            return _orig_mm_init(self, pdd_sigmas=pdd_sigmas, pdd_steps=pdd_steps, **kwargs)

        _patched_mm_init._is_minimax_gguf_patched = True
        comfy.ldm.minimax.model.MiniMaxH3ImageModel.__init__ = _patched_mm_init

# 3. Patch MiniMaxH3ImageModelSampling in comfy.ldm.minimax.sampling 
if hasattr(comfy.ldm.minimax.sampling, "MiniMaxH3ImageModelSampling"):
    _orig_samp_init = comfy.ldm.minimax.sampling.MiniMaxH3ImageModelSampling.__init__

    if not getattr(_orig_samp_init, "_is_minimax_gguf_patched", False):
        def _patched_samp_init(self, model_config, *args, **kwargs):
            if model_config is not None and hasattr(model_config, "unet_config"):
                if model_config.unet_config.get("pdd_sigmas") is None:
                    model_config.unet_config["pdd_sigmas"] = list(DEFAULT_PDD_SIGMAS)
            return _orig_samp_init(self, model_config, *args, **kwargs)

        _patched_samp_init._is_minimax_gguf_patched = True
        comfy.ldm.minimax.sampling.MiniMaxH3ImageModelSampling.__init__ = _patched_samp_init

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

print("\033[92m[MiniMax-H3-Image GGUF Fix] Applied 6-step pdd_sigmas & 24-channel latent patch for UnetLoaderGGUF.\033[0m")
