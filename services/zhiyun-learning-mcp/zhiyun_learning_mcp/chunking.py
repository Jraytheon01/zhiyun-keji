# meeting_assistant/chunking.py
import re

def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 3)

def chunk_transcript(text: str, target_tokens: int = 400, overlap: int = 50) -> list[dict]:
    lines = [l for l in text.splitlines() if l.strip()]
    chunks, buf, cur_speaker, ordinal = [], [], None, 0
    for line in lines:
        if "：" in line:
            head, body = line.split("：", 1)
            cur_speaker = head.strip()
        else:
            body = line
        buf.append(line)
        if _approx_tokens("\n".join(buf)) >= target_tokens:
            text_block = "\n".join(buf)
            chunks.append({"kind":"transcript","ordinal":ordinal,"text":text_block,"speaker":cur_speaker})
            ordinal += 1
            keep = []
            acc = 0
            for l in reversed(buf):
                acc += _approx_tokens(l)
                if acc > overlap: break
                keep.append(l)
            buf = list(reversed(keep))
    if buf:
        chunks.append({"kind":"transcript","ordinal":ordinal,"text":"\n".join(buf),"speaker":cur_speaker})
    return chunks

def chunk_summary(md: str) -> list[dict]:
    chunks, cur_section, cur_buf, ordinal = [], None, [], 0
    def flush():
        nonlocal ordinal
        if cur_buf and cur_section:
            chunks.append({"kind":"summary","ordinal":ordinal,"text":"\n".join(cur_buf),"section":cur_section})
            ordinal += 1
    for line in md.splitlines():
        if line.startswith("## "):
            flush()
            cur_section = line[3:].strip(); cur_buf = [line]
        elif match := re.match(r"^【([^】]+)】", line.strip()):
            flush()
            cur_section = match.group(1).strip(); cur_buf = [line]
        else:
            if cur_section: cur_buf.append(line)
    flush()
    if not chunks and md.strip():
        chunks.append({"kind": "summary", "ordinal": 0,
                       "text": md.strip(), "section": "会议摘要"})
    return chunks
