"""Self-contained Aozora-style ruby parser, safe hybrid normalizer, and GPU/CPU span scorers."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

_KANJI_CHAR_RE = re.compile(r"[\u4E00-\u9FFF\u3400-\u4DBF々ヶヵ〆〇]")
_PIXIV_RUBY_RE = re.compile(r"\[\[rb:([^\[\]\n>]+?)\s*>\s*([^\[\]\n]+?)\]\]")

ConversionMode = Literal["original", "partial_kana", "auto_select"]


class RubySyntaxError(ValueError):
    """Raised when invalid ruby syntax is encountered in strict mode."""


@dataclass(frozen=True)
class RubyWarning:
    code: str
    position: int
    message: str
    fragment: str


@dataclass(frozen=True)
class RubySpan:
    """A single ruby annotation mapped to character offsets in `plain_text`."""

    surface: str
    reading: str
    plain_start: int
    plain_end: int
    explicit_bar: bool
    source_start: int = 0
    source_end: int = 0


@dataclass(frozen=True)
class RubyParseResult:
    source_text: str
    plain_text: str
    spans: tuple[RubySpan, ...] = ()
    warnings: tuple[RubyWarning, ...] = ()

    @property
    def has_errors(self) -> bool:
        return len(self.warnings) > 0


@dataclass(frozen=True)
class RubySelectionDecision:
    span: RubySpan
    score: float
    selected: Literal["kanji", "kana"]
    output_text: str


@dataclass(frozen=True)
class RubyConversionResult:
    mode: ConversionMode
    plain_text: str
    tts_text: str
    decisions: tuple[RubySelectionDecision, ...] = ()
    warnings: tuple[RubyWarning, ...] = ()


def normalize_safe_ruby_formats(text: str) -> str:
    """Normalize unambiguous ruby syntaxes (pixiv `[[rb:base > reading]]`) to Aozora style."""
    return _PIXIV_RUBY_RE.sub(lambda m: f"｜{m.group(1).strip()}《{m.group(2).strip()}》", text)


def _extract_trailing_kanji(plain_chunks: list[str]) -> str:
    """Extract contiguous trailing kanji characters from `plain_chunks` in O(word_length) time."""
    kanji_chars: list[str] = []
    for chunk in reversed(plain_chunks):
        for ch in reversed(chunk):
            if _KANJI_CHAR_RE.match(ch):
                kanji_chars.append(ch)
            else:
                return "".join(reversed(kanji_chars))
    return "".join(reversed(kanji_chars))


def parse_aozora_ruby(
    text: str,
    *,
    strict: bool = False,
    allow_ascii_bar: bool = True,
    literal_unpaired_bars: bool = False,
) -> RubyParseResult:
    """Parse Aozora/Kakuyomu-style ruby annotations while preserving plain text and positions."""
    bars = {"｜", "|"} if allow_ascii_bar else {"｜"}
    plain_chunks: list[str] = []
    plain_len = 0
    spans: list[RubySpan] = []
    warnings: list[RubyWarning] = []

    def warn(code: str, pos: int, message: str, fragment: str) -> None:
        w = RubyWarning(code=code, position=pos, message=message, fragment=fragment)
        if strict:
            raise RubySyntaxError(f"{code} at {pos}: {message} ({fragment!r})")
        warnings.append(w)

    def append_plain(s: str) -> None:
        nonlocal plain_len
        if s:
            plain_chunks.append(s)
            plain_len += len(s)

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]

        if ch in bars:
            j = i + 1
            while j < n and text[j] not in ("\n", "《", "》") and text[j] not in bars:
                j += 1
            if j >= n or text[j] != "《":
                if not literal_unpaired_bars:
                    warn("E_ORPHAN_BAR", i, "ルビ開始記号 '｜' に対応する '《読み》' がありません", text[i : min(n, i + 16)])
                append_plain(ch)
                i += 1
                continue

            surface = text[i + 1 : j]
            close_idx = text.find("》", j + 1)
            newline_idx = text.find("\n", j + 1)
            open_nested = text.find("《", j + 1)
            if close_idx == -1 or (newline_idx != -1 and newline_idx < close_idx) or (
                open_nested != -1 and open_nested < close_idx
            ):
                warn("E_UNCLOSED_RUBY", j, "ルビの閉じ記号 '》' が見つかりません", text[i : min(n, j + 16)])
                append_plain(text[i : j + 1])
                i = j + 1
                continue

            reading = text[j + 1 : close_idx]
            if not surface:
                warn("E_EMPTY_SURFACE", i, "ルビの親文字が空です", text[i : close_idx + 1])
                append_plain(text[i : close_idx + 1])
                i = close_idx + 1
                continue
            if not reading.strip():
                warn("E_EMPTY_READING", j, "ルビの読みが空です", text[i : close_idx + 1])
                append_plain(surface)
                i = close_idx + 1
                continue

            start = plain_len
            append_plain(surface)
            spans.append(
                RubySpan(
                    surface=surface,
                    reading=reading,
                    plain_start=start,
                    plain_end=plain_len,
                    explicit_bar=True,
                    source_start=i,
                    source_end=close_idx + 1,
                )
            )
            i = close_idx + 1
            continue

        if ch == "《":
            close_idx = text.find("》", i + 1)
            newline_idx = text.find("\n", i + 1)
            open_nested = text.find("《", i + 1)
            if close_idx == -1 or (newline_idx != -1 and newline_idx < close_idx) or (
                open_nested != -1 and open_nested < close_idx
            ):
                warn("E_UNCLOSED_RUBY", i, "ルビの閉じ記号 '》' が見つかりません", text[i : min(n, i + 16)])
                append_plain(ch)
                i += 1
                continue

            reading = text[i + 1 : close_idx]
            surface = _extract_trailing_kanji(plain_chunks)
            if not surface:
                warn("E_NO_KANJI_BASE", i, "'｜' なしのルビの直前に漢字列がありません", text[max(0, i - 6) : close_idx + 1])
                append_plain(text[i : close_idx + 1])
                i = close_idx + 1
                continue

            if not reading.strip():
                warn("E_EMPTY_READING", i, "ルビの読みが空です", text[max(0, i - len(surface)) : close_idx + 1])
                i = close_idx + 1
                continue

            start = plain_len - len(surface)
            spans.append(
                RubySpan(
                    surface=surface,
                    reading=reading,
                    plain_start=start,
                    plain_end=plain_len,
                    explicit_bar=False,
                    source_start=i - len(surface),
                    source_end=close_idx + 1,
                )
            )
            i = close_idx + 1
            continue

        if ch == "》":
            warn("E_ORPHAN_CLOSE", i, "対応する '《' のない '》' があります", text[max(0, i - 6) : min(n, i + 6)])
            append_plain(ch)
            i += 1
            continue

        append_plain(ch)
        i += 1

    return RubyParseResult(
        source_text=text,
        plain_text="".join(plain_chunks),
        spans=tuple(spans),
        warnings=tuple(warnings),
    )


def apply_ruby_selections(
    plain_text: str,
    spans: tuple[RubySpan, ...] | list[RubySpan],
    use_kana: list[bool] | tuple[bool, ...],
) -> str:
    """Reconstruct text from `plain_text` and `spans` according to per-span boolean flags."""
    if len(spans) != len(use_kana):
        raise ValueError(f"spans ({len(spans)}) and use_kana ({len(use_kana)}) length mismatch.")
    if not spans:
        return plain_text

    out: list[str] = []
    cursor = 0
    for span, kana in zip(spans, use_kana):
        if span.plain_start < cursor:
            raise ValueError(f"Overlapping ruby spans detected at {span}.")
        out.append(plain_text[cursor : span.plain_start])
        out.append(span.reading if kana else span.surface)
        cursor = span.plain_end
    out.append(plain_text[cursor:])
    return "".join(out)


SpanScorer = Callable[[str, str, int, int, str], float]


def score_ruby_span(plain, span, scorer, threshold, single_token_threshold):
    repl_text = (
        plain[: span.plain_start]
        + span.reading
        + plain[span.plain_end :]
    )
    score_span_fn = getattr(scorer, "score_span", None)
    if callable(score_span_fn):
        score_val, span_tokens = score_span_fn(
            plain,
            repl_text,
            span.plain_start,
            span.plain_end,
            span.reading,
        )
        score = float(score_val)
        eff_threshold = (
            single_token_threshold
            if (single_token_threshold is not None and span_tokens == 1)
            else threshold
        )
    else:
        score = float(
            scorer(
                plain,
                repl_text,
                span.plain_start,
                span.plain_end,
                span.reading,
            )
        )
        eff_threshold = threshold
    is_kana = score <= eff_threshold
    return score, is_kana


def convert_ruby_text(
    text: str,
    *,
    mode: ConversionMode = "partial_kana",
    threshold: float = 0.8327,
    single_token_threshold: float | None = 0.65,
    scorer: SpanScorer | None = None,
    strict: bool = False,
    allow_ascii_bar: bool = True,
) -> RubyConversionResult:
    """Convert ruby-annotated text into TTS input text."""
    parsed = parse_aozora_ruby(text, strict=strict, allow_ascii_bar=allow_ascii_bar)

    if mode == "original":
        decisions = tuple(
            RubySelectionDecision(span=s, score=1.0, selected="kanji", output_text=s.surface)
            for s in parsed.spans
        )
        return RubyConversionResult(
            mode=mode,
            plain_text=parsed.plain_text,
            tts_text=parsed.plain_text,
            decisions=decisions,
            warnings=parsed.warnings,
        )

    if mode == "partial_kana":
        use_kana = [True] * len(parsed.spans)
        tts_text = apply_ruby_selections(parsed.plain_text, parsed.spans, use_kana)
        decisions = tuple(
            RubySelectionDecision(span=s, score=0.0, selected="kana", output_text=s.reading)
            for s in parsed.spans
        )
        return RubyConversionResult(
            mode=mode,
            plain_text=parsed.plain_text,
            tts_text=tts_text,
            decisions=decisions,
            warnings=parsed.warnings,
        )

    if mode == "auto_select":
        if not parsed.spans:
            return RubyConversionResult(
                mode=mode,
                plain_text=parsed.plain_text,
                tts_text=parsed.plain_text,
                decisions=(),
                warnings=parsed.warnings,
            )
        if scorer is None:
            raise ValueError("auto_select mode requires a `scorer` callable.")

        decisions_list: list[RubySelectionDecision] = []
        use_kana_flags: list[bool] = []
        for span in parsed.spans:
            score, is_kana = score_ruby_span(
                parsed.plain_text, span, scorer, threshold, single_token_threshold
            )
            use_kana_flags.append(is_kana)
            decisions_list.append(
                RubySelectionDecision(
                    span=span,
                    score=score,
                    selected="kana" if is_kana else "kanji",
                    output_text=span.reading if is_kana else span.surface,
                )
            )

        tts_text = apply_ruby_selections(parsed.plain_text, parsed.spans, use_kana_flags)
        return RubyConversionResult(
            mode=mode,
            plain_text=parsed.plain_text,
            tts_text=tts_text,
            decisions=tuple(decisions_list),
            warnings=parsed.warnings,
        )

    raise ValueError(f"Unsupported conversion mode: {mode!r}")


class _BaseEncoderSpanScorer:
    """Shared span cosine similarity logic with single-utterance bounded cache."""

    backbone: object
    projector: object
    text_norm: object
    hf_tokenizer: object
    bos_token_id: int | None
    device: object
    metric: Literal["cos_cond", "cos_bb"]
    _cached_text: str | None
    _cached_encoded: tuple[object, object] | None

    def _encode_hidden(self, text: str):
        import torch

        ids = self.hf_tokenizer.encode(text, add_special_tokens=False)
        if self.bos_token_id is not None:
            ids = [int(self.bos_token_id)] + ids
        input_ids = torch.tensor([ids], dtype=torch.long, device=self.device)
        mask = torch.ones_like(input_ids, dtype=torch.bool)
        with torch.no_grad():
            if self.metric == "cos_bb":
                hidden = self.backbone(input_ids, mask)[0]
            else:
                hidden = self.text_norm(self.projector(self.backbone, input_ids, mask))[0]
        enc = self.hf_tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        return hidden.float(), enc["offset_mapping"]

    def score_span(
        self,
        plain_text: str,
        repl_text: str,
        char_start: int,
        char_end: int,
        repl_str: str,
    ) -> tuple[float, int]:
        import torch.nn.functional as F

        if self._cached_text != plain_text or self._cached_encoded is None:
            self._cached_text = plain_text
            self._cached_encoded = self._encode_hidden(plain_text)
        hx, off_x = self._cached_encoded
        hr, off_r = self._encode_hidden(repl_text)

        bos_offset = 1 if self.bos_token_id is not None else 0
        sx = [i + bos_offset for i, (a, b) in enumerate(off_x) if max(a, char_start) < min(b, char_end)]
        r_end = char_start + len(repl_str)
        sr = [i + bos_offset for i, (a, b) in enumerate(off_r) if max(a, char_start) < min(b, r_end)]
        if not sx or not sr:
            return 0.0, 0

        vx = hx[sx[0] : sx[-1] + 1].mean(dim=0)
        vr = hr[sr[0] : sr[-1] + 1].mean(dim=0)
        return float(F.cosine_similarity(vx.unsqueeze(0), vr.unsqueeze(0)).item()), len(sx)

    def __call__(
        self,
        plain_text: str,
        repl_text: str,
        char_start: int,
        char_end: int,
        repl_str: str,
    ) -> float:
        score, _ = self.score_span(plain_text, repl_text, char_start, char_end, repl_str)
        return score


class RuntimeSpanScorer(_BaseEncoderSpanScorer):
    """Span cosine similarity scorer backed by an already-loaded Irodori-TTS runtime (GPU or CPU)."""

    def __init__(self, runtime, metric: Literal["cos_cond", "cos_bb"] = "cos_cond") -> None:
        model = runtime.model
        if getattr(model, "pretrained_text_backbone", None) is None:
            raise RuntimeError("このTTSモデルは事前学習済みテキストエンコーダを持たないため auto_select を使用できません")
        self.backbone = model.pretrained_text_backbone
        self.projector = model.text_encoder
        self.text_norm = model.text_norm
        self.hf_tokenizer = runtime.tokenizer.tokenizer
        self.bos_token_id = runtime.tokenizer.bos_token_id if runtime.tokenizer.add_bos else None
        self.device = runtime.model_device
        self.metric = metric
        self._cached_text = None
        self._cached_encoded = None


class StandaloneSpanScorer(_BaseEncoderSpanScorer):
    """Self-contained CPU/GPU scorer loading only text encoder weights from safetensors."""

    def __init__(
        self,
        *,
        model_repo: str = "Aratako/Irodori-TTS-v4.1-Small",
        model_revision: str | None = "2b28324dc263ed5e6638b3cf3dd94c82ead07b4b",
        tokenizer_repo: str = "sbintuitions/modernbert-ja-310m",
        tokenizer_revision: str | None = "77675fc96a7e445e982e2ba90246b816efc74ec6",
        metric: Literal["cos_cond", "cos_bb"] = "cos_cond",
        device: str = "cpu",
    ) -> None:
        import json
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
        from huggingface_hub import hf_hub_download
        from safetensors import safe_open
        from transformers import AutoConfig, AutoModel, AutoTokenizer

        class _RMSNorm(nn.Module):
            def __init__(self, dim: int, eps: float = 1e-5) -> None:
                super().__init__()
                self.weight = nn.Parameter(torch.ones(dim))
                self.eps = eps

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                rms = torch.rsqrt(x.pow(2).mean(dim=-1, keepdim=True) + self.eps)
                return x * rms * self.weight

        class _BackboneWrapper(nn.Module):
            def __init__(self, cfg_dict: dict) -> None:
                super().__init__()
                raw = dict(cfg_dict)
                mtype = raw.pop("model_type")
                cfg = AutoConfig.for_model(mtype, **raw)
                self.backbone = AutoModel.from_config(cfg, trust_remote_code=False).float()
                self.hidden_size = int(cfg.hidden_size)

            def forward(self, input_ids: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
                out = self.backbone(input_ids=input_ids, attention_mask=mask, return_dict=True).last_hidden_state
                return out * mask.unsqueeze(-1).to(dtype=out.dtype)

        class _ProjectorWrapper(nn.Module):
            def __init__(self, in_dim: int, out_dim: int, ptype: str, ratio: float, eps: float) -> None:
                super().__init__()
                self.ptype = ptype
                self.projector = nn.Linear(in_dim, out_dim, bias=True)
                if ptype == "residual_mlp":
                    hdim = max(1, int(round(out_dim * float(ratio))))
                    self.residual_norm = _RMSNorm(in_dim, eps=eps)
                    self.residual_up = nn.Linear(in_dim, hdim, bias=True)
                    self.residual_down = nn.Linear(hdim, out_dim, bias=True)

            def forward(self, bb: _BackboneWrapper, input_ids: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
                state = bb(input_ids, mask)
                proj = self.projector(state)
                if self.ptype == "residual_mlp":
                    res = F.silu(self.residual_up(self.residual_norm(state)))
                    proj = proj + self.residual_down(res)
                return proj * mask.unsqueeze(-1).to(dtype=proj.dtype)

        self.metric = metric
        self.device = torch.device(device)
        ckpt_path = hf_hub_download(model_repo, "model.safetensors", revision=model_revision)
        with safe_open(ckpt_path, framework="pt", device="cpu") as f:
            meta = f.metadata() or {}
            full_cfg = json.loads(meta["config_json"])
            mcfg = full_cfg.get("model", full_cfg)
            text_enc_cfg = json.loads(meta["text_encoder_config_json"])

            backbone = _BackboneWrapper(text_enc_cfg)
            projector = _ProjectorWrapper(
                backbone.hidden_size,
                int(mcfg.get("text_dim", 512)),
                str(mcfg.get("pretrained_projector_type", "residual_mlp")),
                float(mcfg.get("pretrained_projector_hidden_ratio", 2.0)),
                float(mcfg.get("norm_eps", 1e-5)),
            )
            text_norm = _RMSNorm(int(mcfg.get("text_dim", 512)), eps=float(mcfg.get("norm_eps", 1e-5)))

            bb_state, proj_state, norm_state = {}, {}, {}
            for k in f.keys():
                if k.startswith("pretrained_text_backbone."):
                    bb_state[k[len("pretrained_text_backbone.") :]] = f.get_tensor(k).float()
                elif k.startswith("text_encoder."):
                    proj_state[k[len("text_encoder.") :]] = f.get_tensor(k).float()
                elif k.startswith("text_norm."):
                    norm_state[k[len("text_norm.") :]] = f.get_tensor(k).float()

        backbone.load_state_dict(bb_state, strict=True)
        projector.load_state_dict(proj_state, strict=True)
        text_norm.load_state_dict(norm_state, strict=True)

        self.backbone = backbone.to(self.device).eval()
        self.projector = projector.to(self.device).eval()
        self.text_norm = text_norm.to(self.device).eval()
        self.hf_tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_repo,
            revision=tokenizer_revision,
            use_fast=True,
        )
        self.bos_token_id = (
            int(self.hf_tokenizer.bos_token_id)
            if bool(mcfg.get("text_add_bos", True)) and self.hf_tokenizer.bos_token_id is not None
            else None
        )
        self._cached_text = None
        self._cached_encoded = None
