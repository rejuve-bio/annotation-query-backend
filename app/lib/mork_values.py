"""Property values in the BioCypher MeTTa / ACT representation."""

import re


def normalize_mork_value(value):
    """Mirror MeTTaWriter.check_property with the default include_curie=False.

    The ACT parser stores at most 63 bytes per symbol. Case is significant;
    identifiers have their own preprocessing and must not use this function.
    """
    if isinstance(value, str):
        text = value.strip()
        is_url = text.startswith(("http://", "https://", "ftp://", "ftps://")) or (
            text.startswith("www.") and "." in text[4:]
        )
        if not is_url:
            if ":" in text:
                text = text.split(":", 1)[1].strip()
            text = text.replace(" ", "_").strip("_").replace("->", "-")
            text = re.sub(r"[^a-zA-Z0-9_:\.-]", "", text)
    elif isinstance(value, (bool, int, float)):
        text = str(value)
    else:
        raise ValueError(f"Invalid MORK property value: {value!r}")

    # URLs bypass the writer's punctuation cleanup, but still need to be a
    # single literal symbol rather than executable MeTTa syntax.
    if not text or text.startswith(("$", ";")) or any(
        char.isspace() or char in '()"\\' for char in text
    ):
        raise ValueError(f"Invalid MORK property value: {value!r}")
    try:
        return text.encode("utf-8")[:63].decode("utf-8")
    except UnicodeDecodeError:
        # Dropping a partial character would query different bytes from ACT.
        raise ValueError("Invalid MORK property value: truncation splits a UTF-8 character") from None
