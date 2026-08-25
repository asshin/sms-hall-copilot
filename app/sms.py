from __future__ import annotations

# GSM 03.38 basic character set (approximate). Anything else → UCS-2 / 70 chars.
_GSM = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)


def encoding_for(text: str) -> str:
    return "gsm7" if text and set(text) <= _GSM else "ucs2"


def unit_size(encoding: str, concatenated: bool) -> int:
    if encoding == "gsm7":
        return 153 if concatenated else 160
    return 67 if concatenated else 70


def split_sms(text: str) -> list[str]:
    enc = encoding_for(text)
    single = unit_size(enc, False)
    if len(text) <= single:
        return [text]
    size = unit_size(enc, True)
    return [text[i : i + size] for i in range(0, len(text), size)]


def compose_meta(text: str) -> dict[str, int | str]:
    parts = split_sms(text)
    return {"encoding": encoding_for(text), "parts": len(parts), "chars": len(text)}
