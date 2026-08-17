# Handoff Windows — RTX 5070 Ti 12GB

This handoff keeps the agreed OCR choice: **DeepSolo + PARSeq-VN**. The
repository does not copy or download DeepSolo code/checkpoints. Before setup,
Việt receives those approved local artifacts and fills `.env` from
`.env.example`.

## One-time setup

1. Install Python **3.12 x64** and a current NVIDIA driver.
2. Copy `.env.example` to `.env` and set all three DeepSolo/PARSeq paths.
   Also set the three `WP04_*_COMMAND` values. They are local approved model
   commands, not a URL. WP04 replaces `{keyframe_path}` or `{audio_path}` in
   the command and requires JSON on stdout:

   ```json
   {"detections":[{"text":"BÁNH MÌ","bbox_xyxy_norm":[0.1,0.2,0.3,0.4],"confidence":0.9}]}
   ```

   OCR uses `text`; object detection uses `label` instead. ASR emits
   `{"segments":[{"start_ms":1000,"end_ms":2000,"text":"...","confidence":0.9}]}`.
3. Open PowerShell in this folder and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

The script creates `TV3/WP04/.venv-gpu`, installs the PyTorch CUDA 12.8 wheel,
downloads the pinned ChunkFormer revision, writes its resolved file SHA256s to
`checkpoints.lock.json`, installs RF-DETR and checks that CUDA is visible. It
fails before inference when the DeepSolo/PARSeq artifacts are absent.

## Run

```powershell
.\run.ps1 -RunDir C:\AIC\data\runs\run-a -PreprocessRunId run-a `
  -ArtifactSetId wp04-a -FramesJson C:\AIC\frames.json -AudioJson C:\AIC\audio.json
```

`frames.json` is a TV1 `FrameRecord` array and `audio.json` is a TV1
`AudioRecord` array. Keep original `video_id`, `frame_id`, `timestamp_ms` and
`preprocess_run_id` unchanged.

## Known gate

The existing package has adapter seams but does **not** embed/copy DeepSolo
runtime code. Supplying the three local paths satisfies artifact availability;
the next integration task is wiring the approved local DeepSolo/PARSeq command
or library API to `wp04.adapters.OCRAdapter`. This remains deliberately visible
as a failed OCR modality until wired, rather than yielding misleading results.

PyTorch's Windows builds support Python 3.9–3.12, and CUDA wheel selection
must follow the installed NVIDIA driver. ChunkFormer documents its pinned model
repository and `pip install chunkformer`; RF-DETR documents `pip install rfdetr`.
