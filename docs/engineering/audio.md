# Bounded CPU speech training and generation

TASK-29 implements one explicit English text-to-speech profile. It uses the actual SpeechT5 pretrained weights, character/audio processor, published demo speaker-conditioning vector and HiFi-GAN vocoder. It trains only the mel and stop output heads (124,578 of 144,431,684 TTS parameters), with FP32 AdamW on one cooperating CPU thread. Model output is an actual PCM16 WAV. Registry labels, metadata-only training and empty files cannot establish a successful result.

Customer quality, production release, human listening, speaker identity/fidelity, customer voices, product ASR, voice cloning, other languages/models and GPU/distributed execution require separate qualification. The small automatic test below is an intelligibility proxy, not a customer acceptance result.

## Exact public sources

| Component | Repository | Revision | License |
| --- | --- | --- | --- |
| TTS | [microsoft/speecht5_tts](https://huggingface.co/microsoft/speecht5_tts) | `30fcde30f19b87502b8435427b5f5068e401d5f6` | MIT |
| Vocoder | [microsoft/speecht5_hifigan](https://huggingface.co/microsoft/speecht5_hifigan) | `bb6f429406e86a9992357a972c0698b22043307d` | MIT |
| Fixed demo conditioning | [Matthijs/cmu-arctic-xvectors](https://huggingface.co/datasets/Matthijs/cmu-arctic-xvectors) | `5c1297a9eb6c91714ea77c0d4ac5aca9b6a952e5` | MIT |
| Independent transcription proxy | [openai/whisper-tiny.en](https://huggingface.co/openai/whisper-tiny.en) | `87c7102498dcde7456f24cfd30239ca606ed9063` | Apache-2.0 |

Every file has a literal SHA-256 pin in `audio_math.py` / `audio_runtime.py`; the independent consumer has its own pins. The original TTS/vocoder publisher checkpoints are converted once by `scripts/convert_speecht5.py`. It checks the complete original SHA **before** `torch.load(weights_only=True, mmap=True, map_location='cpu')`, admits finite FP32 tensors and the five published scalar int64 BatchNorm counters, and verifies the resulting exact SafeTensors SHA. It does not allow custom pickle globals, download or execute remote code. The application loads SafeTensors only.

The exact source has two legacy positional buffers that Transformers marks nonpersistent. Both are explicitly restored from the pinned tensors, with fixed shape/finite checks. Other missing/unexpected/mismatched tensors fail. The vocoder's historical `hifigan` model-type alias is accepted only through the fixed SpeechT5 class, exact source files and complete tensor match.

Conditioning is the bounded `spkrec-xvect/cmu_us_slt_arctic-wav-arctic_a0001.npy` member, loaded with NumPy `allow_pickle=False`. Its SHA and 512-element FP32 vector are checked. No dataset loading script runs. This is fixed demo conditioning, with no user voice capture or speaker-fidelity claim.

## Operator setup

Install `requirements.txt` and `requirements.audio.txt` in the API/worker environment normally, with dependencies. The pins include SoundFile, CFFI and SciPy. Use local filesystem storage shared by API and worker, one dedicated single-slot CPU worker, at least 16 GiB observed host memory and enough local disk for immutable artifacts and bounded staging. Observed memory is host capacity, not an idle/free-memory reservation.

Provision these exact local files through your authorized acquisition process:

```text
speech-base/
  config.json
  preprocessor_config.json
  tokenizer_config.json
  special_tokens_map.json
  added_tokens.json
  spm_char.model
  model.safetensors
  speaker.npy
  vocoder/config.json
  vocoder/model.safetensors
whisper-proxy/
  model.safetensors
  config.json
  generation_config.json
  preprocessor_config.json
  tokenizer.json
  tokenizer_config.json
  special_tokens_map.json
  added_tokens.json
  normalizer.json
  vocab.json
  merges.txt
```

For the two pinned publisher `.bin` files, convert into new destinations:

```sh
python scripts/convert_speecht5.py tts /local/published-tts/pytorch_model.bin /local/speech-base/model.safetensors
python scripts/convert_speecht5.py vocoder /local/published-vocoder/pytorch_model.bin /local/speech-base/vocoder/model.safetensors
```

Upload each recording with authenticated `POST /api/v1/audio/upload-audio/` (multipart `file`, active project). This validates actual bytes and returns artifact and normalization provenance. Prepare canonical sample-envelope JSONL with exactly two blocks: a user text transcript and an assistant audio block with `asset_ref: artifact:UUID`. Preserve the real `source_group_id`, `metadata.speaker_id`, source snapshot/record/hash provenance, audio MIME and audio hash. At least three rows and nonempty training, validation and protected-test splits are required. A speaker, source group, identical source audio or identical normalized PCM cannot cross splits. Group-aware publication does not fabricate a new speaker identity when choosing a split seed.

```sh
python manage.py setup_audio_training \
  --tenant-id TENANT_UUID --project-id PROJECT_UUID --name speech-pilot \
  --model-dir /local/speech-base --evaluator-dir /local/whisper-proxy \
  --samples /local/paired-speech.jsonl --split-seed 0 --steps 2
```

Setup verifies/imports the complete source, processor, vocoder, conditioning and evaluator as scoped immutable artifacts, publishes the dataset, and returns worker/pool/budget and training launch IDs. It performs no model download or training. Choose a seed whose real source groups produce all three splits; otherwise setup refuses. It creates a two-step quota (or the selected step count) and a separate 288,000-sample speech quota, enough to reserve three six-second attempts for one generation. Further requests require sufficient remaining quota through normal budget administration.

In **Training → Advanced settings**, select **Speech output head**, the imported base/tokenizer/dataset/runner/pool, 1–10 steps and the training budget. Preview preflight and launch. Estimates count real target mel frames; CPU engine timing excludes queue, staging, database/checkpoint writes, independent scoring and retries. Throughput has mel-frame units, not text-token units.

Run the fixed operator dispatcher:

```sh
python manage.py run_worker --worker-id WORKER_ID \
  --executor modelanvil.runners.audio_generation.audio_executor
```

Leave this worker running while queuing training and speech. A one-shot `--once` execution intentionally marks its worker offline when it exits.

The dispatcher accepts only qualified training or typed audio-generation jobs. Job data cannot select a command or executor. The run's exact source bytes, dataset/features, build, package pins, device, pool/worker and quota are rechecked before commits. Restart API/worker after implementation changes; code changes invalidate a queued/recovered run's pinned build.

## Media, updates and recovery

Supported source recordings are **PCM16 WAV/FLAC, 0.25–6 seconds, mono/stereo, at most 4 MiB**, at 8,000, 16,000, 22,050, 24,000, 32,000, 44,100 or 48,000 Hz. Actual source rate/channel/frame/duration/hash, transcript/source/speaker identity and normalized hash are retained. Normalization explicitly averages channels, resamples to 16 kHz using SciPy polyphase/kaiser(5), clips and records clipping. Unsupported formats/subtypes/rates, malformed bytes, oversize data and non-finite samples fail. Text is 1–96 characters, at most 128 native tokens, with no reserved/unknown tokens; no silent truncation.

Native 80-bin mel targets preserve every frame. A single odd trailing frame is padded to the model's reduction factor of two with `-100` masking. Loss is the actual SpeechT5 composite spectrogram/stop/guided-attention loss, not a text-model loss. Only `feat_out` and `prob_out` weights/biases train. Frozen model evaluation mode protects other state. The decoder prenet's native dropout still consumes RNG, so every fenced checkpoint saves the exact head, Adam moments/step and CPU RNG state as SafeTensors, plus measured loss/gradient/count/CPU/wall/source evidence.

Automatic expired-lease recovery resumes the latest committed cursor with identical pins, head, Adam and RNG state. A stale worker cannot publish. Uncommitted work can repeat; training accounting is committed optimizer updates, and does not claim uncommitted elapsed computation was zero. Self-service recovery of a terminal failed job remains restricted to the separately qualified reference runtimes. Cancellation publishes no unfinished candidate.

## Speech generation, playback and export

**Audio** selects an accessible imported base or successfully trained draft, dedicated CPU pool and `audio_samples` quota. Submit text, seed and a 1–6 second bound. The API is `POST /api/v1/audio/jobs/`; fields are `model` (UUID), `text`, `seed`, `max_seconds`, `pool`, `budget_policy` (UUID), `idempotency_key`. Unknown fields fail. The same key and exact inputs return the same request; different inputs refuse reuse.

A fixed isolated offline CPU child reloads the exact processor/model/head/conditioning/vocoder. The parent holds the physical CPU lease (also inherited by the child), renews the durable fence and current authorization, and kills/waits on cancellation, lost lease or deadline. It validates actual bounded PCM16 WAV bytes and the independent checksum/source/settings report. Empty, silent, non-finite, severely clipped, failed or length-limited output is not successful complete speech.

Three attempts reserve `3 × max_seconds × 16000` output samples. Each started attempt records a conservative ceiling before computation. Verified frames replace that ceiling. A lost in-flight attempt retains the upper bound, explicitly marked unknown; terminal settlement is idempotent and never fabricates zero usage. Pending automatic retries retain their reservation. Queue cancellation before compute settles zero.

Poll `GET /api/v1/audio/jobs/REQUEST_UUID/`, cancel with `POST …/cancel/`, and play/download `GET …/audio/` (`?download=1` adds attachment disposition). All reads remain authenticated and project scoped, and verify committed output/source access. The Audio page fetches the bounded authenticated WAV into a short-lived object URL, uses native audio controls, revokes it on change, and downloads the same bytes. Model/processor/vocoder/source hashes, settings, actual rate/frames/duration, CPU/wall observations and draft qualification remain inspectable.

Completed training offers JSON provenance or the native ZIP: exact base, separate trained head, tokenizer/audio processor, demo-conditioning vector, vocoder, MIT license/attribution and provenance. Adam/RNG recovery state and ASR-proxy weights stay out of the inference export. The native package is approximately 607 MiB, so the existing 256 MiB in-memory browser fallback refuses it. Chrome/Edge's save picker streams to disk; an authenticated API client can also stream it. The independent consumer needs no application/Django imports:

```sh
python -I scripts/audio_candidate_infer.py /local/unpacked-native-export \
  --text 'Hello world.' --seed 42 --max-seconds 6 --output /local/new-speech.wav
```

## Independent automatic qualification protocol

At completion, a separate fixed CPU process reloads base and candidate from exact source/processor/head/vocoder/conditioning hashes, with **1–4 protected test recordings**. It independently decodes and hashes the audio, confirms no training speaker/source/raw/normalized audio overlap, and computes seeded native composite teacher-forced loss. It synthesizes bounded WAVs for the held-out transcripts and independently transcribes those actual generated WAVs with pinned Whisper Tiny English weights/processor. English case/punctuation-normalized Levenshtein word error rate (WER) is a proxy, with explicit reference word counts.

All four gates must pass: natural candidate stop, candidate loss ≤110% of base, candidate WER ≤0.5, and candidate WER ≤base+0.1. Reports bind the exact manifest/files/target audio/normalized samples and checkpoint digest; baseline/candidate WAV examples remain scoped artifacts for listening. The consumer must report no ModelAnvil/Django imports. An unavailable scorer or failed check leaves the actual trained candidate explicitly **draft, unqualified**; it never invents a passing result or promotes a release.

The bounded Mac proof uses three real qualified CC-BY-4.0 VCTK recordings, distinct speakers p225/p226/p227 and the common transcript “Please call Stella.” This establishes a narrow automatic protocol over three recordings and one phrase, not broad English quality, unseen linguistic generalization, speaker identity, human listening or customer acceptance. A later human gate should use protected representative prompts and independent listeners, recording intelligibility, naturalness, pronunciation and unwanted content separately before release. No such human result is claimed here.
