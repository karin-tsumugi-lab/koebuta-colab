"""Official emoji catalog shared by validation, prompts and request planning."""
import re

LEGACY = dict(zip(
    ('neutral', 'joy', 'anger', 'sad', 'kind', 'tease', 'anxiety', 'tension',
     'surprise', 'tired', 'whisper', 'giggle', 'fear', 'sleepy', 'resolve'),
    ('', '😆', '😠', '😭', '🫶', '😏', '🥺', '😰', '😲', '😮‍💨',
     '👂', '🤭', '😱', '😪', '💥')))
ADDITIONAL = {
    'panting': '🥵', 'calling': '📢', 'sleep_talking': '😴',
    'fast': '⏩', 'telephone': '📞', 'slow': '🐢', 'pained': '😖',
    'worried': '😟', 'shy': '🫣', 'exasperated': '🙄', 'cheerful': '😊',
    'confident': '😎', 'pleading': '🙏', 'drunken': '🥴', 'humming': '🎵',
    'relieved': '😌', 'questioning': '🤔', 'strong': '💪', 'narration': '📖',
}
EMOTIONS = {**LEGACY, **ADDITIONAL}
EVENT_TAGS = ('😮‍💨', '⏸️', '🤭', '🌬️', '😮', '💋', '🥤', '🤧', '👌', '👃')
EXCLUDED = {
    '👅': '意図した口の音として判別しにくい異音',
    '🤐': '台詞に合わない声の挿入',
    '🥱': 'あくびを再現しにくく異音が多い',
    '😒': '反復で異音になりやすい',
}
ALL_TAGS = tuple(dict.fromkeys([v for v in EMOTIONS.values() if v] + list(EVENT_TAGS) + list(EXCLUDED)))
TAG_PATTERN = re.compile('|'.join(re.escape(t) for t in sorted(ALL_TAGS, key=len, reverse=True)))

def spoken_length(text):
    return len(TAG_PATTERN.sub('', text).strip())

def align_readings(readings, spoken):
    """Align known inserted tags while preserving source tags and exact text."""
    parts = [body for body, issues in readings]
    if any(issues for body, issues in readings):
        return None
    result = []
    offset = 0
    for body in parts:
        start = offset
        for char in body:
            while offset < len(spoken) and spoken[offset] != char:
                match = TAG_PATTERN.match(spoken, offset)
                if not match:
                    return None
                offset = match.end()
            if offset >= len(spoken) or spoken[offset] != char:
                return None
            offset += 1
        result.append(spoken[start:offset])
    while offset < len(spoken):
        match = TAG_PATTERN.match(spoken, offset)
        if not match:
            return None
        result[-1] += match.group()
        offset = match.end()
    return result if ''.join(result) == spoken else None
