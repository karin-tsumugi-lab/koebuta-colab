# Audio retention and recovery

Ordinary reusable cache: latest 32 keys. Current candidates, current accepted
audio, references and prior accepted history are protected independently.
Persistence publishes the new manifest before removing obsolete WAVs owned by
the previous manifest. Files absent from that ownership record are never cleanup
targets, even when their names look like generated audio. Failed publication
does not run cleanup. Destination and local caches therefore share retention.

Prior accepted history is retained without automatic deletion, following the
original explicit requirement to preserve old accepted audio. Consequently,
45 different adopted takes can legitimately retain 45 WAVs. An automatic history
cap would change that requirement and is not enabled. A future explicit user
cleanup/archive action can provide a selectable history limit.

Current accepted audio and candidates are mandatory during restoration. Missing
or corrupt historical takes and ordinary cache entries are omitted; missing
history produces a warning. Copies use the filtered manifest and do not fail
solely because a historical take is absent.

CPU verification: 45 regenerate/discard/persist cycles retain 32 managed WAVs
and preserve an unrelated user WAV; missing history permits restore and copy.
These are filesystem mock tests, not Google Drive integration observations.
