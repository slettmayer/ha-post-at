# Contributing

Issues and pull requests are welcome. Please open an issue before submitting a
large change.

## Development

```bash
uv venv --python 3.14
uv pip install -r requirements_test.txt -r requirements_lint.txt
```

## Checks

The same four jobs CI runs:

```bash
python -m pytest tests/ -q     # unit tests
ruff check .                   # lint
ruff format . --check          # format
```

Hassfest and HACS validation run in CI only.

## Ground rules

- **Never persist the account password.** The config flow uses it once and
  discards it. Only the B2C SSO cookie is stored.
- **Never request or expose address fields.** `recipientAddress` is the user's
  own name and street; it must not reach the state machine, the recorder or a
  diagnostics download.
- **Tests must not contain real data.** No real tracking numbers, names or
  addresses in fixtures.
- **An unmapped tracking state reports `unknown`,** never a guess.
