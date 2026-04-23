#!/usr/bin/env python3
"""FastAPI server exposing Irodori-TTS inference as an HTTP API for SillyTavern integration."""
from __future__ import annotations

import sys
from pathlib import Path

# When invoked as ./SillyTavern-Irodori-TTS-Extension/api_server.py from the
# Irodori-TTS root, the package lives one level up — add it to sys.path.
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import argparse
import io
import threading
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

import torchaudio
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from irodori_tts.inference_runtime import (
    InferenceRuntime,
    RuntimeKey,
    SamplingRequest,
    default_runtime_device,
)

if TYPE_CHECKING:
    import torch

app = FastAPI(title="Irodori-TTS API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_runtime: InferenceRuntime | None = None
_ref_dir: Path = Path("references")
_model_type: str = "base"

SUPPORTED_AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


# --------------------------------------------------------------------------- #
#  Request / Response models                                                   #
# --------------------------------------------------------------------------- #

class TtsRequest(BaseModel):
    text: str
    voice_id: str = "no_ref"
    caption: str | None = None
    num_steps: int = 40
    cfg_scale_text: float = 3.0
    cfg_scale_caption: float = 3.0
    cfg_scale_speaker: float = 5.0
    cfg_guidance_mode: str = "independent"
    seed: int | None = None
    seconds: float = 30.0
    trim_tail: bool = True


class VoiceObject(BaseModel):
    name: str
    voice_id: str
    preview_url: str | None = None
    lang: str = "ja"


# --------------------------------------------------------------------------- #
#  Reference caching — injected into InferenceRuntime without modifying it    #
# --------------------------------------------------------------------------- #

def _inject_reference_caching(runtime: InferenceRuntime, cache_size: int = 16) -> None:
    """Monkey-patch an LRU reference-latent cache onto an existing InferenceRuntime.

    Works with the stock Irodori-TTS (2708d3c baseline) without any changes to
    irodori_tts/inference_runtime.py.
    """
    if cache_size <= 0:
        return

    import torch

    cache: OrderedDict[
        tuple[str, str, int, int, float | None, float | None, bool, int, str],
        tuple[torch.Tensor, torch.Tensor],
    ] = OrderedDict()
    cache_lock = threading.Lock()
    original_load = runtime._load_reference_latent

    def _build_key(*, req: SamplingRequest, runtime_dtype: torch.dtype):
        if req.no_ref:
            return None
        if req.ref_latent is not None:
            kind, ref_path = "latent", req.ref_latent
            normalize_db, ensure_max = None, False
        elif req.ref_wav is not None:
            kind, ref_path = "wav", req.ref_wav
            normalize_db = (
                None if req.ref_normalize_db is None else float(req.ref_normalize_db)
            )
            ensure_max = bool(req.ref_ensure_max)
        else:
            return None
        resolved = Path(ref_path).expanduser().resolve()
        try:
            stat = resolved.stat()
        except OSError:
            return None
        max_ref_seconds = (
            None
            if req.max_ref_seconds is None or req.max_ref_seconds <= 0
            else float(req.max_ref_seconds)
        )
        return (
            kind,
            str(resolved),
            int(stat.st_mtime_ns),
            int(stat.st_size),
            max_ref_seconds,
            normalize_db,
            ensure_max,
            int(runtime.model_cfg.latent_patch_size),
            str(runtime_dtype),
        )

    def _cached_load_reference_latent(
        *,
        req: SamplingRequest,
        batch_size: int,
        messages: list[str],
    ):
        import torch
        runtime_dtype = next(runtime.model.parameters()).dtype
        key = _build_key(req=req, runtime_dtype=runtime_dtype)

        if key is not None:
            with cache_lock:
                cached = cache.get(key)
                if cached is not None:
                    cache.move_to_end(key)
                    messages.append("info: reused cached reference latent.")
                    r, m = cached
                    if batch_size > 1:
                        return r.repeat(batch_size, 1, 1), m.repeat(batch_size, 1)
                    return r, m

        # Call the original bound method; request batch_size=1 so we can cache the
        # single-item result and then expand it for larger batches.
        effective_batch = 1 if key is not None else batch_size
        result = original_load(req=req, batch_size=effective_batch, messages=messages)

        if key is not None and result[0] is not None:
            r_single, m_single = result
            with cache_lock:
                cache[key] = (r_single.contiguous(), m_single.contiguous())
                cache.move_to_end(key)
                while len(cache) > cache_size:
                    cache.popitem(last=False)
            if batch_size > 1:
                return r_single.repeat(batch_size, 1, 1), m_single.repeat(batch_size, 1)
            return r_single, m_single

        return result

    original_unload = runtime.unload

    def _unload_with_cache_clear():
        with cache_lock:
            cache.clear()
        original_unload()

    runtime._load_reference_latent = _cached_load_reference_latent
    runtime.unload = _unload_with_cache_clear


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _audio_to_wav_bytes(audio, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    try:
        torchaudio.save(buf, audio, sample_rate, format="wav")
    except RuntimeError:
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, audio.squeeze(0).numpy(), sample_rate, format="WAV")
    buf.seek(0)
    return buf.read()


_SPLIT_THRESHOLD = 100
_SENTENCE_ENDINGS = "。！？…\n"


def _split_text(text: str) -> list[str]:
    """Split text into chunks of at most _SPLIT_THRESHOLD characters.

    Splits on newlines first, then on Japanese sentence-ending punctuation.
    """
    import re

    # Normalise CRLF
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    def _split_segment(seg: str) -> list[str]:
        if len(seg) <= _SPLIT_THRESHOLD:
            return [seg] if seg.strip() else []
        # Split on sentence-ending punctuation, keeping the delimiter
        parts = re.split(r'(?<=[。！？…])', seg)
        chunks: list[str] = []
        current = ""
        for part in parts:
            if len(current) + len(part) <= _SPLIT_THRESHOLD:
                current += part
            else:
                if current:
                    chunks.append(current)
                # If part itself is still too long, hard-cut it
                while len(part) > _SPLIT_THRESHOLD:
                    chunks.append(part[:_SPLIT_THRESHOLD])
                    part = part[_SPLIT_THRESHOLD:]
                current = part
        if current:
            chunks.append(current)
        return [c for c in chunks if c.strip()]

    chunks: list[str] = []
    for line in text.split("\n"):
        chunks.extend(_split_segment(line))
    return chunks or [text]


def _resolve_ref_wav(voice_id: str) -> str | None:
    """Strip ref_ prefix and return absolute path, or None for no_ref."""
    if voice_id == "no_ref" or not voice_id:
        return None
    filename = voice_id.removeprefix("ref_")
    ref_path = _ref_dir / filename
    if not ref_path.exists():
        raise HTTPException(status_code=404, detail=f"Reference audio not found: {filename}")
    return str(ref_path)


# --------------------------------------------------------------------------- #
#  Endpoints                                                                   #
# --------------------------------------------------------------------------- #

@app.get("/health")
def health():
    if _runtime is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {
        "status": "ready",
        "model_type": _model_type,
        "ref_dir": str(_ref_dir),
    }


@app.get("/voices", response_model=list[VoiceObject])
def list_voices():
    voices: list[VoiceObject] = [
        VoiceObject(name="[No Reference]", voice_id="no_ref", lang="ja")
    ]
    print(f"[voices] scanning ref_dir: {_ref_dir} (exists={_ref_dir.exists()})", flush=True)
    if _ref_dir.exists():
        found = []
        for p in sorted(_ref_dir.iterdir()):
            print(f"[voices]   found: {p.name!r}  is_file={p.is_file()}  suffix={p.suffix.lower()!r}", flush=True)
            if p.is_file() and p.suffix.lower() in SUPPORTED_AUDIO_EXTS:
                found.append(p)
                voices.append(VoiceObject(
                    name=f"[Ref] {p.name}",
                    voice_id=f"ref_{p.name}",
                    lang="ja",
                ))
        print(f"[voices] {len(found)} reference file(s) added.", flush=True)
    else:
        print(f"[voices] ref_dir does not exist: {_ref_dir}", flush=True)
    return voices


@app.post("/tts")
def generate_tts(req: TtsRequest):
    if _runtime is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    ref_wav_path = _resolve_ref_wav(req.voice_id)
    use_no_ref = ref_wav_path is None
    use_caption = (
        _runtime.model_cfg.use_caption_condition
        and req.caption is not None
        and req.caption.strip() != ""
    )
    use_speaker = _runtime.model_cfg.use_speaker_condition and not use_no_ref

    cfg_scale_text = req.cfg_scale_text
    cfg_scale_caption = req.cfg_scale_caption if use_caption else 0.0
    cfg_scale_speaker = req.cfg_scale_speaker if use_speaker else 0.0

    def _synthesize_one(text: str):
        return _runtime.synthesize(
            SamplingRequest(
                text=text,
                caption=req.caption if use_caption else None,
                ref_wav=ref_wav_path,
                no_ref=use_no_ref,
                num_steps=req.num_steps,
                cfg_scale_text=cfg_scale_text,
                cfg_scale_caption=cfg_scale_caption,
                cfg_scale_speaker=cfg_scale_speaker,
                cfg_guidance_mode=req.cfg_guidance_mode,
                seed=req.seed,
                seconds=req.seconds,
                trim_tail=req.trim_tail,
            ),
        )

    chunks = _split_text(req.text)
    if len(chunks) > 1:
        lengths = [len(c) for c in chunks]
        print(
            f"[tts] split into {len(chunks)} chunks "
            f"(char lengths: {lengths}, total: {sum(lengths)})",
            flush=True,
        )

    try:
        import torch
        results = [_synthesize_one(chunk) for chunk in chunks]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if len(results) == 1:
        audio = results[0].audio
    else:
        audio = torch.cat([r.audio for r in results], dim=-1)

    wav_bytes = _audio_to_wav_bytes(audio, results[0].sample_rate)
    return Response(content=wav_bytes, media_type="audio/wav")


# --------------------------------------------------------------------------- #
#  Startup                                                                     #
# --------------------------------------------------------------------------- #

def _load_runtime(args: argparse.Namespace) -> None:
    global _runtime, _ref_dir, _model_type

    _ref_dir = Path(args.ref_dir).expanduser().resolve()
    _ref_dir.mkdir(parents=True, exist_ok=True)

    checkpoint = args.checkpoint
    if checkpoint is None:
        from huggingface_hub import hf_hub_download
        checkpoint = hf_hub_download(repo_id=args.hf_checkpoint, filename="model.safetensors")

    key = RuntimeKey(
        checkpoint=str(checkpoint),
        model_device=args.model_device,
        codec_repo=args.codec_repo,
        model_precision=args.model_precision,
        codec_device=args.codec_device or args.model_device,
        codec_precision=args.codec_precision or args.model_precision,
        compile_model=bool(args.compile_model),
        compile_dynamic=bool(args.compile_dynamic),
    )
    _runtime = InferenceRuntime.from_key(key)
    _inject_reference_caching(_runtime, cache_size=int(args.reference_cache_size))
    _model_type = "voicedesign" if _runtime.model_cfg.use_caption_condition else "base"
    print(f"[api_server] Runtime ready. model_type={_model_type}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Irodori-TTS HTTP API server for SillyTavern.")
    ckpt_group = parser.add_mutually_exclusive_group(required=True)
    ckpt_group.add_argument("--checkpoint", default=None, help="Local checkpoint path (.pt/.safetensors).")
    ckpt_group.add_argument("--hf-checkpoint", default=None, help="Hugging Face repo id.")
    parser.add_argument("--ref-dir", default="references", help="Directory containing reference audio files.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--model-device", default=default_runtime_device())
    parser.add_argument("--model-precision", choices=["fp32", "bf16"], default="fp32")
    parser.add_argument("--codec-device", default=None)
    parser.add_argument("--codec-precision", default=None)
    parser.add_argument("--codec-repo", default="Aratako/Semantic-DACVAE-Japanese-32dim")
    parser.add_argument(
        "--compile-model",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable torch.compile for core inference methods.",
    )
    parser.add_argument(
        "--compile-dynamic",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use dynamic=True when --compile-model is enabled.",
    )
    parser.add_argument(
        "--reference-cache-size",
        type=int,
        default=16,
        help="Number of prepared reference latents to keep in the in-memory LRU cache (0 to disable).",
    )
    args = parser.parse_args()

    _load_runtime(args)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
