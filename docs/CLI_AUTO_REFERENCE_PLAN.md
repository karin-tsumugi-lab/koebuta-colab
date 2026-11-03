# CLI automatic reference voice: proposed changes

Requested 2026-11-03. Implemented on `codex/cli-auto-reference` for review;
not merged. Short three-condition T4 generation/recovery was verified on 2026-11-03;
listening quality is unverified. See [the adopted specification](CLI_AUTO_REFERENCE.md)
and [GPU observations](reviews/CLI_AUTO_REFERENCE_GPU.md).

Accepted clarification: explicit design/no-ref remains unchanged; ambiguous
speaker WAV assignments in shared reading fail unless a shared WAV is supplied;
changed reference conditions invalidate dependent speech. Show one pre-generation
`[y/N]` prompt. `--yes` or settings `confirm: false` skips the prompt, never errors.
Noninteractive execution requires an explicit confirmation bypass. The host shows
the maximum affected utterances; actual remote cache reuse is known on the worker.

The requirements below are retained as the acceptance checklist.

- Preserve explicitly assigned WAVs. Missing assignments must no longer block
  generation. Distinguish an omitted reference from an explicitly supplied
  missing/corrupt file; reject the latter rather than silently substituting.
- For a speaker with multiple utterances, select suitable normal speech before
  generating the conversation: provisional heuristic 20–100 characters, neutral
  emotion, no exclamation/question/ellipsis, target 60 characters. This heuristic
  cannot guarantee neutral content; show the selection and allow replacement.
- Generate that line without reference, emotion or acting, using the speaker's
  voice caption. Save as an immutable reference, then clone all actual utterances
  including the selected line in original order with normal emotion/acting.
- A single-utterance speaker or a speaker without suitable speech uses no-ref
  generation directly. Report that cross-utterance voice consistency is not assured.
- Shared reading uses a single shared voice group. Explicit shared WAV wins.
- Add a preparation stage before `sampling_plan` validation; host dry-run must
  describe planned reference generation without GPU work. Resolve actual reference
  hashes before creating final speech fingerprints on the worker.
- Version reference metadata: selected segment/text, voice caption, seed/steps,
  pinned model/codec/upstream revisions, resulting WAV hash. Persist/recover these
  references with the job. A resumed job reuses verified references instead of
  silently selecting a different voice. Replacing a reference invalidates dependent
  speech cache; pause-only edits do not.
- Adjust `load_inputs`, `sampling_plan`, worker preparation, transfer/recovery,
  CLI progress/plan display and documentation together. Do not overwrite original
  scenario/settings. Keep existing explicit clone/design behavior compatible.
- CPU acceptance cases: supplied reference precedence, omitted versus invalid WAV,
  scream-first with suitable later speech, one utterance, all-short speech, shared
  reading, repeatable selection, cache invalidation, corrupt reference, interrupted
  preparation/recovery and unchanged original inputs. GPU/listening checks remain
  separate and require authorization.
