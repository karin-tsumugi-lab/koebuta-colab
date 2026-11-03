# Voice candidate guide: adoption evidence

Date: 2026-11-03 JST. Branch: feature/voice-candidate-guide. Base: b423ddc.

## Requirement and scope

Adopt the user's VOICE_CANDIDATE_FLOW_SLIM.md after correcting portability,
measurement attribution, account-wide CU wording, voice-consistency claims,
and the environment-specific proxy workaround. Documentation only; no CLI,
JSON schema, authentication, or runtime implementation changes.

Changed paths: cli/docs/AI_VOICE_CANDIDATES.md, cli/README.md,
cli/AGENTS.md, and this evidence record. The integration owner's
docs/INTEGRATION_STATUS.md is not edited by this contribution.

## Commands/tests and results

- git diff --check: passed before commit.
- Parsed the guide's JSON settings and three Python command examples.
  Replaced only example input/output paths with temporary fixtures and added
  --dry-run; ran the repository's irodori_generate.main for all three: passed.
- Checked that the plans use seed 1/2/10 respectively, all requests are
  VoiceDesign, and no generation output directories are created: passed.
- Checked the local README/AGENTS/guide link targets: passed.
- GPU generation, model residency and the supplied timing benchmark: not run.

## Requirement-to-observation evidence

- Environment portability: the fixed /home/hatch path is replaced with an
  explicitly editable path; YOMIBUTA_COLAB_BIN is optional and environment-specific.
- Runtime reuse: examples use --new only for the first candidate and
  --skip-prepare for later candidates; final example requests verified shutdown.
  Actual runtime reuse is not verified by this documentation change.
- Measurement honesty: 4m11s, 44-55s and about 11.5 minutes are attributed to
  the user-supplied document; missing execution logs and no independent
  verification are explicitly stated. Performance conformance: not verified.
- CU: 0.06 is described as an account-balance difference, not per-job consumption.
- Voice selection: the user chooses; cloning is described as carrying a voice
  forward, with listening on another text required rather than a guarantee.
- Proxy workaround: attributed to the original VM and explicitly prohibited
  from automatic application to other environments.
- Adoption: the new canonical CLI guide is linked from README and AGENTS.

## Unresolved / integration handoff

No independent benchmark logs supplied; do not promote the reported figures
to a verified project benchmark. This does not implement a batched-seed CLI.
Final merge recommendation and integration ledger update belong to Sol / the
designated integration owner. No main update or merge is performed here.
