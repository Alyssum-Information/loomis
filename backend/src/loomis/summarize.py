"""Prompt construction + Markdown rendering for diary and meeting summaries.

Pure helpers (no DB, no I/O): build the speaker-labelled transcript text, the
versioned prompts handed to the LLM, and the human-readable Markdown written to
``diary/<date>.md`` / ``meetings/<id>.md`` (05 §1, feature 05 §3–5).
"""

from __future__ import annotations

from .models import DiaryDoc, MeetingDoc, Segment

PROMPT_VERSION = "v1"


def _lang_clause(language: str) -> str:
    if language in ("", "auto"):
        return "Write in the transcript's dominant language. "
    return f"Write in {language}. "


def transcript_text(segments: list[Segment], speaker_names: dict[int, str]) -> str:
    """Render segments as ``Name: text`` lines for the prompt context."""
    lines: list[str] = []
    for seg in segments:
        if not seg.text:
            continue
        if seg.speaker_id is not None:
            who = speaker_names.get(seg.speaker_id, f"Speaker {seg.speaker_id}")
        else:
            who = seg.diarization_label or "Unknown"
        lines.append(f"{who}: {seg.text}")
    return "\n".join(lines)


def build_classify_prompt(text: str) -> str:
    return (
        "Classify the following transcript as a personal 'diary' (mostly one person, "
        "everyday self-talk) or a 'meeting' (genuine multi-person discussion). "
        'Respond as JSON: {"type":"diary|meeting","confidence":0..1,"reason":"..."}.\n\n'
        f"Transcript:\n{text}"
    )


def build_diary_prompt(text: str, language: str) -> str:
    return (
        f"{_lang_clause(language)}"
        "You are writing the author's first-person daily diary from the day's audio "
        "transcripts below. Produce JSON with keys: title, narrative_markdown "
        "(first-person prose), topics (list), mood, todos (list), decisions (list), "
        "mentioned_people (list).\n\n"
        f"Transcripts (chronological):\n{text}"
    )


def build_meeting_prompt(text: str, language: str) -> str:
    return (
        f"{_lang_clause(language)}"
        "Summarize the following meeting transcript. Produce JSON with keys: title, "
        "attendees (list of names), summary_markdown, decisions (list), action_items "
        "(list of {owner, task, due}), topics (list).\n\n"
        f"Transcript:\n{text}"
    )


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "_none_"


def render_diary_markdown(date: str, doc: DiaryDoc, meeting_links: list[tuple[str, str]]) -> str:
    title = doc.title or date
    parts = [
        f"# {title}",
        f"_{date}_",
        "",
        doc.narrative_markdown or "_(no entry)_",
        "",
        "## Topics",
        _bullets(doc.topics),
        "",
        "## To-dos",
        _bullets(doc.todos),
        "",
        "## Decisions",
        _bullets(doc.decisions),
    ]
    if doc.mood:
        parts += ["", f"**Mood:** {doc.mood}"]
    if meeting_links:
        parts += ["", "## Meetings today"]
        parts += [f"- [{t}]({p})" for t, p in meeting_links]
    return "\n".join(parts) + "\n"


def render_meeting_markdown(doc: MeetingDoc) -> str:
    parts = [
        f"# {doc.title or 'Meeting'}",
        "",
        f"**Attendees:** {', '.join(doc.attendees) if doc.attendees else '_unknown_'}",
        "",
        "## Summary",
        doc.summary_markdown or "_(no summary)_",
        "",
        "## Decisions",
        _bullets(doc.decisions),
        "",
        "## Action items",
    ]
    if doc.action_items:
        for ai in doc.action_items:
            due = f" (due {ai.due})" if ai.due else ""
            owner = ai.owner or "unassigned"
            parts.append(f"- **{owner}**: {ai.task}{due}")
    else:
        parts.append("_none_")
    parts += ["", "## Topics", _bullets(doc.topics)]
    return "\n".join(parts) + "\n"
