# 05 · Feature — Summarization & Organization

| | |
|---|---|
| **Document** | Feature Spec — Summarization & Organization (Diary vs Meeting) |
| **Doc ID** | LM-F05 |
| **Version** | 0.2 (Draft) |
| **Last updated** | 2026-06-10 |
| **Related** | [04 Speakers](04-speaker-diarization-and-identification.md), [05 Data Model](../05-data-model-and-storage.md), [ADR-0005](../adr/0005-llm-provider-abstraction.md) |
| **Traces** | FR-6.1 … FR-6.9 |

---

## 1. Overview

Turn transcripts into human-readable output in two modes:

- **Diary mode** — a first-person daily lifelog aggregating the day's scattered,
  mostly-solo clips.
- **Meeting mode** — a standalone record of a genuine multi-person discussion,
  with decisions and action items.

Every diary day links to any meetings that happened that day.

## 2. Classification (FR-6.1)

Two-stage: cheap heuristics first, LLM confirmation when unsure.

**Heuristic signals:** distinct speaker count; owner-dominance fraction;
turn-taking density & overlap; duration/structure. Produces a label + confidence.

**LLM confirmation** (when confidence is low): pass a transcript excerpt, get
structured `{ "type": "diary|meeting", "confidence": 0..1, "reason": "..." }`.

> Tie-break bias toward **diary** (`[summaries].ambiguous_bias`) — a stray meeting
> filed into the diary is less harmful than fragmenting the lifelog.

## 3. Diary mode (FR-6.2, FR-6.5, FR-6.8)

Scope: all *diary-type* recordings for one local calendar day.

1. Order the day's clips chronologically; concatenate speaker-labeled transcripts.
2. LLM (diary template) writes a **first-person** entry → structured output:

```json
{
  "title": "string",
  "narrative_markdown": "first-person prose for the day",
  "topics": ["..."],
  "mood": "string",
  "todos": ["..."],
  "decisions": ["..."],
  "mentioned_people": ["name", "..."],
  "speaker_names": [{ "speaker": "Speaker 3", "name": "小明" }]
}
```

3. Render `diary/<YYYY-MM-DD>.md` + metadata sidecar; record sources in
   `diary_recordings`; append "Meetings today" links.
4. **Idempotent re-summary:** late clips re-trigger aggregation; prior version
   retained/diffable.

**Day-settled debounce** (`[summaries].diary_day_settle_minutes`): summarize once
a day looks complete (quiet timer after the last import), re-open on stragglers.

## 4. Meeting mode (FR-6.3, FR-6.4, FR-6.6)

Scope: a *meeting-type* recording, or a contiguous group forming one discussion
(`meeting_recordings`).

```json
{
  "title": "string",
  "attendees": ["mapped speaker names", "..."],
  "summary_markdown": "string",
  "decisions": ["..."],
  "action_items": [{ "owner": "name", "task": "string", "due": "optional" }],
  "topics": ["..."],
  "speaker_names": [{ "speaker": "Speaker 3", "name": "小明" }]
}
```

Attendees map to known `speakers` via identity
([10](04-speaker-diarization-and-identification.md)); unknowns appear as
provisional identities. Render `meetings/<meeting_id>.md`; create the back-link
into that day's diary (`diary_meeting_links`).

## 5. Prompting & structured output (FR-6.7)

### 5.1 Speaker name suggestions (FR-5.8)

Both modes ask the model for one extra key, `speaker_names`: for any speaker
labelled `Speaker N` in the transcript whose real name is evident from the
conversation (addressed by name, self-introduction), return
`{ "speaker": "Speaker N", "name": "..." }`. The pipeline maps each entry back
to the speaker row and stores it as `suggested_name` **only if** that identity
is still unnamed — display names are always user-confirmed
([feature 04 §6.1](04-speaker-diarization-and-identification.md#61-llm-name-suggestions-fr-58)).
Speakers already named appear in the transcript under their real name, so the
model naturally skips them.

- **Schema-validated** JSON (pydantic), retried on mismatch → deterministic,
  storable output.
- **Versioned templates**; model id + prompt version stored with each summary for
  reproducibility.
- **Language** follows the transcript's dominant language by default
  (`[summaries]`/`[llm].summary_language`) — a Mandarin day yields a Mandarin
  diary.
- **Context limits:** long days/meetings chunked + hierarchically summarized
  (map-reduce) to fit local model context windows.

## 6. Provider (FR-6.9)

Runs through the LLM adapter — **Ollama by default**, optional cloud
(OpenAI/Anthropic/Gemini) for higher quality, accepting that transcripts then
leave the device. See [ADR-0005](../adr/0005-llm-provider-abstraction.md) and the
privacy boundary
([04 §10](../04-system-architecture.md#10-privacy--trust-boundary)).

## 7. Open questions

- Exact heuristic thresholds/weights (calibrate on real recordings).
- Contiguous-clip grouping rule for meetings (time gap? same speakers?).
- Weekly/monthly roll-up summaries — candidate for the
  [roadmap](../08-roadmap-and-milestones.md).
