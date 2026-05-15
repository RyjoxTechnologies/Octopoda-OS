# Loop Intelligence v2 — Build Plan

**Status:** Draft, ready to implement
**Owner:** Joe + Ryan
**Build estimate:** 2.5–3 weeks to full ship, 1 week to "sleep insurance" MVP
**Last updated:** 2026-04-24

---

## TL;DR

Turn the current Loop Intelligence tab from a generic alerts list into **the first agent loop tool that a serious engineer would actually trust.** Three pillars:

1. **Sleep insurance.** Catch loops early, pause them, roll back the damage, notify the dev — with real numbers, not projections.
2. **Dev workflow.** Loop detection becomes part of building agents — test suites, deploy regression, prompt fingerprinting, auto-fix suggestions, shareable traces.
3. **Scientific accuracy.** Every alert is traceable to explicit rules, every threshold is statistically backed, precision/recall are published on the tab itself.

No vapor. Every feature below is backed by endpoints that already exist or need <1 day to build. Every claim is provable in a 30-second demo.

---

## The thesis

Every observability tool (LangSmith, Helicone, Datadog, Sentry) can tell you **after** something went wrong. None of them can:

- Catch loops at iteration 2 using embedding similarity across memory writes
- Pause the agent mid-loop
- Roll back the damage the loop did
- Detect loops where every API call returned 200 but the agent wasn't actually progressing
- Show the exact rule that fired, with the raw events that matched

**Octopoda can do all five, because Octopoda sits between the agent and its memory.** That's the defensible position. This plan cashes it in.

---

## The scientific accuracy foundation

These aren't nice-to-haves. They're how the system stays credible.

1. **Rule-based classification only.** No LLMs in the detection path. LLMs hallucinate; rules are inspectable, unit-testable, versionable.
2. **Multi-signal agreement.** No alert fires on one signal. Every classification requires ≥2 independent signals to agree.
3. **Confidence levels, never binary flags.** Every alert shows `high`, `medium`, or `low`. Low-confidence events are logged but do not notify.
4. **Ground-truth test corpus.** 150–200 labeled examples, dual-reviewed, any disagreement discarded. Every rule change must pass the corpus before ship.
5. **Shadow mode.** New rules run silently for 7–14 days. We review would-be alerts manually. Ship only when FP rate is under target.
6. **Published accuracy.** On the tab: last-30-day precision, recall, and false-positive rate per loop type. If we're wrong, users see it first.
7. **Per-alert explainability.** Every alert has a "Why did this fire?" expander showing the exact rule version, events matched, similarity values.
8. **Honest unknown states.** "Unknown loop pattern" is a valid classification. We never force a wrong label.
9. **Feedback loop.** Every alert has "This was wrong" + type override. Feeds back into rule tuning.
10. **Versioned rules + regression tests.** Every rule change runs against the test corpus; regressions block ship.
11. **Calibrated confidence.** Rule with P<0.70 on corpus doesn't ship. 0.70–0.85 → low. 0.85–0.95 → medium. ≥0.95 → high.
12. **Adversarial red-teaming.** Before any rule is called robust, someone writes an agent that tries to fool it. Patch, repeat.

---

## Feature set

### Tier 1 — Sleep Insurance (Week 1)

These are the unambiguously-useful features. Build these first.

#### 1.1 Real running cost per loop
Live dollar counter on every active loop card, updating every 10 seconds. Sum of actual LLM spend scoped to the loop window, attributed via correlation IDs.

- **Data:** `/v1/agents/{id}/cost` + audit-v2 correlation IDs
- **Shown as:** `$0.47 spent · at current rate: $6.80/hr` (rate clearly labeled as extrapolation)
- **Accuracy:** only count LLM calls with confirmed correlation ID; time-window-only cost is labeled "≥" to signal lower bound

#### 1.2 One-click Pause
Red button, primary action on every running-loop card.

- **Data:** `POST /v1/brain/pause/{agent_id}` (exists)
- **Verification:** poll `/v1/brain/status` after click; UI must confirm `paused=true` within 3 seconds or show error

