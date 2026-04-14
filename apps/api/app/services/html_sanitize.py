import re

import bleach

_RICH_TAGS = ("strong", "b", "em", "i", "br", "code")
_RICH_TAGS_LIST = list(_RICH_TAGS)


def _unwrap_markdown_bold_to_plain(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    out = text
    while True:
        nxt = re.sub(r"\*\*([^*]+)\*\*", r"\1", out)
        if nxt == out:
            return out
        out = nxt


def normalize_skill_chip_label(label: str) -> str:
    x = (label or "").strip()
    x = _unwrap_markdown_bold_to_plain(x)
    for _ in range(5):
        y = x.strip()
        if len(y) >= 2 and y[0] == y[-1] and y[0] in "\"'":
            x = y[1:-1].strip()
            continue
        if len(y) >= 2 and y.startswith("`") and y.endswith("`"):
            x = y[1:-1].strip()
            continue
        break
    return sanitize_plain_text(_unwrap_markdown_bold_to_plain(x).strip())


def markdown_bold_to_html(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    out = text
    while True:
        nxt = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
        if nxt == out:
            return out
        out = nxt


def sanitize_rich_html(text: str) -> str:
    step = markdown_bold_to_html((text or "").strip())
    return bleach.clean(
        step,
        tags=_RICH_TAGS_LIST,
        attributes={},
        strip=True,
    )


def sanitize_plain_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    return bleach.clean(text, tags=[], strip=True).strip()


def _safe_http_url(url: str) -> str:
    u = sanitize_plain_text(url)
    low = u.lower()
    if low.startswith("javascript:") or low.startswith("data:") or low.startswith("vbscript:"):
        return ""
    return u


def sanitize_resume_for_display(data: dict) -> None:
    if not isinstance(data, dict):
        return
    for key in ("fullName",):
        v = data.get(key)
        if isinstance(v, str):
            data[key] = sanitize_plain_text(v)
    for key in ("headline", "summary"):
        v = data.get(key)
        if isinstance(v, str):
            data[key] = sanitize_rich_html(v)
    exp = data.get("experience")
    if isinstance(exp, list):
        for item in exp:
            if not isinstance(item, dict):
                continue
            for k in ("company", "title", "location", "start", "end"):
                v = item.get(k)
                if isinstance(v, str):
                    item[k] = sanitize_plain_text(v)
            hs = item.get("highlights")
            if isinstance(hs, list):
                rich_hs: list[str] = []
                for h in hs:
                    if not isinstance(h, str):
                        continue
                    x = sanitize_rich_html(h)
                    if x:
                        rich_hs.append(x)
                item["highlights"] = rich_hs
    projs = data.get("projects")
    if isinstance(projs, list):
        for p in projs:
            if not isinstance(p, dict):
                continue
            if isinstance(p.get("name"), str):
                nm = sanitize_rich_html(p["name"])
                p["name"] = nm if nm else "Project"
            if isinstance(p.get("description"), str):
                p["description"] = sanitize_rich_html(p["description"])
    edu = data.get("education")
    if isinstance(edu, list):
        for item in edu:
            if not isinstance(item, dict):
                continue
            for k in ("institution", "degree", "end"):
                v = item.get(k)
                if isinstance(v, str):
                    item[k] = sanitize_plain_text(v)
            det = item.get("details")
            if isinstance(det, str):
                dval = sanitize_rich_html(det)
                item["details"] = dval if dval else None
    skills = data.get("skills")
    if isinstance(skills, list):
        chips: list[str] = []
        for s in skills:
            if not isinstance(s, str):
                continue
            c = normalize_skill_chip_label(s)
            if c:
                chips.append(c)
        data["skills"] = chips
    links = data.get("links")
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict):
                continue
            if isinstance(link.get("label"), str):
                link["label"] = sanitize_plain_text(link["label"])
            if isinstance(link.get("url"), str):
                link["url"] = _safe_http_url(link["url"])
    for key in ("location", "phone", "locale"):
        v = data.get(key)
        if isinstance(v, str):
            data[key] = sanitize_plain_text(v)
