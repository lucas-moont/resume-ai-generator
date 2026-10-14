"""Opt-in evaluation of the resume pipeline against real job descriptions.

This calls a REAL LLM (through whatever provider the model id routes to, e.g. the local Claude
CLI), so it is never collected by pytest and refuses to run unless ``RUN_LLM_EVAL=1``.

It answers questions like "did this prompt change make resumes leaner?" or "does a pruned profile
beat a rich one?" by running the same postings through the real chain (Analysis -> approve every
item -> generation with the quality pass) and measuring the resumes that come out.

Three subcommands:

  prepare  Export postings and the active profile from a local app.db (opened read-only) into a
           folder you keep out of git, e.g. ``data/eval/``.
  run      Run one ARM: every posting through the pipeline of whatever ``app`` package is on
           ``sys.path``. To evaluate an older commit, check it out in a ``git worktree`` and run
           this same file with ``PYTHONPATH=<worktree>/apps/api``. Point ``DATA_DIR`` and
           ``DATABASE_URL`` at a scratch folder so the run never opens your real app.db.
  report   Compare arms with the CURRENT checkout's quality checks, so every arm is measured by
           the same ruler, and write a Markdown report.

Example (PowerShell-free, from ``apps/api``)::

    RUN_LLM_EVAL=1 python scripts/eval_generation.py prepare --db ../../data/app.db \
        --out ../../data/eval --sessions 150,114,98
    RUN_LLM_EVAL=1 DATA_DIR=/tmp/eval-data DATABASE_URL=sqlite:////tmp/eval-data/app.db \
        python scripts/eval_generation.py run --profile ../../data/eval/profile_rich.json \
        --jds ../../data/eval/jds.json --out ../../data/eval/arm_b.json --model claude-opus-5-5
    RUN_LLM_EVAL=1 python scripts/eval_generation.py report \
        --arm "A=../../data/eval/arm_a.json" --arm "B=../../data/eval/arm_b.json" \
        --jds ../../data/eval/jds.json --out ../../data/eval/report.md
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import os
import re
import sqlite3
import statistics
import sys
import time
from pathlib import Path
from typing import Any

# Families decide one metric: AI vocabulary only counts as noise on a posting that is not about AI.
FAMILIES = ("frontend", "fullstack", "ai", "low-match", "off-target")

_AI_TERMS = re.compile(
    r"\b(?:langgraph|langchain|llms?|rag|llmops|openai|agentic|agents?|agentes?|"
    r"generative ai|ia generativa|genai|prompt engineering)\b",
    re.IGNORECASE,
)


# Per-posting LLM call counter. asyncio.gather runs each posting in its own Task, and a Task gets a
# copy of the context, so a counter set inside one posting is invisible to the others even while
# they run concurrently through the same wrapped ``chat_json``.
_CALLS: contextvars.ContextVar[list[int] | None] = contextvars.ContextVar("eval_calls", default=None)


def _install_call_counter() -> None:
    from app.services import llm_client

    real = llm_client.chat_json
    if getattr(real, "_eval_counted", False):
        return

    async def counted(system: str, user: str, model: str | None = None) -> str:
        box = _CALLS.get()
        if box is not None:
            box[0] += 1
        return await real(system, user, model=model)

    counted._eval_counted = True  # type: ignore[attr-defined]
    llm_client.chat_json = counted


def _require_opt_in() -> None:
    if os.getenv("RUN_LLM_EVAL") != "1":
        sys.exit("Refusing to run: this script calls a real LLM. Set RUN_LLM_EVAL=1 to proceed.")


# --- prepare ------------------------------------------------------------------------------------


def _parse_session_spec(spec: str) -> list[tuple[int, str]]:
    """``150:frontend,98:fullstack`` -> [(150, "frontend"), (98, "fullstack")]."""
    out: list[tuple[int, str]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        sid, _, family = part.partition(":")
        family = family or "fullstack"
        if family not in FAMILIES:
            sys.exit(f"Unknown family {family!r}; use one of {', '.join(FAMILIES)}")
        out.append((int(sid), family))
    return out


def cmd_prepare(args: argparse.Namespace) -> None:
    db = Path(args.db).resolve()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        jds = []
        for sid, family in _parse_session_spec(args.sessions):
            row = conn.execute(
                "select title, job_description from chat_sessions where id = ?", (sid,)
            ).fetchone()
            if not row or not (row[1] or "").strip():
                sys.exit(f"Session {sid} has no job description.")
            if row[1].lstrip().upper().startswith("TARGET BRIEF"):
                sys.exit(f"Session {sid} is a baseline brief, not a posting.")
            jds.append({"session": sid, "family": family, "title": row[0] or "", "jd": row[1]})
        version = conn.execute(
            "select id, data from profile_versions order by id desc limit 1"
        ).fetchone()
    finally:
        conn.close()
    profile = json.loads(version[1])
    profile["githubUsername"] = None  # no GitHub fetches during an eval
    (out / "jds.json").write_text(json.dumps(jds, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "profile_rich.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"Wrote {len(jds)} postings and profile_versions.id={version[0]} to {out}")


# --- run ----------------------------------------------------------------------------------------


async def _run_one(item: dict, *, resolved_profile: Any, model: str, sem: asyncio.Semaphore) -> dict:
    from app.domain.locale import resolve_locale
    from app.services import llm_client
    from app.services.chat_service import build_analysis_prompt
    from app.services.generation_service import generate_resume_events
    from app.services.llm.proposal_json_parser import parse_proposal_json

    async with sem:
        started = time.monotonic()
        box = [0]
        _CALLS.set(box)
        record: dict[str, Any] = {"session": item["session"], "family": item["family"], "title": item["title"]}
        try:
            profile = resolved_profile.profile
            locale = resolve_locale(None, item["jd"], profile.locale)
            system, user = build_analysis_prompt(profile=profile, job_description=item["jd"], locale=locale)
            raw = await llm_client.chat_json(system, user, model=model)
            parsed = parse_proposal_json(raw)
            items = parsed.items if parsed else None
            record["proposal"] = [i.model_dump() for i in items] if items else None
            resume = None
            async for event, data in generate_resume_events(
                resolved_profile=resolved_profile,
                job_description=item["jd"],
                model=model,
                locale=locale,
                backend_label="claude",
                agreed_improvements=items,
            ):
                if event == "done":
                    resume = data["resume"]
            record["resume"] = resume.model_dump() if resume is not None else None
        except Exception as exc:  # recorded, never fatal: one bad posting must not sink the arm
            record["error"] = f"{type(exc).__name__}: {exc}"
        record["calls"] = box[0]
        record["seconds"] = round(time.monotonic() - started, 1)
        print(f"[{item['session']}] {record.get('error') or 'ok'} calls={box[0]} {record['seconds']}s", flush=True)
        return record


async def _run_arm(args: argparse.Namespace) -> list[dict]:
    from app.domain.schemas import ProfileMaster
    from app.services.profile_resolution import ResolvedProfile

    profile = ProfileMaster.model_validate_json(Path(args.profile).read_text(encoding="utf-8"))
    resolved = ResolvedProfile(
        profile=profile,
        profile_version_id=None,
        source="disk",
        pdf_text="",
        pdf_path=None,
        needs_extraction=False,
    )
    jds = json.loads(Path(args.jds).read_text(encoding="utf-8"))
    _install_call_counter()
    sem = asyncio.Semaphore(args.concurrency)
    return await asyncio.gather(*(_run_one(i, resolved_profile=resolved, model=args.model, sem=sem) for i in jds))


def cmd_run(args: argparse.Namespace) -> None:
    import app

    records = asyncio.run(_run_arm(args))
    payload = {"model": args.model, "app_path": str(Path(app.__file__).parent), "records": records}
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote {len(records)} records to {args.out}")


# --- report -------------------------------------------------------------------------------------


def _metrics(resume: dict, jd: str, family: str) -> dict:
    from app.domain.keywords import extract_jd_keywords
    from app.domain.quality import (
        headline_segments,
        quality_issues,
        resume_keyword_blob,
        unevidenced_skills,
    )
    from app.domain.schemas import ResumeDocument

    doc = ResumeDocument.model_validate(resume)
    plain = lambda s: re.sub(r"<[^>]+>", "", s or "")  # noqa: E731
    top = extract_jd_keywords(jd)[:12]
    blob = resume_keyword_blob(doc)
    prose = " ".join(
        [plain(doc.headline), plain(doc.summary)]
        + [plain(h) for e in doc.experience for h in e.highlights]
        + [plain(p.description) for p in doc.projects]
        + list(doc.skills)
    )
    return {
        "skills": len(doc.skills),
        "unevidenced": len(unevidenced_skills(doc)),
        "bullets": [len(e.highlights) for e in doc.experience],
        "bullets_total": sum(len(e.highlights) for e in doc.experience),
        "projects": len(doc.projects),
        "headline_segments": headline_segments(doc),
        "summary_words": len(plain(doc.summary).split()),
        "issues": len(quality_issues(doc, jd)),
        "coverage": round(sum(1 for k in top if k in blob) / len(top), 2) if top else None,
        "ai_terms": None if family == "ai" else len(_AI_TERMS.findall(prose)),
        "headline": plain(doc.headline),
    }


def _mean(values: list) -> str:
    vals = [v for v in values if isinstance(v, (int, float))]
    return f"{statistics.mean(vals):.1f}" if vals else "-"


def cmd_report(args: argparse.Namespace) -> None:
    # The report always measures with THIS checkout's quality checks, whatever code each arm ran.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    jds = {j["session"]: j for j in json.loads(Path(args.jds).read_text(encoding="utf-8"))}
    arms: dict[str, dict] = {}
    for spec in args.arm:
        name, _, path = spec.partition("=")
        arms[name] = json.loads(Path(path).read_text(encoding="utf-8"))

    rows: dict[str, list[dict]] = {}
    for name, payload in arms.items():
        out = []
        for rec in payload["records"]:
            jd = jds[rec["session"]]
            m = {"session": rec["session"], "family": rec["family"], "calls": rec.get("calls"), "error": rec.get("error")}
            if rec.get("resume"):
                m.update(_metrics(rec["resume"], jd["jd"], rec["family"]))
            out.append(m)
        rows[name] = out

    keys = [
        ("skills", "Skills"),
        ("unevidenced", "Skills sem evidência"),
        ("bullets_total", "Bullets (total)"),
        ("projects", "Projetos"),
        ("headline_segments", "Segmentos do headline"),
        ("summary_words", "Palavras do resumo"),
        ("issues", "Quality issues restantes"),
        ("coverage", "Cobertura top-12 da vaga"),
        ("ai_terms", "Termos de IA (vagas não-IA)"),
        ("calls", "Chamadas de LLM"),
    ]
    lines = ["# Avaliação do pipeline de currículo", ""]
    for name, payload in arms.items():
        errors = sum(1 for r in rows[name] if r.get("error"))
        lines.append(f"- **{name}**: `{payload['app_path']}`, modelo `{payload['model']}`, erros: {errors}")
    lines += ["", "## Médias por braço", "", "| Métrica | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    for key, label in keys:
        lines.append(f"| {label} | " + " | ".join(_mean([r.get(key) for r in rows[n]]) for n in arms) + " |")

    lines += ["", "## Por vaga", ""]
    for sid, jd in jds.items():
        lines.append(f"### {jd['title']} (sessão {sid}, {jd['family']})")
        lines.append("")
        lines.append("| Braço | Skills | Sem evid. | Bullets | Proj. | Seg. | Resumo | Issues | Cobertura | IA | Headline |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for name in arms:
            r = next((x for x in rows[name] if x["session"] == sid), None)
            if not r or r.get("error") or "skills" not in r:
                lines.append(f"| {name} | erro: {(r or {}).get('error', 'sem resultado')} |||||||||| ")
                continue
            lines.append(
                f"| {name} | {r['skills']} | {r['unevidenced']} | {r['bullets']} | {r['projects']} | "
                f"{r['headline_segments']} | {r['summary_words']} | {r['issues']} | {r['coverage']} | "
                f"{'-' if r['ai_terms'] is None else r['ai_terms']} | {r['headline']} |"
            )
        lines.append("")

    for sid in args.showcase or []:
        sid = int(sid)
        lines += [f"## Lado a lado: {jds[sid]['title']}", ""]
        for name, payload in arms.items():
            rec = next((r for r in payload["records"] if r["session"] == sid), None)
            resume = (rec or {}).get("resume")
            lines.append(f"### {name}")
            if not resume:
                lines += ["(sem currículo)", ""]
                continue
            lines.append(f"**{re.sub(r'<[^>]+>', '', resume['headline'])}**")
            lines.append("")
            lines.append(re.sub(r"<[^>]+>", "", resume["summary"]))
            lines.append("")
            lines.append("Skills: " + ", ".join(resume["skills"]))
            lines.append("")
            for role in resume["experience"]:
                lines.append(f"- *{role['title']}*, {role['company']}")
                for h in role["highlights"]:
                    lines.append(f"  - {re.sub(r'<[^>]+>', '', h)}")
            lines.append("")
            lines.append("Projetos: " + ", ".join(p["name"] for p in resume["projects"]))
            lines.append("")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")


def main() -> None:
    _require_opt_in()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--db", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--sessions", required=True, help="e.g. 150:frontend,98:fullstack,106:ai")
    p.set_defaults(func=cmd_prepare)

    r = sub.add_parser("run")
    r.add_argument("--profile", required=True)
    r.add_argument("--jds", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--concurrency", type=int, default=1)
    r.set_defaults(func=cmd_run)

    rep = sub.add_parser("report")
    rep.add_argument("--arm", action="append", required=True, help="NAME=path/to/arm.json")
    rep.add_argument("--jds", required=True)
    rep.add_argument("--out", required=True)
    rep.add_argument("--showcase", nargs="*", help="session ids to print side by side")
    rep.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
