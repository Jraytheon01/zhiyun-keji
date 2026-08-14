"""Helpers for the production ``user_meeting_content`` transcript layout."""


def preferred_transcript_type(rows: list[dict]) -> str | None:
    """Prefer normalized rows (type=1), then ordinary rows (type=0), then NULL."""
    available = {str(row["type"]) for row in rows if row.get("type") is not None}
    if "1" in available:
        return "1"
    if "0" in available:
        return "0"
    return None


def format_transcript_rows(rows: list[dict]) -> str:
    """Render ordered speaker rows into the text format consumed by chunking/LLM."""
    selected_type = preferred_transcript_type(rows)
    selected = [
        row for row in rows
        if (str(row.get("type")) if row.get("type") is not None else None) == selected_type
    ]
    lines = []
    for row in selected:
        content = (row.get("content") or "").strip()
        if not content:
            continue
        speaker = (row.get("speaker") or "").strip()
        code = (row.get("code") or "").strip()
        if not speaker:
            if code.startswith("说话人"):
                speaker = code
            elif code:
                speaker = f"说话人{code}"
            else:
                speaker = "未知说话人"
        lines.append(f"{speaker}：{content}")
    return "\n".join(lines)