#### 1.3 Restore to pre-loop snapshot
The killer feature. One click rewinds agent memory to before the loop started.

- **Data:** `/v1/agents/{id}/snapshots` + `/v1/agents/{id}/restore` (both live)
- **Atomic flow:** pause → snapshot current state (`pre_restore_<ts>`) → restore → resume
- **Pre-restore diff preview** shows: N keys will be deleted, M keys reverted, K keys unchanged. User can uncheck any.
- **5-minute undo window** after restore (the `pre_restore_*` snapshot is auto-restorable)

#### 1.4 Cost-budget circuit breaker
Auto-pause any agent whose spend exceeds a threshold.

- **Data:** streaming LLM cost, rolling 60s window
- **Rule:** sustained spend ≥ threshold for ≥30 seconds → pause
- **Default:** $0.50/min (calibrated against 95th percentile of tenant spend over 30 days before enabling)
- **User config:** per-tenant override via Settings

#### 1.5 Notifications
Email, Slack webhook, Discord webhook.

- **Email:** via existing Resend integration
- **Triggers:** circuit-breaker fires, `high`-confidence loop detected, sustained stealth loop, daily digest (opt-in)
- **Rate limit:** max 1 notification per (agent, loop_type) per hour
- **Content:** exact rule that fired + confidence + link to alert + quick-pause action

---

### Tier 2 — Detection Upgrades (Week 1–2)

Make detection genuinely better than frequency-counting.

#### 2.1 Early detection via embedding similarity
Flag forming loops at iteration 2.

- **Data:** existing `nodes` embeddings (pgvector)
- **Rule:** cosine similarity between write N and writes N-1, N-2 (same agent, same key or same prefix). `high` if both pairs ≥ 0.92. `medium` if one pair ≥ 0.92 and one ≥ 0.80. `low` if ≥ 0.80.
- **Excludes:** `runtime:*`, `snapshot:*`, `checkpoint:*` keys

#### 2.2 Basic loop types (the 4 highest-signal, built first)
Strict rule-based classifiers. All conditions must hold.

| Type | Rules (all required) |
|---|---|
| **Retry loop** | ≥3 consecutive identical tool calls AND ≥2 returned HTTP 4xx/5xx AND agent retried after each |
| **Polling loop** | ≥3 identical tool calls AND all returned 2xx AND intervals within 10% AND results ≥0.9 similar |
| **Decision oscillation** | ≥3 `log_decision` events AND alternating between 2 values AND same decision key |
| **Cost-inflation loop** | ≥3 LLM calls AND model tier increases across calls AND agent context unchanged |

Remaining 4 basic types (self-correction, ping-pong, tool non-determinism, recall-write) ship in Week 2.

#### 2.3 Memory writes list with checkbox delete
List every key the loop wrote, with `+` for new keys and `~` for modified. Checkbox per row, bulk delete.

- **Data:** timeline API filtered to loop window + agent_id
- **New endpoint:** `DELETE /v1/agents/{id}/memory/{key}?purge=true` (~30 min to build, already planned)
- **Delete confirmation:** required, shows count

#### 2.4 Raw event trace
Monospace terminal-style log of every event in the loop window.

- **Data:** existing timeline API + LLM hook log + decision log
- **Format:** timestamp, event_type, agent_id, full payload
- **Filterable:** by event type, key prefix, LLM call only
- **Exportable:** JSON download

---

### Tier 3 — Dev Workflow Features (Week 2)

These transform loop detection from "alert tool" to "part of how I build agents."

#### 3.1 Loop → reproducible test case
Every detected loop saved as a replayable scenario.

- **Data stored:** trace, memory state snapshot at loop start, captured tool responses, prompts
- **Action:** "Run loop suite" button on the tab — re-runs the agent against stored tool responses deterministically
- **New table:** `loop_test_cases (id, tenant_id, agent_id, loop_type, captured_at, trace_blob, memory_blob, tool_responses_blob, pass_status)`
- **New endpoint:** `POST /v1/agents/{id}/loop-tests/run`
- **Dev benefit:** regression protection. Change your prompt, click Run Suite, know if loops came back.

