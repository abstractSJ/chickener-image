---
name: chickener-image
description: Default workflow for generating, editing, transforming, or using raster images as references with the configured personal OpenAI-compatible Images API and gpt-image-2. Use whenever the user asks to generate, create, draw, illustrate, render, edit, transform, or make an image, picture, photo, artwork, poster, banner, mockup, texture, or other bitmap asset. Do not use for SVG/vector work or code-native diagrams.
---

# Chickener Image

Treat this as the default path for raster image generation and editing. Use this skill's script for every image request; do not call the provider with ad-hoc curl or SDK code.

When input images are present, first determine from the user's wording whether they should be edited independently, used together as references, or handled in stages. Do not infer the relationship from the number of images alone. If the intended relationship is ambiguous, ask a concise clarification before making a billable request.

## Workflow

1. Turn the user's request into a concise image prompt. Preserve exact requested text and constraints.
2. Preserve the user's input order as stable labels `图1` through `图4` when they refer to numbered images. Do not renumber after validation or between processing stages.
3. Determine the operation from the user's intent: generation, single-image editing, independent batch editing, joint reference, or a clearly requested multi-stage workflow. Do not silently switch operations; ask when the relationship between multiple images is unclear.
4. Choose an output path. Use `output/imagegen/` in the current project when the user does not specify a location; otherwise use the user's location. Resolve relative paths from the current project, never from the installed skill directory.
5. Resolve the skill directory from the location of this `SKILL.md`; never assume a user name, home directory, operating system, or install root.
6. Run `<skill-directory>/scripts/generate_image.py` with the explicit operation, `--prompt`, and output arguments. Use `--quality low` for a draft and `medium` or `high` for a final asset. Refuse before making a request when more than 4 input images or 4 final outputs are requested.
7. Inspect the written image with `view_image`. Treat this call as internal quality assurance only. If the image misses a required detail, make one targeted prompt revision and regenerate to a new filename.
8. Deliver every approved output in a separate final tool call as a generated-image result block. In `functions.exec`, load each file with `tools.view_image(...)`, then call `generatedImage({ image_url: result.image_url, output_hint: "short descriptive title" })`. This makes the image appear directly in the conversation instead of only inside a collapsible `view_image` trace.
9. Do not use a plain `view_image` call, the generic `image(...)` helper, a Markdown link, or a filesystem path as the user-facing image delivery. Each image must be emitted with `generatedImage(...)`. Do not report saved paths unless the user asks for them or needs them integrated into project files.
10. Report the model, size, quality, and final prompt concisely after the inline images. Never print credentials or configuration-file contents.

## Model selection

Choose the model yourself unless the user names one. If the active configuration file lists a `models` array, treat it as the whitelist of what the configured endpoint actually supports and choose only from it. Otherwise fall back to the built-in default.

| Model | Traits | Choose for |
|---|---|---|
| `gpt-image-2.5-flare` | Fastest current model; quality comparable to or better than gpt-image-2 at much lower latency | Everyday generation, drafts, bulk or user-facing requests |
| `gpt-image-2.5-sunburst` | Highest quality and editing precision; noticeably slower | Final assets, multi-turn edits, in-image text, product or character fidelity |
| `gpt-image-2.5` | Unsuffixed alias some gateways route to flare or sunburst | Avoid; prefer the explicit flare or sunburst ID when listed |
| `gpt-image-2` | Previous generation; reliable baseline | When no 2.5 variant is available on the endpoint |
| `gpt-image-1.5` | Older, cheapest and quickest, visibly weaker | Rough drafts only |

Some gateways also list `gemini-3.1-flash-image`, but it is served through chat completions rather than the Images API, so the script cannot call it; do not select it.

Default routing: drafts use `gpt-image-2.5-flare` with `--quality low`; final assets use `gpt-image-2.5-flare` with `medium` or `high`; work where a wrong detail makes the image unusable (text, logos, product shape, character identity, multi-step edits) uses `gpt-image-2.5-sunburst`. A `model` value in the configuration file overrides this routing as the default; `--model` overrides both for a single run.

## Error handling

The script never retries a request by itself; do not compensate by firing repeated generation requests in a loop. Every attempt is potentially billable, even ones that fail or time out.

Classify the failure before acting:

- Request or configuration errors (HTTP 400, 401, 403, 404, invalid parameter, model not found): never retry the identical request. Fix the cause once, such as a wrong model name or bad parameter, or stop and report.
- Provider-side failures (HTTP 429, 5xx, timeout, connection error, no available channel): the upstream may be degraded. Wait at least 60 seconds, then make at most one follow-up attempt with the identical request.

