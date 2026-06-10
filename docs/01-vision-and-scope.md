# 01 · Vision & Scope

| | |
|---|---|
| **Document** | Vision & Scope |
| **Doc ID** | LM-01 |
| **Version** | 0.2 (Draft) |
| **Last updated** | 2026-06-10 |
| **Related** | [02 User Flows](02-user-flows.md), [03 SRS](03-requirements-specification.md), [04 Architecture](04-system-architecture.md), [09 Security & Privacy](09-security-and-privacy-model.md) |
| **Traces** | — (sets goals that all FRs derive from) |

---

## 1. Problem

People increasingly carry dedicated voice recorders or use phones to capture
audio — fleeting thoughts, voice memos, lectures, and meetings. That audio then
rots on the device: it is never offloaded, never transcribed, and never
revisited. Manually copying files, transcribing them, and writing up notes is
tedious enough that almost nobody does it.

Existing cloud "AI note-taker" products solve part of this, but they require
uploading private audio to a third party, charge per minute, and treat every
recording as a meeting — they have no concept of a *personal lifelog*.

## 2. Vision

**Loomis turns your voice recordings into an effortless, private lifelog.**
Recordings arrive from any **source** — a USB voice recorder, a phone whose
recordings sync into a watched folder, a wearable lifelogger's drop folder —
and everything else happens automatically and stays on your machine:

1. New recordings are backed up locally (and optionally to your own cloud).
2. They are transcribed with speaker labels.
3. The same voices are recognized across recordings, and speakers are
   **named from the conversation itself** (confirmed by you) so records read
   like they involve people, not `SPEAKER_03`.
4. Each day's scattered clips become a first-person **diary** entry.
5. Real multi-person **discussions** become standalone **meeting** records,
   linked from the diary for that day.

The product is opinionated about being **local-first**: your audio and
transcripts never leave your computer unless you explicitly turn on a cloud
feature.

## 3. Goals

- **Zero-friction capture-to-insight.** The happy path requires only plugging in
  the device — or nothing at all, when recordings sync into a watched folder.
- **Privacy by default.** Local storage, local STT, local LLM (Ollama). Any
  network egress is opt-in and clearly surfaced.
- **Durable & safe.** Never delete source audio before a verified backup. The
  pipeline is resumable and idempotent.
- **Lifelogger-grade browsing.** A timeline you actually want to scroll through,
  with search across everything you've ever said.
- **Extensible.** Pluggable STT, LLM, and cloud backends so the project can
  track a fast-moving ecosystem.

## 4. Non-goals (v1)

- ❌ Real-time / live transcription during recording. Loomis is batch, post-hoc.
- ❌ Mobile apps. The UI is a local web service usable from a phone browser on
  the same network, but there is no native mobile client.
- ❌ Multi-tenant / hosted SaaS. Loomis is single-user, self-hosted software.
- ❌ Editing or re-mixing audio (beyond optional format transcoding).
- ❌ Being a meeting bot that dials into live calls. Loomis ingests files.

## 5. Personas

**Primary — the self-quantifier / lifelogger** (e.g. the project author):
technically comfortable, owns a dedicated recorder and/or records on a phone,
captures both private voice memos and the occasional meeting, values privacy,
and wants a searchable personal archive without manual effort.

**Secondary:** students recording lectures; journalists/researchers doing
interviews; anyone who simply wants voice memos transcribed and organized.

## 6. Success criteria

- Plugging in a registered device and doing nothing else results in a complete,
  speaker-labeled, summarized library entry.
- No source file is ever lost: deletion only follows a checksum-verified copy.
- A day's worth of clips produces a coherent diary entry; a genuine multi-party
  discussion is split out as a meeting and linked.
- The entire default pipeline runs offline.

## 7. Guiding principles

1. **Local-first, cloud-optional.** Sensible defaults never touch the network.
2. **Don't lose data.** Integrity checks gate every destructive action.
3. **Make the common case automatic, the rare case possible.**
4. **Pluggable, not married.** STT/LLM/cloud are swappable behind interfaces.
5. **Explain itself.** The UI shows what ran, what's queued, and what failed.
