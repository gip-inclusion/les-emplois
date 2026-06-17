import re


def normalize_phone_number(phone_number: str) -> str | None:
    if not phone_number:
        return None
    normalized = phone_number.strip()
    if normalized.startswith("+33"):
        rest = re.sub(r"\D", "", normalized[3:])
        if rest:
            normalized = f"0{rest}"
    else:
        normalized = re.sub(r"\D", "", normalized)
        if normalized.startswith("0033"):
            normalized = f"0{normalized[4:]}"
    if len(normalized) == 10 and normalized.startswith("0"):
        return normalized
    return None
