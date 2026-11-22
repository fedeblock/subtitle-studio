import re


def fmt(t, vtt=False):
    ms = max(0, round(float(t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02}{'.' if vtt else ','}{ms:03}"


def parse_srt(s):
    result = []
    for chunk in re.split(r"\n\s*\n", s.strip().replace("\r\n", "\n")):
        lines = chunk.strip().splitlines()
        if not lines:
            continue
        t = next((j for j, line in enumerate(lines) if "-->" in line), None)
        if t is None:
            continue
        parts = lines[t].split("-->")

        def seconds(v):
            m = re.match(r"\s*(\d+):(\d+):(\d+)[,.](\d+)", v)
            if not m:
                raise ValueError("Bad timestamp: " + v)
            h, mi, sec, millis = map(int, m.groups())
            return h * 3600 + mi * 60 + sec + millis / 1000

        start, end = seconds(parts[0]), seconds(parts[1])
        text = "\n".join(lines[t + 1 :]).strip()
        if text and end > start:
            result.append({"start": start, "end": end, "original": text})
    return result


def export(cues, language, vtt):
    chunks = []
    for i, c in enumerate(cues, 1):
        body = (
            "\n".join(x for x in [c.original or "", c.translated or ""] if x.strip())
            if language == "bilingual"
            else (c.original if language == "original" else c.translated)
        ) or ""
        if not body.strip():
            continue
        chunks.append(f"{i}\n{fmt(c.start, vtt)} --> {fmt(c.end, vtt)}\n{body}")
    return ("WEBVTT\n\n" if vtt else "") + "\n\n".join(chunks) + "\n"
