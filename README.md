# Chickener Image

A Codex skill that generates, edits, and uses raster images as references through a user-configured OpenAI-compatible Images API using the official OpenAI Python SDK.

No API endpoint or API key is included in this repository. Every user supplies their own configuration locally.

## Install with Codex

Give Codex this repository URL and the following instruction:

```text
Install the chickener-image skill from https://github.com/abstractSJ/chickener-image.
The skill is at the repository root and should be installed as chickener-image.
Use $skill-installer, install its Python requirements, then tell me how to run
the local configuration helper myself. Never ask me to paste my API key into chat.
```

The installing agent should:

1. Use `$skill-installer` to install the repository root as `chickener-image`.
2. Resolve the installed skill directory instead of assuming an operating-system-specific path.
3. Run `python -m pip install -r <skill-directory>/requirements.txt` in the Python environment that will execute the skill.
4. Tell the user to run `python <skill-directory>/scripts/configure.py` in their own interactive terminal.
5. After the user finishes, run `python <skill-directory>/scripts/configure.py --check`. This checks presence and validity without displaying the endpoint or key.
6. If Codex does not discover the newly installed skill automatically, restart Codex.

## Local configuration

The simplest option is a skill-local configuration file. Copy `config.example.json` to `config.json` in the skill directory and fill in the two fields:

```json
{
  "api_base": "https://your-gateway.example.com/v1",
  "api_key": "sk-replace-with-your-key"
}
```

`config.json` is listed in `.gitignore` and must never be committed. When it exists, it takes precedence over the per-user secrets file below.

The configuration helper prompts for the API base URL and hides API key input. It writes to:

```text
$CODEX_HOME/secrets/chickener-image.json
```

When `CODEX_HOME` is unset, it defaults to `~/.codex`. The configuration stays outside the installed skill and must never be committed.

Users may alternatively set both environment variables:

```text
CHICKENER_IMAGE_API_BASE
CHICKENER_IMAGE_API_KEY
```

Environment variables override the configuration file.

## Supported operations

The Skill accepts natural-language requests and chooses the operation from the user's intent. Users do not need to select an API method.

- **Generation**: no input image; create a new image from the prompt.
- **Single-image editing**: modify one input image.
- **Independent batch editing**: apply an instruction separately to each input image and produce one corresponding output per input.
- **Joint reference**: submit multiple input images together as references for one or more new outputs, if the configured service supports it.
- **Multi-stage workflows**: reserved for workflows such as editing images first and then jointly referencing the results; not required for the first implementation.

When users refer to `图1`, `图2`, `图3`, or `图4`, numbering follows the order in which the input images were supplied. The mapping remains stable throughout the task. If wording does not make it clear whether images should be processed independently or jointly, the Skill asks before making a request rather than guessing.

The Skill does not silently truncate inputs or switch from joint reference to independent editing when a request is unsupported or exceeds a limit.

## Command

```text
python <skill-directory>/scripts/generate_image.py \
  [--input IMAGE ...] \
  --prompt "A red apple on a white table, studio photograph, no text" \
  [--out FILE ... | --out-dir DIRECTORY] \
  [--operation generate|edit|batch|reference] \
  --size 1024x1024 \
  --quality medium
```

`--operation` is used by the Skill to pass an explicit execution plan. When calling the script directly, no-input and single-input legacy defaults are allowed; multiple input images must explicitly choose `batch` or `reference`.

Examples:

```text
# Pure generation
python <skill-directory>/scripts/generate_image.py \
  --prompt "生成一只兔子" \
  --out output/imagegen/rabbit.png

# Single-image editing
python <skill-directory>/scripts/generate_image.py \
  --operation edit \
  --input input/chick.png \
  --prompt "把小鸡换成大公鸡，保持背景和构图" \
  --out output/imagegen/rooster.png

# Independent batch editing
python <skill-directory>/scripts/generate_image.py \
  --operation batch \
  --input input/a.png \
  --input input/b.png \
  --prompt "把图中的鸡换成大公鸡" \
  --out-dir output/imagegen/edited

# Joint reference, if supported by the configured service
python <skill-directory>/scripts/generate_image.py \
  --operation reference \
  --input input/a.png \
  --input input/b.png \
  --prompt "参考图1和图2，生成一张它们在同一个院子里的合影" \
  --out output/imagegen/combined.png
```

## Input and output rules

- At most 4 input images and 4 final output images are accepted per task.
- A request over either limit is rejected before any API request is made.
- Supported input formats are determined by the actual service contract; the first implementation validates common PNG, JPEG, and WEBP signatures and extensions.
- Batch editing maps inputs to outputs in order: input 1 to output 1, input 2 to output 2, and so on.
- Multiple `--out` paths must match the number of batch inputs.
- `--out` and `--out-dir` are mutually exclusive.
- Multiple inputs with only one output path are rejected for batch editing to prevent accidental overwrites.
- Existing explicitly named output files are not overwritten without `--force`.
- Automatically generated names avoid existing files by adding a numeric suffix.
- All image requests execute serially; only one request is in flight at a time.
- Multiple generated outputs are requested one at a time with `n=1` to support providers that do not implement batched `n` responses.
- Image API requests are never retried automatically because a timeout, HTTP error, or malformed response may occur after the provider has already processed and charged the request.
- Failures report the affected input and warn that the request may have been charged, without exposing credentials.

## Output location and filenames

When the user specifies a file or directory, the Skill uses that location. Relative paths are resolved from the current project directory, not from the installed Skill directory.

When no location is specified, outputs go to:

```text
output/imagegen/
```

The directory is created automatically when needed. Default names are:

- Pure generation: `imagegen.png`;
- Single-image or batch editing: `<input-stem>-edited.png`;
- Joint reference: `imagegen.png`;
- Multiple variants: repeat `--out` to explicitly provide each output filename.

Default names never include the full prompt, which avoids invalid, oversized, or sensitive filenames. All output files are written through a temporary file and atomically replaced only after the result has been received.

## API compatibility

The configured service must support the operations the user requests:

- Pure generation through the compatible Images API;
- Image editing through its editing endpoint and multipart file upload;
- Joint reference only if the service accepts multiple image files in one request;
- A response containing `b64_json` is preferred; URL responses may depend on the service implementation.

An OpenAI-compatible base URL may support generation but not editing or multiple-image reference. In that case the Skill returns a clear capability error and does not silently send a different kind of request.

## Requirements

- Python 3.10 or newer
- `openai>=2,<3`
- An OpenAI-compatible Images API that supports the configured model and requested operation
