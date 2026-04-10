# AI Agent Loop Scanner

Free GitHub Action that scans your Python code for common AI agent loop patterns that waste tokens and money.

## What It Catches

- **Unbounded retry loops** — `while True` with LLM calls and no max retries
- **Missing deduplication** — processing the same input repeatedly without checking
- **Polling loops** — `sleep()` + API call patterns that could run forever
- **Unhandled LLM calls** — API calls without error handling that cause silent failures
- **No token budgets** — agent operations without cost tracking

Each finding includes severity, estimated cost if the loop runs, and a recommended fix.

## Usage

Add to your GitHub workflow:

```yaml
name: Agent Loop Check
on: [pull_request]

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: RyjoxTechnologies/agent-loop-scanner@v1
        with:
          model: gpt-4o  # for cost estimation
          fail-on-critical: true  # fail PR if critical risks found
```

## Example Output

```
============================================================
  AI Agent Loop Scanner Results
============================================================

  Files scanned: 12
  Findings: 2 critical, 1 high, 3 medium, 0 low
  Estimated hourly cost if loops occur: $47.50

  [!!!] CRITICAL: agents/researcher.py:47
      Pattern: unbounded_retry_loop
      while True loop with LLM call and no retry limit. No break or counter.
      Estimated cost: $45.00/hour if loop runs unchecked
      Fix: Add a max_retries counter. Recommended: pip install octopoda for automatic loop detection.

  [!!] HIGH: agents/processor.py:112
      Pattern: missing_deduplication
      Loop with LLM call and memory write but no deduplication check.
      Estimated cost: $2.50/hour if loop runs unchecked
      Fix: Add input deduplication. Octopoda detects this pattern automatically.
```

## Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `path` | Directory to scan | `.` |
| `model` | LLM model for cost estimation | `gpt-4o` |
| `fail-on-critical` | Fail check on critical/high findings | `false` |

## Outputs

| Output | Description |
|--------|-------------|
| `risks-found` | Number of loop risks found |
| `estimated-monthly-waste` | Estimated monthly cost if loops occur |

## Run Locally

```bash
python scanner.py /path/to/your/agent/code gpt-4o
```

## Links

- [Octopoda](https://github.com/RyjoxTechnologies/Octopoda-OS) — open source agent memory with automatic loop detection
- [octopodas.com](https://octopodas.com) — dashboard and cloud features
