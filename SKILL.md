---
name: chickener-image
description: Default workflow for creating new raster images with the configured personal OpenAI-compatible Images API and gpt-image-2. Use whenever the user asks to generate, create, draw, illustrate, render, or make a new image, picture, photo, artwork, poster, banner, mockup, texture, or other bitmap asset. Do not use for editing an existing image, SVG/vector work, or code-native diagrams.
---

# Chickener Image

Treat this as the default path for new image generation. Use this skill's script for every generation; do not call the provider with ad-hoc curl or SDK code.

## Workflow

1. Turn the user's request into a concise image prompt. Preserve exact requested text and constraints.
2. Choose an output path. Use `output/imagegen/` in the current project for project assets; otherwise use a descriptive path under the current workspace.
3. Resolve the skill directory from the location of this `SKILL.md`; never assume a user name, home directory, operating system, or install root.
4. Run `<skill-directory>/scripts/generate_image.py` with `--prompt` and `--out`. Use `--quality low` for a draft and `medium` or `high` for a final asset.
5. Inspect the written image with `view_image`. Treat this call as internal quality assurance only. If the image misses a required detail, make one targeted prompt revision and regenerate to a new filename.
6. Deliver the approved image in a separate final tool call as a generated-image result block. In `functions.exec`, load the file with `tools.view_image(...)`, then call `generatedImage({ image_url: result.image_url, output_hint: "short descriptive title" })`. This makes the image appear directly in the conversation instead of only inside a collapsible `view_image` trace.
7. Do not use a plain `view_image` call, the generic `image(...)` helper, a Markdown link, or a filesystem path as the user-facing image delivery. The image itself must be emitted with `generatedImage(...)`. Do not report the saved path unless the user asks for it or needs the image integrated into project files.
8. Report the model, size, quality, and final prompt concisely after the inline image. Never print credentials or configuration-file contents.

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
- The default configuration file is `$CODEX_HOME/secrets/chickener-image.json`, with `$CODEX_HOME` defaulting to `~/.codex`.
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

- Default to `gpt-image-2`, one image, PNG output, and opaque backgrounds.
- Do not request `background=transparent`; this provider path is validated only for normal image generation.
- The script refuses to overwrite an existing file unless `--force` is explicitly provided.
- Always emit the approved file with `generatedImage(...)` after generation succeeds. A successful `view_image` inspection alone does not count as delivery.
- If the API reports no available channel, report the provider-side routing error rather than retrying with another model.
