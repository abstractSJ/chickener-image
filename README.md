# Chickener Image

A Codex skill that generates raster images through a user-configured OpenAI-compatible Images API using the official OpenAI Python SDK.

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

## Requirements

- Python 3.10 or newer
- `openai>=2,<3`
- An OpenAI-compatible Images API that supports the configured model
