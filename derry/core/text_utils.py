import re

_CODE_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_MD_LINKS = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF]"
)


def text_to_speech_safe(text: str, max_chars: int = 400) -> str:
    """Convert assistant/Markdown output into clean, speakable prose."""
    t = _CODE_FENCE.sub(" (code omitted) ", text)
    t = _INLINE_CODE.sub(r"\1", t)
    t = _MD_LINKS.sub(r"\1", t)
    t = _URL.sub(" link ", t)
    t = _EMOJI.sub("", t)
    t = re.sub(r"[#*_>~`]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > max_chars:
        t = t[:max_chars].rsplit(" ", 1)[0] + "…"
    return t