#### 3.2 Deploy-aware regression detection
Tag every memory write and LLM call with a `deployment_id`.

- **Data change:** add `deployment_id VARCHAR(64)` column to events tables. Backfill with `unknown`.
- **Source:** env var `OCTOPODA_DEPLOYMENT_ID` at agent start (user-supplied, or hash of prompt file, or git SHA)
- **UI:** line chart of loops/day colored by deploy. Vertical lines at deploy boundaries. Click a spike → see what changed.
- **Dev benefit:** git-blame for agents.

#### 3.3 Prompt fingerprinting (pre-flight)
Before running an agent with a new prompt, compare its embedding against embeddings of prompts from past loops.

- **Data:** store prompt embeddings when loops are logged
- **Action:** on agent start (via new hook in AgentRuntime.__init__), compute similarity to stored loop-prompts. If max similarity > 0.85, log a warning event viewable on the tab.
- **Dev benefit:** pre-crime — warn before the loop happens, based on this agent's own history.

#### 3.4 Surgical auto-fix suggestions
For the 4 highest-signal loop types with `high` confidence, offer exact code/config diffs.

- **Data:** per-type fix template, hard-coded (not LLM-generated)
- **Shown as:** copy-paste ready code block + explanation
- **Rule:** only shown when classification confidence is `high` AND the fix matches the specific matched rule
- **Dev benefit:** immediately actionable. No googling.

Example retry loop fix:
```python
from functools import wraps

def circuit_breaker(max_failures=3, reset_after=60):
    def deco(fn):
        fails, last_fail = 0, 0
        @wraps(fn)
        def wrapped(*a, **kw):
            nonlocal fails, last_fail
            if fails >= max_failures and time.time() - last_fail < reset_after:
                raise CircuitOpen(f"{fn.__name__} circuit-broken")
            try:
                result = fn(*a, **kw)
                fails = 0
                return result
            except Exception:
                fails += 1
                last_fail = time.time()
                raise
        return wrapped
    return deco

@circuit_breaker(max_failures=3, reset_after=60)
def call_crm(customer_id): ...
```

#### 3.5 Share-a-loop (exportable trace URL)
Every detected loop gets a shareable URL (read-only, auth-protected).

- **New endpoint:** `GET /v1/loops/{loop_id}/share` — returns a signed URL
- **Dashboard route:** `/loops/shared/{token}` — renders the detail view
- **Content shared:** full trace, memory state, LLM calls, cost, classification
- **Dev benefit:** debugging is now collaborative. Paste the URL in Slack.

#### 3.6 Per-prompt cost attribution
Break down agent cost by prompt template, not just by agent.

- **Data change:** tag LLM calls with `prompt_template_id` (deterministic hash of system prompt)
- **UI:** "Top 10 expensive prompts this week" leaderboard on the cost panel
- **Dev benefit:** see which prompts burn tokens. Optimize the expensive ones.

---

### Tier 4 — Advanced Detection (Week 2–3)

The 8 advanced loop types + stealth detection + historical pattern matching. These are what take the product from "good" to "defensibly best-in-market."

#### 4.1 The 4 remaining basic types

| Type | Rules (all required) |
|---|---|
| **Self-correction** | ≥3 LLM responses AND each starts with revision cue (`actually`, `wait`, `reconsider`, `let me re-`) AND each produces a revised version of prior write |
| **Ping-pong (cross-agent)** | Two agents AND alternating writes to same shared-memory key AND ≥4 alternations |
| **Tool non-determinism** | Same tool + same input ≥3 times AND outputs differ (similarity <0.9) AND agent kept re-querying |
| **Recall-write** | Read key X AND write key X with similarity ≥0.85 to read AND ≥3 cycles |

#### 4.2 Convergent hallucination loop
Agent hallucinates a fact → stores it → recalls it as truth → builds on it.

- **Rule:** track "grounded" writes (traceable to tool output or user input via correlation) vs "generated" writes. Flag when generated-to-grounded ratio spikes in a window (>70% generated over ≥5 writes).
- **Accuracy note:** requires tool/input hooks that emit source attribution. audit-v2's correlation IDs provide this.

