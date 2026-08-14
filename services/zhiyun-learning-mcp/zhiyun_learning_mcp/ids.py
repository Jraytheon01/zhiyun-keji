# meeting_assistant/ids.py
"""Shared recording-id validation.

`recording_id` becomes a MinIO object-key prefix (f"{rid}/{name}") and a Milvus
filter-expr value, so it must be character-restricted — otherwise a value like
"../other" traverses into another recording's keys, and a value containing `"`
or `/` can break/inject the Milvus filter expression.
"""
import re

ID_RE = re.compile(r"^[A-Za-z0-9_\-一-龥]+$")


class InvalidRecordingId(ValueError):
    pass


def validate_recording_id(rid) -> str:
    """Raise InvalidRecordingId unless rid matches the safe charset."""
    if not isinstance(rid, str) or not ID_RE.match(rid):
        raise InvalidRecordingId(
            f"非法 recording_id: {rid!r}（仅允许字母/数字/下划线/连字符/中文）"
        )
    return rid
