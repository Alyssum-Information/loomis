# 02 · User Flows

| | |
|---|---|
| **Document** | User Flows |
| **Doc ID** | LM-02 |
| **Version** | 0.2 (Draft) |
| **Last updated** | 2026-06-10 |
| **Related** | [01 Vision](01-vision-and-scope.md), [03 SRS](03-requirements-specification.md), [04 Architecture](04-system-architecture.md), [features/](features/) |
| **Traces** | Drives FR-1 … FR-9 |

---

These are the end-to-end journeys Loomis must support. They drive the
[functional requirements](03-requirements-specification.md). Each flow lists the
trigger, the happy path, the key decision points, and the failure handling.

Legend: 🟢 automatic · 🟡 requires user · ⚠️ safety-critical step.

## 1. First-time device registration

**Trigger:** An unregistered USB storage device is connected.

1. 🟢 Device Watcher detects a new removable volume.
2. 🟢 Loomis looks for `<volume>/.loomis/device.json`.
3. If absent, 🟢 Loomis surfaces a "New device found" prompt in the UI.
4. 🟡 User confirms registration and sets: device name; default owner/speaker
   hint; auto-delete-after-backup (default **off**); transcode preference
   (default **off**); which folders/extensions hold audio.
5. 🟢 Loomis writes `device.json` to the device and inserts a `devices` row in
   SQLite, keyed by a generated `device_id` (plus volume serial as a hint).
6. 🟢 Flow continues into **§2 (Auto-backup)** for the initial import.

**Alternative:** A power user can pre-create `device.json` by hand; Loomis
validates it and registers silently.

**Failure handling:** Device read-only / no space for `device.json` → register
in DB only; warn that on-device identification is unavailable (fall back to
volume serial / label matching).

> Detail: [features/01 Device Registration & Backup](features/01-device-registration-and-backup.md).

## 1b. Folder source registration (phones, lifeloggers)

**Trigger:** The user has recordings landing in a local folder — a phone's
sync target (Syncthing / OneDrive / iCloud Drive), a wearable's companion-app
export folder, or a folder they drop files into by hand.

1. 🟡 User adds the folder on the Devices screen (or `loomis backup <folder>`),
   with the same settings as a device: name, owner hint, globs, transcode
   preference. Auto-delete defaults **off** (FR-1.13) — the folder usually
   belongs to a sync tool, so Loomis copies and leaves it alone.
2. 🟢 Loomis writes `<folder>/.loomis/device.json` (same contract as a recorder
   volume) and inserts a `devices` row with `kind = "folder"`.
3. 🟢 The daemon **polls** the folder (`[backup].folder_poll_interval_s`) and
   imports anything new through the identical safety spine — ledger dedupe,
   SHA-256 verify, quarantine (**§2** steps 3–9).

**Failure handling:** Folder missing (drive unmounted, sync paused) → skip
silently and retry next poll. Files still being written by the sync tool are
not touched: a file is only imported once it has been **stable** for
`[backup].folder_settle_seconds` (mtime quiet period), so a half-synced file
never enters the library.

> Detail: [features/01 §3.2](features/01-device-registration-and-backup.md),
> [ADR-0012](adr/0012-folder-sources.md).

## 2. Auto-backup on connect

**Trigger:** A *registered* device is connected (or registration just finished).

1. 🟢 Read `device.json`, resolve the device row.
2. 🟢 Enumerate audio files matching the device's globs.
3. 🟢 For each file, compute an identity (path + size + mtime, then content
   hash) and check it against the backup **ledger** (`recordings` table).
4. 🟢 Copy *new* files into the local **staging** area.
5. ⚠️ Verify the copy by SHA-256 before the file is considered backed up.
6. 🟢 Transcode to Opus into the library (default; keep/discard original per
   policy — [ADR-0013](adr/0013-transcode-by-default.md)).
7. ⚠️ (Optional) If auto-delete is on, delete the source file **only after** the
   verified backup (and, if transcoding, after the transcode also verifies).
8. 🟢 Enqueue a processing job per imported recording (**§3**).
9. 🟢 Update `last_seen` on the device; show an import summary in the UI.