#### 4.3 Reflection loop
Agent produces output → reviews → revises → reviews → revises. Common in CrewAI reflection mode.

- **Rule:** same artifact ID revised ≥3 times AND each revision's similarity to prior ≥0.85. Requires framework hooks that emit revision events.

#### 4.4 Plan-replan loop
Plans being replaced rather than extended.

- **Rule:** plan objects (tracked via `log_decision` with `type="plan"`) replaced ≥3 times AND no leaf actions (non-planning events) executed between replans.

#### 4.5 Tool selection oscillation
Different tools, same unsolved underlying task.

- **Rule:** ≥3 distinct tool calls for the same task (correlation ID) without a success signal.

#### 4.6 Clarification loop
Agent keeps asking for clarification, rephrased.

- **Rule:** agent outputs classified as questions (ends with `?` + starts with interrogative) AND ≥3 recent outputs with pairwise similarity ≥0.75.

#### 4.7 Subgoal proliferation
Plan tree depth grows without leaf execution.

- **Rule:** plan tree depth ≥4 AND zero leaf-action events.

#### 4.8 Consensus failure loop (multi-agent)
Repeated vote-propose-vote without resolution.

- **Rule:** ≥3 proposal events on same topic AND each followed by failed-consensus event.

#### 4.9 Cross-session contamination
Session A's write → Session B reads → writes → Session C reads B's writes. Loop across sessions.

- **Rule:** chain of write → cross-session-read → write events on same key family, with semantic drift measured across the chain ≥0.2.

#### 4.10 Stealth loops (success-shaped loops)
The big one. Agent succeeds at every call but isn't progressing toward its goal.

- **Rules (ALL 5 must hold):**
  1. Agent has a goal set via `/v1/brain/goal`
  2. Goal drift change < 5% across last 10 iterations
  3. Embedding entropy (Shannon) of last 10 writes below calibrated threshold
  4. ≥60% of recent decisions in the same decision class
  5. Sustained for ≥5 minutes or 10 iterations
- **Critical:** shadow mode for 14 days, no exceptions. FP rate must be <5% before enable.
- **Why novel:** only Octopoda can see drift + entropy + decisions together. Other tools see API 200s.

#### 4.11 Historical pattern matching
When a loop fires, show prior occurrences on the same signature.

- **Data:** `loop_events` table logs every detected loop (agent_id, loop_type, keys_affected_prefix, prompt_hash)
- **UI:** on any alert, show "This agent has looped on this pattern N times before" + list of prior occurrences + "Mark as fixed" button (user confirmation that the fix held)

---

## UI Design

### Top status strip (replaces 10 "HEALTHY" cards)

```
10 agents  ·  2 looping  ·  $4.23 spent on active loops  ·  FP rate (30d): 2.1%
```

Empty state:
```
10 agents healthy  ·  Last loop caught 4h ago ($0.80 before stop)  ·  FP rate (30d): 2.1%
```

**Publish the FP rate publicly.** If it's bad, users see. Commits us to honesty.

### Active Loop card (when something's burning)

```
┌──────────────────────────────────────────────────────────┐
│ customer-support                     RETRY LOOP   [high] │
│ Running 4m 23s · iteration 7 · confidence 92%            │
│                                                          │
│ $0.47 spent                        ← live, ticks up      │
│ At current rate: $6.80/hr          ← clearly extrapolated│
│                                                          │
│ Rule match (RetryLoop v2.1):                             │
│   ✓ Same tool call 7 times                               │
│   ✓ 4 returned HTTP 429                                  │
│   ✓ Agent retried after each                             │
│                                                          │
│ Suggested fix:                                           │
│   Tool is rate-limited. Add circuit breaker.             │
│   [View fix code] [Apply fix]                            │
│                                                          │
│ [ Pause Agent ]  [ Restore Pre-Loop ]  [ Inspect ]       │
│                                                          │
│ [Why did this fire?] [This was wrong]                    │
└──────────────────────────────────────────────────────────┘
```

Color coding by **real cost**, not "severity":
- Green: under $0.10
- Yellow: $0.10 – $1.00
- Red: $1 – $5
- Pulsing red: over $5 (act now)

