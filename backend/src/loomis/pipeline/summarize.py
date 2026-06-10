"""Prompt construction + Markdown rendering for diary and meeting summaries.

Pure helpers (no DB, no I/O): build the speaker-labelled transcript text, the
versioned prompts handed to the LLM, and the human-readable Markdown written to
``diary/<date>.md`` / ``meetings/<id>.md`` (05 §1, feature 05 §3–5).
"""

from __future__ import annotations

from ..core.models import DiaryDoc, MeetingDoc, Segment

PROMPT_VERSION = "v2"  # v2: prompts also ask for speaker_names (FR-5.8)

# Shared clause asking the model to name unnamed speakers from conversational
# evidence. Labels must round-trip exactly ("Speaker N") so the pipeline can map
# guesses back to speaker rows; named speakers already appear under their real
# name, so the model naturally skips them.
_SPEAKER_NAMES_CLAUSE = (
    'speaker_names (list of {"speaker", "name"}: for any speaker labelled '
    '"Speaker N" whose real name is evident from the conversation — addressed '
    "by name, self-introduction — give the label exactly as written and the "
    "inferred name; omit speakers whose name is not evident)"
)


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
        f"mentioned_people (list), {_SPEAKER_NAMES_CLAUSE}.\n\n"
        f"Transcripts (chronological):\n{text}"
    )


def build_meeting_prompt(text: str, language: str) -> str:
    return (
        f"{_lang_clause(language)}"
        "Summarize the following meeting transcript. Produce JSON with keys: title, "
        "attendees (list of names), summary_markdown, decisions (list), action_items "
        f"(list of {{owner, task, due}}), topics (list), {_SPEAKER_NAMES_CLAUSE}.\n\n"
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