**Failure handling:** Device removed mid-copy → partially copied files are not
committed to the ledger; resume on next connect. Hash mismatch → quarantine the
file and never delete the source.

> Detail: [features/01](features/01-device-registration-and-backup.md),
> [features/02 Audio Compression](features/02-audio-compression.md).

## 3. Processing pipeline (per recording)

**Trigger:** A recording is imported (job enqueued). Runs in the background;
fully resumable.

1. 🟢 **Transcode** (if not already done) → normalized audio for STT.
2. 🟢 **Speech-to-text** (WhisperX): segments with word-level timestamps + language.
3. 🟢 **Diarization** (pyannote): assign speaker turns.
4. 🟢 **Speaker identification**: extract a voiceprint per turn, match against
   the voiceprint DB; assign known or provisional identity.
5. 🟢 **Classify** the recording as *diary-type* or *meeting-type*.
6. 🟢 Persist transcript + segments + speaker assignments.
7. 🟢 Hand off to **§4** (diary) and/or **§5** (meeting). During those steps the
   LLM also proposes **names for unnamed speakers** from conversational evidence
   (FR-5.8); proposals surface in the UI for confirmation (**§6**).

**Failure handling:** Each stage is a separate retryable job step with attempt
counts and recorded errors; a failed stage blocks only its own recording.

> Detail: [features/03 Transcription](features/03-transcription.md),
> [features/04 Speakers](features/04-speaker-diarization-and-identification.md),
> [features/05 Summarization](features/05-summarization-and-organization.md).

## 4. Daily diary assembly

**Trigger:** New diary-type recordings exist for a calendar date (user timezone),
debounced so a day is summarized once it looks "settled."

1. 🟢 Gather all diary-type recordings for that date.
2. 🟢 Build a combined, time-ordered, speaker-labeled transcript.
3. 🟢 LLM (diary mode) writes a first-person daily entry: narrative, topics,
   mood, to-dos/decisions.
4. 🟢 Store the entry as Markdown + structured metadata; link the source clips.
5. 🟢 Insert links to any **meetings** that occurred that day (from §5).
6. 🟢 Re-generation is idempotent: late-arriving clips trigger a re-summary.

## 5. Meeting extraction

**Trigger:** A recording (or contiguous group) is classified as a genuine
multi-speaker discussion.

1. 🟢 Create a standalone **meeting** record (separate from the diary).
2. 🟢 LLM (meeting mode) produces: title, attendees (mapped to known speakers),
   summary, decisions, action items with owners.
3. 🟢 Store as Markdown + structured metadata.
4. 🟢 Add a reference link from that day's diary entry back to the meeting.

## 6. Browse & review (UI)

**Trigger:** User opens the local web UI.

- 🟡 **Timeline / calendar** of days, each showing diary entry + meeting chips.
- 🟡 **Recording detail**: audio player, transcript with speaker labels, jump-to.
- 🟡 **Speakers**: list of identities; rename, merge, split; confirm/correct
  auto-assigned identities (feedback improves future matching). LLM-suggested
  names (FR-5.8) appear here for one-click acceptance — a suggestion never
  becomes the display name on its own.
- 🟡 **Search** across all transcripts, diaries, and meetings.
- 🟡 **Jobs/health**: what's queued, running, failed; retry controls.
- 🟡 **Settings**: devices, defaults, models, cloud remotes.

> Detail: [07 UI/UX Design](07-ui-ux-design.md).

## 7. Cloud sync (optional)

**Trigger:** Manual "sync now," or a schedule, with cloud sync enabled.

1. 🟡 User configures one or more rclone remotes (OneDrive, Google Drive, …).
2. 🟡 User chooses what to sync (audio, Markdown, DB backup) and direction (push).
3. 🟢 Loomis runs rclone, surfaces progress, logs the result.
4. ⚠️ Cloud sync never deletes local source data; remote-side deletion is opt-in
   and clearly labeled.

> Detail: [features/06 Cloud Sync](features/06-cloud-sync.md).

## 8. Device removed / reconnected

- 🟢 On removal mid-work, in-flight imports stop cleanly; nothing half-copied is
  committed.
- 🟢 On reconnect, Loomis resumes: the ledger skips already-backed-up files, and
  unfinished processing jobs continue from their last good step.