### Recently Caught section

Compact cards below active loops:
```
✓ data-pipeline — ping-pong loop, stopped at $0.12 · 2h ago · [Replay] [Share]
✓ code-reviewer — repeat loop, paused at $0.08 · yesterday · [Replay] [Share]
```

### Detail view (click Inspect on any card)

Three-pane slide-over:

**Left: raw event trace** — monospace, terminal-style, full payloads, filterable, exportable as JSON.

**Right: memory affected** — list of keys with checkboxes, `+` for new and `~` for modified, bulk delete, diff viewer per key.

**Bottom: actions bar** — Pause (if running), Restore Pre-Loop (with diff preview), Delete Selected, Export Trace, Share URL, Run loop as test.

### Removed from the current tab

- The 10 agent health cards at top (replaced by one-line strip)
- Latency / Errors / Crashes sub-tabs (belong on a separate Operations page)
- Generic "why this matters" bullets (replaced by rule-match display)

---

## Accuracy validation plan

### Test corpus (non-negotiable foundation)

Build 150–200 labeled examples:
- 100 real loops from production (anonymized, covering every type)
- 50 near-misses (legitimate bulk updates, intentional polling, etc.)
- 50 clean operations

Each example dual-reviewed. Only include examples where both reviewers agreed on classification.

Store under `tests/loop_corpus/` in the repo, versioned.

### Shadow mode infrastructure

New table `loop_shadow_events` captures rule-matches that would fire but don't. Manual review dashboard at `/admin/shadow-review` (admin-only).

New rule lifecycle:
1. Land in shadow mode (7 days for simple rules, 14 days for stealth)
2. Manual review of all shadow-fires
3. Compute precision and recall against corpus
4. If target met → promote to live
5. If target missed → tune or revert

### Published metrics

Visible on Loop Intelligence tab itself:

- Alerts fired (last 30d) — total, per type
- FP count (user-dismissed + marked-wrong)
- FP rate per type
- Mean time to detect per type (seconds from loop start to alert)

### Feedback loop

- "This was wrong" button on every alert — captures type, sends to `loop_feedback` table
- Weekly cron: aggregate, surface to admin for rule tuning
- New FP patterns added to test corpus

### Regression testing

- CI step: run new rule version against corpus
- Any regression vs. prior version blocks merge
- Versioned rules: `RetryLoop v2.1 → v2.2 (2026-05-03)` with changelog

---

## Build order (concrete, estimated)

### Week 1 — Sleep Insurance MVP (Ryan backend + Lovable UI)

**Backend (~3 days):**
- [ ] Memory-key delete endpoint `DELETE /v1/agents/{id}/memory/{key}?purge=true`
- [ ] Restore-with-pause-and-preview flow (wrap existing `/restore`)
- [ ] Cost-budget circuit breaker middleware + config
- [ ] Notifications dispatcher (Resend email + Slack webhook + Discord webhook)
- [ ] Early detection via embedding similarity (add to existing loop detector)

**Lovable UI (~3 days):**
- [ ] Strip the 10 health cards → one-line status strip
- [ ] Rebuild alert card with cost hero + 3-button action row + rule-match display
- [ ] Build three-pane detail view (trace / memory / actions)
- [ ] Wire live $ counter (10s poll)
- [ ] Remove Latency / Errors / Crashes sub-tabs
- [ ] Add "Why did this fire?" expander
- [ ] Add "This was wrong" feedback button
- [ ] Add Settings panel for circuit breaker threshold + notification channels

**Ship target:** End of week 1. Every active user gets a substantially better tab.

### Week 2 — Detection upgrades + dev workflow

**Backend (~5 days):**
- [ ] 4 remaining basic loop types (self-correction, ping-pong, tool non-determinism, recall-write)
- [ ] Deploy-ID column + `OCTOPODA_DEPLOYMENT_ID` env var support
- [ ] `loop_test_cases` table + replay harness + `POST /loop-tests/run` endpoint
- [ ] Prompt fingerprinting hook in AgentRuntime + similarity check on start
- [ ] Per-type hard-coded fix templates (4 highest-signal types)
- [ ] Share-a-loop signed URL + `/loops/shared/{token}` page
- [ ] Prompt-template-id tagging on LLM calls + aggregation endpoint

