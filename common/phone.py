import re


def normalize_phone(value: str) -> str:
    """Strict: international format only. Used for numbers we are asked to dial or text."""
    cleaned = re.sub(r"[\s\-().]", "", value)
    if not re.fullmatch(r"\+[1-9]\d{6,14}", cleaned):
        raise ValueError("Phone number must be in international format, e.g. +923001234567")
    return cleaned


def clean_remote(value: str) -> str:
    """Lenient: numbers reported by the phone may be local format or an SMS sender name."""
    v = value.strip()
    compact = re.sub(r"[\s\-().]", "", v)
    if re.fullmatch(r"\+?\d{3,20}", compact):
        return compact
    return v[:32]
