# CLI review fixes: recovery and original utterance counts

2026-11-03 JST. Branch `codex/cli-auto-reference`, same isolated worktree and
PR #4. Fix base: `70c2be8`. No other branch or integration-ledger edits.

## Requirements and observations

1. A supplied valid WAV must replace an unused corrupt automatic reference
   without failing recovery after main speech has already completed.
   Job metadata now records `active_groups` separately from retained `entries`.
   The CPU reproduction creates references for A/B, corrupts A, assigns A a valid
   WAV, and reuses B. Main generation and `verify_recovery` succeed, with one
   active reference. Old corrupt A remains untouched in job history. Corrupting
   active B still fails verification. The public export contains only active
   references; changing all groups to design exports zero reference WAVs.
2. One original utterance must use no-ref even when it becomes multiple TTS
   fragments. `prepare_with_mapping` records each fragment's original ID in
   `autoReference.sourceSegments`, and preserves that ID through subsequent host,
   parent and worker normalization/splitting. A 132-character original utterance
   splits into two fragments but remains fallback/no-ref in cast and shared
   reading, with zero reference inference calls. Per-speaker counts are separate;
   adding a second original utterance still enables automatic reference.

## Interface and compatibility

- Version-1 `references.json` gains optional `active_groups`. Without it, all
  entries are treated as active, preserving old-job validation. Historical files
  are retained. The top-level public metadata contains only the active entries.
- Project `autoReference` gains internal `sourceSegments` (fragment ID to original
  utterance ID). It is not a new user-settings key. The mapping survives project
  normalization/transfer and repeated preparation. Existing unsplit projects
  gain it on their next preparation. Original utterance identity cannot be
  reconstructed from an old already-split project that lacks provenance;
  loading its original scenario through the current host restores the mapping.
- Reference request/engine signatures and final speech fingerprints are unchanged
  for ordinary multi-utterance inputs. No inference backend changes.

## Commands/tests (separate from the observations above)

- Windows Python 3.14, from `cli/`:
  `python -X utf8 -m unittest test_auto_reference test_irodori_generate test_cli_terminal`:
  **63 passed**. Local `review-fix-cpu-tests.log`.
- WSL Ubuntu-26.04 Python 3.14, same three modules via `python3 -m unittest`:
  **63 passed**. Local `review-fix-wsl-tests.log`.
- Existing Inspector/Notebook standard-library suite: **16 passed**.
  Same invocation as `CLI_AUTO_REFERENCE_ACCEPTANCE.md`;
  local `review-fix-root-tests.log`.
- BUILD hash refresh: 57 files verified. CRLF-aware diff check passed.
- New GPU generation after these fixes: **not run**. Tests use local PCM WAVs
  and a fake inference backend, including real worker orchestration. Prior
  three-condition T4 evidence applies to `db3c58d`; the user subsequently said
  those generated samples were fine. It is not a GPU test of these fixes.
- Full notebook UI smoke remains unverified, as recorded in the initial handoff.

Integration/merge recommendation remains with Sol and the integration owner.