**Lovable UI (~3 days):**
- [ ] Loop-type chips on alerts with color coding
- [ ] Deploy-regression line chart on tab
- [ ] "Run loop suite" button + results panel
- [ ] "Share this loop" button → copyable URL
- [ ] Per-prompt cost panel
- [ ] Fix-code diff preview modal + "Apply fix" one-click

**Ship target:** End of week 2. Four basic loop types live with confidence, dev workflow features available.

### Week 3 — Advanced detection + validation

**Backend (~5 days):**
- [ ] Advanced loop types 4.2–4.9 (plan-replan, reflection, tool oscillation, clarification, subgoal, consensus, cross-session, convergent hallucination)
- [ ] Stealth loop detector (rule-set 4.10) in shadow mode only
- [ ] `loop_events` table + historical pattern matcher
- [ ] Test corpus scaffolding + first 50 labeled examples
- [ ] Shadow mode infra + admin review dashboard
- [ ] Published metrics endpoint + dashboard widget

**Lovable UI (~2 days):**
- [ ] Historical patterns panel on each alert
- [ ] Published metrics display on tab header
- [ ] Admin-only shadow-review page

**Ship target:** End of week 3. Full 16-type system live with accuracy infrastructure.

### Ongoing (weeks 4+)

- [ ] Complete test corpus (150–200 examples)
- [ ] Stealth loop graduation from shadow to live (after 14-day shadow period)
- [ ] Weekly rule-tuning based on feedback
- [ ] Adversarial red-teaming rounds

---

## Success criteria

How we know this is working:

1. **Dev-facing:**
   - A dev on the Pro tier catches and stops a loop in under 60 seconds from first alert
   - Median detection latency ≤ iteration 3
   - ≥80% of detected loops have a pre-loop snapshot available for restore
   - At least one paid customer testimonial referencing a saved incident

2. **Product accuracy targets (from test corpus):**
   | Loop type | Precision | Recall |
   |---|---|---|
   | Retry | ≥95% | ≥90% |
   | Polling | ≥90% | ≥85% |
   | Decision oscillation | ≥95% | ≥90% |
   | Cost-inflation | ≥95% | ≥90% |
   | Self-correction | ≥85% | ≥75% |
   | Ping-pong | ≥95% | ≥85% |
   | Tool non-determinism | ≥90% | ≥80% |
   | Recall-write | ≥85% | ≥75% |
   | Reflection | ≥85% | ≥75% |
   | Plan-replan | ≥85% | ≥75% |
   | Tool oscillation | ≥85% | ≥75% |
   | Clarification | ≥80% | ≥70% |
   | Subgoal proliferation | ≥85% | ≥75% |
   | Consensus failure | ≥90% | ≥80% |
   | Cross-session | ≥80% | ≥70% |
   | Convergent hallucination | ≥75% | ≥60% |
   | Stealth | ≥75% | ≥60% |

3. **Business:**
   - Loop Intelligence becomes a top-3 most-visited tab in dashboard analytics
   - Measurable drop in cost-blowup support tickets
   - Referenced in ≥1 inbound VC conversation as a differentiator

---

## What we will not claim

- We do not claim to "predict" loops. We detect patterns we can measure.
- We do not use "AI-powered" in marketing. Rules are rule-based and visible.
- We do not show "money saved" — we show money spent on loops that were stopped.
- We do not claim 100% detection. We publish our false-negative rate.
- We do not show high confidence without evidence. A single-signal match is never above `medium`.
- We do not use LLM-generated prose for classification. Only for fix suggestions, from vetted templates.

---

## Endpoint & data dependency inventory