Circuit breaker: after two consecutive failed attempts for the same task, stop generating entirely. Report the HTTP status and the redacted error body, state that retries stopped to avoid repeated charges, and ask the user how to proceed: wait, pick another model from the configuration `models` list, or switch the endpoint. Do not send further image requests until the user responds.

Never silently switch models or endpoints after a failure; offer the switch as an option instead.

## Multi-turn editing

The API is stateless: there is no server-side session, so each follow-up edit must pass the previous output file back as `--input` with `--operation edit`. Keep the chain on disk:

1. Generate or edit to a file such as `output/imagegen/poster.png`.
2. For a follow-up change, run `--operation edit --input output/imagegen/poster.png --out output/imagegen/poster-2.png` with one targeted instruction.
3. Number each new round (`poster-2.png`, `poster-3.png`, ...) instead of overwriting, so any earlier round stays recoverable.

Make one meaningful change per round and state explicitly what must be preserved, for example: "Replace the background with a night sky. Preserve the subject, camera angle, text, and colors." Use `gpt-image-2.5-sunburst` for precision-sensitive edits. Quality degrades over many sequential edits (detail drift, warped text), so for large changes prefer regenerating from the original image or from scratch rather than chaining a long edit sequence.

## Inline delivery example

Use a dedicated `functions.exec` call after visual inspection:

```javascript
const result = await tools.view_image({
  path: "C:\\absolute\\path\\to\\final.png",
  detail: "original"
});
generatedImage({
  image_url: result.image_url,
  output_hint: "Concise image title"
});
```

## First-time setup

- The script uses the official OpenAI Python SDK. If `openai` is unavailable, install `<skill-directory>/requirements.txt` into the active Python environment.
- The simplest setup is a skill-local configuration file: copy `<skill-directory>/config.example.json` to `<skill-directory>/config.json` and fill in `api_base` and `api_key`. The file is git-ignored and must never be committed.
- `config.json` may also set a default `model`; `CHICKENER_IMAGE_MODEL` overrides it, and `--model` overrides both for a single run.
- Alternatively, use the per-user configuration file `$CODEX_HOME/secrets/chickener-image.json`, with `$CODEX_HOME` defaulting to `~/.codex`. The skill-local `config.json` takes precedence when both exist.
- If configuration is missing, instruct the user to run `python <skill-directory>/scripts/configure.py` themselves in a local interactive terminal. The helper hides API key input and writes the configuration outside the skill directory.
- Never ask the user to paste an API key into chat, pass it on a command line, print it, or commit it. The user must enter it locally through the configuration helper or set `CHICKENER_IMAGE_API_BASE` and `CHICKENER_IMAGE_API_KEY` in their environment.
- After configuration, verify presence without revealing values by running `python <skill-directory>/scripts/configure.py --check`.

## Command

```text
python <skill-directory>/scripts/generate_image.py \
  --prompt "A red apple on a white table, studio photograph, no text" \
  --out "output/imagegen/apple.png" \
  --size 1024x1024 \
  --quality medium
```

Environment variables `CHICKENER_IMAGE_API_BASE` and `CHICKENER_IMAGE_API_KEY` override the per-user configuration file when temporary credentials or endpoints are needed.

Image generation requests use a 240-second client timeout so slower successful provider responses can still be received and saved.

## Constraints

- Pick the model per the Model selection section; PNG output and opaque backgrounds stay fixed.
- Accept at most 4 input images and at most 4 final output images per task; refuse before any API request when either limit is exceeded.
- Keep the input order stable as `图1` through `图4`; when multiple images are jointly referenced, submit them in that order and preserve the mapping in the prompt context.
- Do not request `background=transparent`; this provider path is validated only for normal image generation.
- The script refuses to overwrite an explicitly specified existing file unless `--force` is provided; automatically generated default names avoid collisions.
- Keep all image requests serial: only one request may be in flight at a time.
- When multiple outputs are requested, issue one `n=1` request per output rather than relying on batched `n` responses.
- Never automatically retry an image API request. A timeout, connection failure, HTTP error, or malformed response may occur after the provider has already processed and charged the request.
- Never loop generation requests in the conversation either; after two consecutive failures for the same task, stop and ask the user per the Error handling section.
- Preserve successful outputs when a later serial request fails, and report the affected output with a warning that the result may have been charged.
- Always emit every approved output with `generatedImage(...)` after generation or editing succeeds. A successful `view_image` inspection alone does not count as delivery.
- If the API reports no available channel, report the provider-side routing error rather than retrying with another model.
