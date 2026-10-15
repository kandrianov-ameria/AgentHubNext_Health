# Test assets

Committed on purpose - a fresh clone must be able to run. Nothing here is secret.

| File | Used by | What it is |
|---|---|---|
| `probe.jpg` | SAM3 segmentation checks, live 3D / video generation | 640x360 JPEG with the word MAVERICK on a blue panel |
| `probe_silence.wav` | Whisper request-contract checks | 3 s of silence, 16 kHz mono PCM16 |

The Whisper checks validate the request and the response *shape*, so silence is
enough. A spoken-sentence WAV would only be needed for transcription-accuracy
checks, which the suite does not contain.
