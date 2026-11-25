"""Drama-3 Japanese inline tag catalog, control-token guards, and v1 emotion fallback."""
from __future__ import annotations

import re

# Matches Drama-3 inline stage/emotion tags such as [囁き], [笑いながら], [吐息]
INLINE_TAG_RE = re.compile(r"\[[^\[\]\r\n]{1,120}\]")

# Fish Audio Drama 3 base model multi-speaker / special control tokens (forbidden in single-speaker JA mode)
FORBIDDEN_CONTROL_TOKEN_RE = re.compile(r"<\|[^|\r\n]{1,64}\|>")

# Official training-set Japanese inline tags from Aratako/Drama-3-Japanese TAG_LIST.md
KNOWN_DRAMA3_TAGS: frozenset[str] = frozenset({
    "[あくび]", "[うっとりと]", "[うめき声]", "[からかうように]", "[か細い声で]",
    "[くすくす笑い]", "[しゃっくり]", "[すすり泣き]", "[ためらいがちに]", "[ため息]",
    "[どもりながら]", "[ゆっくりと]", "[ゆっくりと強調して]", "[エコー]", "[スピーカー越しに]",
    "[ナレーション]", "[パニックで]", "[パニックになって]", "[リズミカルに]", "[リップノイズ]",
    "[リバーブ]", "[一呼吸おいて]", "[一気にまくしたてて]", "[不満げに]", "[優しく]",
    "[冷たく]", "[力なく]", "[力を込めて]", "[力強く]", "[動揺して]",
    "[勢いに任せて]", "[勢いよく]", "[口を塞がれて]", "[叫び]", "[叫ぶように]",
    "[吐き捨てるように]", "[吐息]", "[含み笑い]", "[呆れたように]", "[咆哮]",
    "[咳き込みながら]", "[咳払い]", "[唸り声]", "[唾液の音]", "[喜びを爆発させて]",
    "[喜びを込めて]", "[嗚咽]", "[嘲笑うように]", "[囁き]", "[声が震えて]",
    "[声を張って]", "[声を枯らして]", "[声を荒らげて]", "[声を震わせて]", "[嬉しそうに]",
    "[安堵して]", "[寝息]", "[寝言]", "[小さな悲鳴]", "[少し間を置いて]",
    "[弱々しく]", "[徐々に怒りを込めて]", "[徐々に感情を込めて]", "[得意げに]", "[心配そうに]",
    "[怒りを込めて]", "[怒鳴り声で]", "[急いで]", "[恥ずかしそうに]", "[息も絶え絶えに]",
    "[息をのむ]", "[息をのむ音]", "[息を吐きながら]", "[息を吐き出して]", "[息を吐き出す]",
    "[息を吐き出す音]", "[息を吐く音]", "[息を吸う音]", "[息切れ]", "[息多めに]",
    "[息遣い]", "[悔しげに]", "[悔しそうに]", "[悲しげに]", "[悲鳴]",
    "[感動して]", "[感嘆して]", "[感嘆の声]", "[感心したように]", "[感心して]",
    "[慌てて]", "[懇願するように]", "[拗ねたように]", "[拗ねて]", "[挑発するように]",
    "[早口で]", "[明るく]", "[楽しげに]", "[歌うように]", "[気だるげに]",
    "[水音]", "[泣きそうに]", "[泣きながら]", "[泣き叫び]", "[深い溜息]",
    "[満足げに]", "[焦って]", "[照れながら]", "[独り言のように]", "[甘えた声で]",
    "[甘えて]", "[甘えるように]", "[甲高い笑い声]", "[疑問の声]", "[皮肉っぽく]",
    "[相槌]", "[眠そうに]", "[笑い]", "[笑いながら]", "[笑い声]",
    "[絶叫]", "[耳元で]", "[自信なさげに]", "[興奮して]", "[興奮気味に]",
    "[舌なめずり]", "[舌打ち]", "[苛立たしげに]", "[苛立って]", "[苦しげな息遣い]",
    "[苦しげに]", "[苦しそうに]", "[荒い息遣い]", "[誘うように]", "[軽蔑するように]",
    "[遠くから]", "[酔っ払って]", "[電話越しに]", "[驚いて]", "[高笑い]",
    "[鼻で笑う]", "[鼻をすする音]", "[鼻を鳴らして]", "[鼻を鳴らす]", "[鼻を鳴らす音]",
    # NSFW tags from official TAG_LIST.md
    "[キス音]", "[チュパ音]", "[喘ぎ]", "[喘ぎながら]", "[喘ぎ声]",
    "[激しい喘ぎ]", "[絶頂]", "[絶頂の叫び]", "[耳舐め]", "[舌を絡める音]",
})

