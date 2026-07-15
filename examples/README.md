# Examples

Runnable scripts that exercise Octopoda end to end. Install first:

```bash
pip install octopoda           # core
pip install octopoda[ai]       # + local semantic search (for search_test.py)
```

Most scripts run fully **local** with no account. Scripts that show the cloud
dashboard read `OCTOPODA_API_KEY` from your environment (get a free key at
[octopodas.com](https://octopodas.com)); without one they fall back to local SQLite.

## Start here

| Script | What it shows |
|--------|---------------|
| [`first_five_minutes.py`](first_five_minutes.py) | Guided first run — write, recall, and watch it appear on the dashboard |
| [`local_only.py`](local_only.py) | Fully local usage with no account or API key |
| [`search_test.py`](search_test.py) | Semantic recall (`recall_similar`) — needs the `[ai]` extra locally |

## Core features

| Script | What it shows |
|--------|---------------|
| [`loop_detection_demo.py`](loop_detection_demo.py) | The loop detector catching a stuck agent |
| [`knowledge_repair_demo.py`](knowledge_repair_demo.py) | Correcting and versioning a memory over time |
| [`self_debugging_demo.py`](self_debugging_demo.py) | An agent using its audit trail to explain its own behaviour |
| [`features_test.py`](features_test.py) | A tour across memory, goals, snapshots, and messaging |
| [`continuous_agent_test.py`](continuous_agent_test.py) | A long-running agent writing continuously |
| [`real_agent_test.py`](real_agent_test.py) | An end-to-end agent workflow |

## Framework & model demos

| Script | What it shows |
|--------|---------------|
| [`framework_comparison_demo.py`](framework_comparison_demo.py) | The same memory across LangChain / CrewAI / AutoGen / OpenAI Agents |
| [`model_debate_demo.py`](model_debate_demo.py) | Multiple agents sharing memory through a debate |
| [`model_showdown_demo.py`](model_showdown_demo.py) | Comparing models against shared memory |

Run any of them directly:

```bash
python examples/first_five_minutes.py
```
