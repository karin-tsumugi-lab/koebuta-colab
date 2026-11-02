"""Explicit Gemini API model IDs. Selection never triggers automatic fallback."""
DEFAULT_MODEL = 'gemini-3.5-flash-lite'
MODELS = (DEFAULT_MODEL, 'gemini-3.8-flash', 'gemini-4-argon')


def validate_model(value):
    if value not in MODELS:
        raise ValueError('未対応のGemini APIモデルです')
    return value
