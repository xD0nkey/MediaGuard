import re
import unicodedata

from .attachments import InspectionResult, Status


URL = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
WHITESPACE = re.compile(r"\s+")


def normalize(value: str) -> str:
    return unicodedata.normalize("NFC", WHITESPACE.sub(" ", value).strip()).casefold()


def _word(char: str) -> bool:
    return char == "_" or char.isalnum() or unicodedata.category(char).startswith("M")


def _contains(text: str, phrase: str) -> bool:
    start = 0
    while (index := text.find(phrase, start)) != -1:
        end = index + len(phrase)
        left = not _word(phrase[0]) or index == 0 or not _word(text[index - 1])
        right = not _word(phrase[-1]) or end == len(text) or not _word(text[end])
        if left and right:
            return True
        start = index + 1
    return False


def _surfaces(embeds):
    if len(embeds) > 10:
        return None
    surfaces = []
    total = 0
    for embed in embeds:
        fields = getattr(embed, "fields", ())
        if len(fields) > 25:
            return None
        candidates = [(getattr(embed, "title", None), 256),
                      (getattr(embed, "description", None), 4096)]
        candidates.extend((getattr(field, "value", None), 1024) for field in fields)
        for value, limit in candidates:
            if value is None:
                continue
            if not isinstance(value, str) or len(value) > limit:
                return None
            total += len(value)
            if total > 6000:
                return None
            surfaces.extend(normalize(part) for part in URL.split(value))
    return surfaces, total


def match_embeds(ordinary, forwarded, rules):
    if len(ordinary) + len(forwarded) > 10:
        return None
    ordinary_result = _surfaces(ordinary)
    forwarded_result = _surfaces(forwarded)
    if ordinary_result is None or forwarded_result is None:
        return None
    ordinary_text, ordinary_length = ordinary_result
    forwarded_text, forwarded_length = forwarded_result
    if ordinary_length + forwarded_length > 6000:
        return None
    for rule in rules:
        for source, surfaces in (("embed", ordinary_text), ("forwarded_embed", forwarded_text)):
            if any(_contains(text, rule["normalized_phrase"]) for text in surfaces):
                return InspectionResult(Status.MATCH, "blocked_embed_phrase", source,
                                        rule_id=rule["rule_id"], rule_name=rule["name"])
    return None