### Already exists (verified in prod code)
- `POST /v1/agents/{id}/snapshot` → [runtime.py:1600](synrix_runtime/api/runtime.py:1600)
- `POST /v1/agents/{id}/restore` → [runtime.py:1642](synrix_runtime/api/runtime.py:1642)
- `GET /v1/agents/{id}/snapshots`
- `DELETE /v1/agents/{id}/snapshots/{label}`
- `GET /v1/agents/{id}/timeline`
- `GET /v1/agents/{id}/checkpoints`
- `GET /v1/agents/{id}/cost`
- `GET /v1/brain/cost-summary`
- `POST /v1/brain/pause/{id}`
- `POST /v1/brain/resume/{id}`
- `GET /v1/brain/drift/{id}`
- `POST /v1/brain/goal/{id}`
- `GET /v1/brain/conflicts/{id}`
- `POST /v1/agents/{id}/recover` (needs audit — may want to remove or explain UI)
- `DELETE /v1/agents/{id}?purge=true` (agent hard delete, from commit `0cb147c`)

### Needs building (~1 day each unless noted)
- `DELETE /v1/agents/{id}/memory/{key}?purge=true` (~30 min — already planned)
- `POST /v1/agents/{id}/loop-tests/run` (new, ~1 day)
- `GET /v1/loops/{loop_id}/share` (signed URL, ~4 hours)
- `GET /v1/loops/metrics/published` (FP/precision per-type, ~4 hours)
- Notification dispatcher (~1 day for email + Slack + Discord)
- Circuit breaker middleware (~1 day)

### Data schema changes
- Add `deployment_id VARCHAR(64)` to event tables (memory writes, LLM calls, decisions)
- Add `prompt_template_id VARCHAR(64)` to LLM call log
- New table `loop_events` (detected loops + signatures)
- New table `loop_test_cases` (saved scenarios)
- New table `loop_shadow_events` (would-fire-but-silent)
- New table `loop_feedback` (user false-positive reports)

### Feature flag
- `OCTOPODA_LOOP_INTEL_V2` env var. Default off for first week after ship. Per-tenant override via Settings (admin). When enabled, new tab UI + new detection rules. When disabled, fall back to current tab.

---

## The pitch (one paragraph, for the deck or a cold email)

> Octopoda Loop Intelligence v2 is the first agent monitoring tool where every alert is traceable to explicit rules, every number is verifiable, and we publish our own accuracy. We catch loops at iteration 2 via embedding similarity, attribute real cost in dollars not projections, pause the agent mid-loop, roll back the damage to a pre-loop snapshot, and classify into 16 loop types — including loops where every API call returned 200 but the agent wasn't actually progressing, which no other tool can detect because they don't own the memory layer. Every alert answers "why did this fire" with the exact rule version and matched events. If we're wrong, you see our false-positive rate on the same page. That's why a serious engineer trusts it.

---

## Open questions (decide before Week 1 starts)

1. **Feature flag scope.** Per-tenant toggle or global? Recommend per-tenant, default off for first 2 weeks, opt-in for power users.
2. **Who owns the test corpus?** Joe labels? Ryan labels? Contractor? Recommend Joe + Ryan dual-label the first 50 together to establish calibration.
3. **Circuit breaker default.** Run the 30-day 95th-percentile measurement now so we have data when Week 1 ships. $0.50/min is a guess until then.
4. **Shadow-mode duration for stealth loops.** 14 days or longer? Recommend 21 days given the complexity and the consequences of false positives.
5. **Crash Recovery section on the Recovery tab.** Fix with clear explanation or remove entirely? Out of scope for this plan but should be decided in parallel.

---

## Definition of Done

- [ ] All 16 loop types implemented with rule-based classifiers
- [ ] Test corpus of ≥150 labeled examples, dual-reviewed
- [ ] Every rule passes precision/recall targets on corpus
- [ ] Shadow mode live; first 4 rules graduated to production
- [ ] Published metrics visible on tab
- [ ] "Why did this fire" expander on every alert
- [ ] Restore-to-pre-loop works on one-click with diff preview
- [ ] Circuit breaker live with default threshold
- [ ] Email + Slack + Discord notifications functional
- [ ] Share-a-loop URL generates + renders correctly
- [ ] Loop-as-test-case runs against a prompt change
- [ ] Deploy-regression chart shows meaningful data
- [ ] At least one internal dogfood incident where Loop Intelligence caught a real issue and the restore button fixed it