V1_EMOTION_TO_DRAMA3: dict[str, str] = {
    "neutral": "",
    "joy": "[嬉しそうに]",
    "anger": "[怒りを込めて]",
    "sad": "[悲しげに]",
    "kind": "[優しく]",
    "tease": "[からかうように]",
    "anxiety": "[心配そうに]",
    "tension": "[焦って]",
    "surprise": "[驚いて]",
    "tired": "[ため息]",
    "whisper": "[囁き]",
    "giggle": "[くすくす笑い]",
    "fear": "[声が震えて]",
    "sleepy": "[眠そうに]",
    "resolve": "[力強く]",
    "panting": "[息切れ]",
    "calling": "[声を張って]",
    "sleep_talking": "[寝言]",
    "fast": "[早口で]",
    "telephone": "[電話越しに]",
    "slow": "[ゆっくりと]",
    "pained": "[苦しそうに]",
    "worried": "[心配そうに]",
    "shy": "[恥ずかしそうに]",
    "exasperated": "[呆れたように]",
    "cheerful": "[明るく]",
    "confident": "[得意げに]",
    "pleading": "[懇願するように]",
    "drunken": "[酔っ払って]",
    "humming": "[歌うように]",
    "relieved": "[安堵して]",
    "questioning": "[疑問の声]",
    "strong": "[力を込めて]",
    "narration": "[ナレーション]",
}

EMOJI_TO_DRAMA3: dict[str, str] = {
    "😆": "[嬉しそうに]",
    "😠": "[怒りを込めて]",
    "😭": "[泣きながら]",
    "🫶": "[優しく]",
    "😏": "[からかうように]",
    "🥺": "[心配そうに]",
    "😰": "[焦って]",
    "😲": "[驚いて]",
    "😮‍💨": "[ため息]",
    "👂": "[囁き]",
    "🤭": "[くすくす笑い]",
    "😱": "[悲鳴]",
    "😪": "[眠そうに]",
    "💥": "[力強く]",
    "🥵": "[息切れ]",
    "📢": "[声を張って]",
    "😴": "[寝言]",
    "⏩": "[早口で]",
    "📞": "[電話越しに]",
    "🐢": "[ゆっくりと]",
    "😖": "[苦しそうに]",
    "😟": "[心配そうに]",
    "🫣": "[恥ずかしそうに]",
    "🙄": "[呆れたように]",
    "😊": "[明るく]",
    "😎": "[得意げに]",
    "🙏": "[懇願するように]",
    "🥴": "[酔っ払って]",
    "🎵": "[歌うように]",
    "😌": "[安堵して]",
    "🤔": "[疑問の声]",
    "💪": "[力を込めて]",
    "📖": "[ナレーション]",
    "⏸️": "[少し間を置いて]",
    "⏸": "[少し間を置いて]",
    "🌬️": "[吐息]",
    "🌬": "[吐息]",
    "😮": "[息をのむ]",
    "💋": "[キス音]",
    "🥤": "[水音]",
    "🤧": "[咳払い]",
    "👌": "[相槌]",
    "👃": "[鼻をすする音]",
    "🥱": "[あくび]",
    "😒": "[不満げに]",
    "👅": "[舌なめずり]",
    "🤐": "[口を塞がれて]",
}

_EMOJI_RE = re.compile("|".join(re.escape(k) for k in sorted(EMOJI_TO_DRAMA3, key=len, reverse=True)))
_MIXED_BRACKET_RE = re.compile(r"\[[^\[\]\r\n]*］|［[^［］\r\n]*\]")


def find_forbidden_control_tokens(text: str) -> list[str]:
    return FORBIDDEN_CONTROL_TOKEN_RE.findall(text)


def find_inline_brackets(text: str) -> list[str]:
    return INLINE_TAG_RE.findall(text)


def find_unknown_inline_tags(text: str) -> list[str]:
    """Return bracketed expressions in `text` that are not in official TAG_LIST.md."""
    return [tag for tag in INLINE_TAG_RE.findall(text) if tag not in KNOWN_DRAMA3_TAGS]


def find_malformed_inline_tags(text: str) -> list[str]:
    """Detect half/full-width mixed brackets (e.g. `[囁き］`) or unclosed `[` / `]`."""
    issues = _MIXED_BRACKET_RE.findall(text)
    remainder = _MIXED_BRACKET_RE.sub("", INLINE_TAG_RE.sub("", text))
    if "[" in remainder or "]" in remainder:
        issues.append("unclosed_halfwidth_bracket")
    return issues


def convert_v1_emojis_to_drama3(text: str) -> tuple[str, int]:
    """Replace known Irodori emoji tags with Drama-3 bracketed Japanese tags."""
    count = 0

    def _rep(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return EMOJI_TO_DRAMA3[match.group(0)]

    converted = _EMOJI_RE.sub(_rep, text)
    return converted, count


def strip_inline_tags(text: str) -> str:
    return INLINE_TAG_RE.sub("", text).strip()


def spoken_length(text: str) -> int:
    """Character count excluding Drama-3 inline tags and leading/trailing whitespace."""
    return len(strip_inline_tags(text))
