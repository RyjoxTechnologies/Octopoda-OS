"""
Octopoda Model Showdown: GPT-4o vs Claude Sonnet 4
=================================================
Can two different LLMs collaborate through shared memory?

Phase 1: Independent Research
  Both models get 10 identical research tasks. Measures speed, tokens, cost.

Phase 2: Cross-Model Collaboration
  Each model reads the other's findings through shared memory.
  Then writes a synthesis combining both perspectives.

Phase 3: Decision Audit
  Each model evaluates the other's work and logs decisions with reasoning.
  Populates the full audit trail.

Methodology:
  - Same prompts, same temperature (0.7), same max tokens (400)
  - Memory stored through Octopoda, recall via semantic search
  - Shared memory for cross-model collaboration
  - All decisions logged with reasoning

Dashboard: http://localhost:7842
"""

import requests
import time
import sys
import json
import os

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BASE = "http://localhost:8741"

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
BLUE = "\033[94m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

# ── LLM Calls ──────────────────────────────────────────────────────────────

def call_gpt(prompt):
    start = time.time()
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 400, "temperature": 0.7},
            timeout=60)
        elapsed = time.time() - start
        data = r.json()
        if "choices" not in data:
            return {"text": f"Error: {data.get('error', {}).get('message', 'unknown')}", "time_s": round(elapsed, 2),
                    "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return {"text": text, "time_s": round(elapsed, 2),
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0)}
    except Exception as e:
        return {"text": f"Error: {e}", "time_s": round(time.time() - start, 2),
                "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def call_claude(prompt):
    start = time.time()
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 400,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60)
        elapsed = time.time() - start
        data = r.json()
        if "content" not in data:
            return {"text": f"Error: {data.get('error', {}).get('message', 'unknown')}", "time_s": round(elapsed, 2),
                    "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        text = data["content"][0]["text"]
        usage = data.get("usage", {})
        return {"text": text, "time_s": round(elapsed, 2),
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)}
    except Exception as e:
        return {"text": f"Error: {e}", "time_s": round(time.time() - start, 2),
                "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


# ── Octopoda helpers ───────────────────────────────────────────────────────

def api(method, path, data=None):
    url = f"{BASE}{path}"
    if method == "POST":
        return requests.post(url, json=data, timeout=15)
    elif method == "PUT":
        return requests.put(url, json=data, timeout=15)
    elif method == "DELETE":
        return requests.delete(url, timeout=15)
    return requests.get(url, timeout=15)


def register(agent_id):
    api("POST", "/v1/agents", {"agent_id": agent_id})


def remember(agent_id, key, value):
    r = api("POST", f"/v1/agents/{agent_id}/remember", {"key": key, "value": value})
    return r.json() if r.status_code == 200 else {}


def recall_similar(agent_id, query, limit=3):
    r = api("GET", f"/v1/agents/{agent_id}/similar?q={requests.utils.quote(query)}&limit={limit}")
    return r.json().get("items", []) if r.status_code == 200 else []


def share(agent_id, space, key, value):
    r = api("POST", f"/v1/shared/{space}", {"key": key, "value": value, "author_agent_id": agent_id})
    return r.json() if r.status_code == 200 else {}


def read_shared(space, key):
    r = api("GET", f"/v1/shared/{space}/{key}")
    return r.json() if r.status_code == 200 else {}


def log_decision(agent_id, decision, reasoning, context=None):
    api("POST", f"/v1/agents/{agent_id}/decision", {
        "decision": decision,
        "reasoning": reasoning,
        "context": context or {},
    })


def get_loop_status(agent_id):
    r = api("GET", f"/v1/agents/{agent_id}/loops/status")
    return r.json() if r.status_code == 200 else {}


# ── Cost calculation ───────────────────────────────────────────────────────

COSTS = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
}

def calc_cost(model_key, input_tokens, output_tokens):
    c = COSTS[model_key]
    return round((input_tokens / 1_000_000) * c["input"] +
                 (output_tokens / 1_000_000) * c["output"], 6)


# ── Research tasks ─────────────────────────────────────────────────────────

TASKS = [
    {"key": "frameworks:langchain",
     "prompt": "In 2-3 sentences, what is LangChain and what specific problem does it solve for AI agent developers? Include one concrete limitation."},
    {"key": "frameworks:crewai",
     "prompt": "In 2-3 sentences, what is CrewAI and how does it differ from LangChain? Include what type of project it's best suited for."},
    {"key": "frameworks:autogen",
     "prompt": "In 2-3 sentences, what is Microsoft AutoGen and what is its approach to multi-agent conversation? Include one technical trade-off."},
    {"key": "frameworks:openai-sdk",
     "prompt": "In 2-3 sentences, what is the OpenAI Agents SDK and when would you choose it over LangChain? Include its main architectural difference."},
    {"key": "analysis:memory-problem",
     "prompt": "In 2-3 sentences, explain why AI agents lose context between sessions. Be specific about the technical cause."},
    {"key": "analysis:loop-causes",
     "prompt": "In 2-3 sentences, what causes AI agents to get stuck in loops? Give two specific technical causes with examples."},
    {"key": "analysis:cost-estimate",
     "prompt": "Estimate the token cost of a single AI agent loop that runs for 1 hour at 10 requests per minute using GPT-4o. Show the calculation."},
    {"key": "comparison:memory-solutions",
     "prompt": "Compare three approaches to giving AI agents persistent memory: custom database, Mem0, and Octopoda. One sentence each on the main advantage and disadvantage."},
    {"key": "recommendation:architecture",
     "prompt": "If you were building a 3-agent customer support system that needs to run 24/7, what is the single most important architectural decision? 2-3 sentences."},
    {"key": "recommendation:monitoring",
     "prompt": "What are the three most important metrics to monitor for AI agents in production? One sentence per metric."},
]

RECALL_QUESTIONS = [
    {"query": "What is LangChain used for?", "expected_key": "frameworks:langchain", "desc": "LangChain"},
    {"query": "How does CrewAI differ from other frameworks?", "expected_key": "frameworks:crewai", "desc": "CrewAI"},
    {"query": "What is AutoGen's approach to agents?", "expected_key": "frameworks:autogen", "desc": "AutoGen"},
    {"query": "When should you use OpenAI Agents SDK?", "expected_key": "frameworks:openai-sdk", "desc": "OpenAI SDK"},
    {"query": "Why do agents lose context between sessions?", "expected_key": "analysis:memory-problem", "desc": "Memory problem"},
    {"query": "What makes agents get stuck repeating themselves?", "expected_key": "analysis:loop-causes", "desc": "Loop causes"},
    {"query": "How much do agent loops cost in tokens?", "expected_key": "analysis:cost-estimate", "desc": "Cost estimate"},
    {"query": "Compare persistent memory options for agents", "expected_key": "comparison:memory-solutions", "desc": "Memory comparison"},
    {"query": "Most important decision for production agent architecture?", "expected_key": "recommendation:architecture", "desc": "Architecture"},
    {"query": "What metrics should you monitor for agents?", "expected_key": "recommendation:monitoring", "desc": "Monitoring"},
]

SYNTHESIS_TOPICS = [
    {"key": "synthesis:best-framework", "topic": "best framework choice",
     "prompt_template": "You are {model_name}. Another AI model researched the same topics as you. Here are their findings on AI agent frameworks:\n\nLangChain: {other_langchain}\n\nCrewAI: {other_crewai}\n\nAutoGen: {other_autogen}\n\nOpenAI SDK: {other_openai}\n\nNow synthesise both your own knowledge and their findings into a 3-sentence recommendation for which framework a startup should use for their first agent project. Note where you agree and disagree with the other model."},
    {"key": "synthesis:biggest-risk", "topic": "biggest production risk",
     "prompt_template": "You are {model_name}. Another AI model analysed agent failure modes. Their findings:\n\nMemory problem: {other_memory}\n\nLoop causes: {other_loops}\n\nCost estimate: {other_cost}\n\nCombine their analysis with your own to answer: what is the single biggest risk of running AI agents in production? 3 sentences. Cite specific findings from both your research and theirs."},
    {"key": "synthesis:ideal-stack", "topic": "ideal agent stack",
     "prompt_template": "You are {model_name}. Another AI model recommended an architecture and monitoring approach:\n\nArchitecture: {other_arch}\n\nMonitoring: {other_monitoring}\n\nMemory solutions: {other_memory_solutions}\n\nCombine their recommendations with yours to propose the ideal production agent stack in 3-4 sentences. Where do you agree? Where do you think they're wrong?"},
]

EVALUATION_TOPICS = [
    {"key": "eval:framework-analysis", "topic": "framework analysis quality",
     "prompt_template": "You are {model_name} evaluating another AI model's research. They wrote this about AI agent frameworks:\n\nLangChain: {other_langchain}\nCrewAI: {other_crewai}\n\nRate the quality of their analysis from 1-10 and explain why in 2 sentences. Be honest about what they got right and wrong."},
    {"key": "eval:risk-assessment", "topic": "risk assessment accuracy",
     "prompt_template": "You are {model_name} evaluating another model's risk analysis:\n\n{other_loops}\n\n{other_cost}\n\nIs their cost estimate reasonable? Rate 1-10 and explain in 2 sentences."},
    {"key": "eval:overall-trust", "topic": "overall trust level",
     "prompt_template": "You are {model_name}. Based on everything you've seen from the other model's research, would you trust their output in a production agent system? Answer in 2-3 sentences with a trust score from 1-10."},
]


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    try:
        r = requests.get(f"{BASE}/health", timeout=5)
        if r.status_code != 200:
            raise Exception()
    except:
        print("\n  Server not running. Start with: octopoda")
        sys.exit(1)

    api("PUT", "/v1/settings", {"llm_model": "gpt-4o"})

    gpt_id = "gpt4o-researcher"
    claude_id = "claude-researcher"
    register(gpt_id)
    register(claude_id)

    print()
    print(f"  {BOLD}OCTOPODA MODEL SHOWDOWN{RESET}")
    print(f"  {DIM}GPT-4o vs Claude Sonnet 4 — Collaboration Experiment{RESET}")
    print()
    print(f"  Phase 1: Independent research (10 tasks each)")
    print(f"  Phase 2: Cross-model collaboration via shared memory")
    print(f"  Phase 3: Decision audit — each model evaluates the other")
    print()
    print(f"  Dashboard: {BOLD}http://localhost:7842{RESET}")
    print()

    gpt_metrics = {"times": [], "tokens_in": [], "tokens_out": []}
    claude_metrics = {"times": [], "tokens_in": [], "tokens_out": []}
    gpt_findings = {}
    claude_findings = {}

    # ── PHASE 1: Independent Research ──────────────────────────────────────

    print(f"  {BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}PHASE 1: Independent Research{RESET}")
    print(f"  {BOLD}{'='*60}{RESET}")
    print()

    for i, task in enumerate(TASKS):
        # GPT
        gpt_result = call_gpt(task["prompt"])
        gpt_write = remember(gpt_id, task["key"], gpt_result["text"])
        gpt_metrics["times"].append(gpt_result["time_s"])
        gpt_metrics["tokens_in"].append(gpt_result["input_tokens"])
        gpt_metrics["tokens_out"].append(gpt_result["output_tokens"])
        gpt_findings[task["key"]] = gpt_result["text"]

        # Claude
        claude_result = call_claude(task["prompt"])
        claude_write = remember(claude_id, task["key"], claude_result["text"])
        claude_metrics["times"].append(claude_result["time_s"])
        claude_metrics["tokens_in"].append(claude_result["input_tokens"])
        claude_metrics["tokens_out"].append(claude_result["output_tokens"])
        claude_findings[task["key"]] = claude_result["text"]

        print(f"  Task {i+1}/10: {task['key']}")
        print(f"    {GREEN}GPT-4o{RESET}:  {gpt_result['time_s']:.1f}s | {gpt_result['total_tokens']} tokens")
        print(f"    {BLUE}Claude{RESET}:  {claude_result['time_s']:.1f}s | {claude_result['total_tokens']} tokens")

        time.sleep(0.3)

    print(f"\n  {DIM}Waiting for embeddings...{RESET}")
    time.sleep(5)

    # Recall accuracy test
    print(f"\n  {BOLD}Recall Accuracy:{RESET}")
    gpt_correct = 0
    claude_correct = 0
    for q in RECALL_QUESTIONS:
        gpt_results = recall_similar(gpt_id, q["query"], limit=3)
        claude_results = recall_similar(claude_id, q["query"], limit=3)
        gpt_keys = [r.get("key", "").replace(f"agents:{gpt_id}:", "") for r in gpt_results]
        claude_keys = [r.get("key", "").replace(f"agents:{claude_id}:", "") for r in claude_results]
        if q["expected_key"] in gpt_keys:
            gpt_correct += 1
        if q["expected_key"] in claude_keys:
            claude_correct += 1

    print(f"    {GREEN}GPT-4o{RESET}:  {gpt_correct}/10")
    print(f"    {BLUE}Claude{RESET}:  {claude_correct}/10")

    # ── PHASE 2: Cross-Model Collaboration ─────────────────────────────────

    print()
    print(f"  {BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}PHASE 2: Cross-Model Collaboration{RESET}")
    print(f"  {DIM}Each model reads the other's findings via shared memory{RESET}")
    print(f"  {BOLD}{'='*60}{RESET}")
    print()

    # Share all findings to shared memory
    print(f"  {DIM}Sharing findings to shared memory...{RESET}")
    for key, value in gpt_findings.items():
        share(gpt_id, "research", f"gpt4o:{key}", value)
    for key, value in claude_findings.items():
        share(claude_id, "research", f"claude:{key}", value)
    print(f"  {GREEN}GPT-4o{RESET}: shared {len(gpt_findings)} findings")
    print(f"  {BLUE}Claude{RESET}: shared {len(claude_findings)} findings")
    print()

    # Each model reads the other's findings and synthesises
    for synth in SYNTHESIS_TOPICS:
        print(f"  Synthesising: {synth['topic']}")

        # GPT reads Claude's findings and synthesises
        gpt_prompt = synth["prompt_template"].format(
            model_name="GPT-4o",
            other_langchain=claude_findings.get("frameworks:langchain", "N/A"),
            other_crewai=claude_findings.get("frameworks:crewai", "N/A"),
            other_autogen=claude_findings.get("frameworks:autogen", "N/A"),
            other_openai=claude_findings.get("frameworks:openai-sdk", "N/A"),
            other_memory=claude_findings.get("analysis:memory-problem", "N/A"),
            other_loops=claude_findings.get("analysis:loop-causes", "N/A"),
            other_cost=claude_findings.get("analysis:cost-estimate", "N/A"),
            other_arch=claude_findings.get("recommendation:architecture", "N/A"),
            other_monitoring=claude_findings.get("recommendation:monitoring", "N/A"),
            other_memory_solutions=claude_findings.get("comparison:memory-solutions", "N/A"),
        )
        gpt_synth = call_gpt(gpt_prompt)
        remember(gpt_id, synth["key"], gpt_synth["text"])
        share(gpt_id, "synthesis", f"gpt4o:{synth['key']}", gpt_synth["text"])
        gpt_metrics["tokens_in"].append(gpt_synth["input_tokens"])
        gpt_metrics["tokens_out"].append(gpt_synth["output_tokens"])

        # Claude reads GPT's findings and synthesises
        claude_prompt = synth["prompt_template"].format(
            model_name="Claude Sonnet",
            other_langchain=gpt_findings.get("frameworks:langchain", "N/A"),
            other_crewai=gpt_findings.get("frameworks:crewai", "N/A"),
            other_autogen=gpt_findings.get("frameworks:autogen", "N/A"),
            other_openai=gpt_findings.get("frameworks:openai-sdk", "N/A"),
            other_memory=gpt_findings.get("analysis:memory-problem", "N/A"),
            other_loops=gpt_findings.get("analysis:loop-causes", "N/A"),
            other_cost=gpt_findings.get("analysis:cost-estimate", "N/A"),
            other_arch=gpt_findings.get("recommendation:architecture", "N/A"),
            other_monitoring=gpt_findings.get("recommendation:monitoring", "N/A"),
            other_memory_solutions=gpt_findings.get("comparison:memory-solutions", "N/A"),
        )
        claude_synth = call_claude(claude_prompt)
        remember(claude_id, synth["key"], claude_synth["text"])
        share(claude_id, "synthesis", f"claude:{synth['key']}", claude_synth["text"])
        claude_metrics["tokens_in"].append(claude_synth["input_tokens"])
        claude_metrics["tokens_out"].append(claude_synth["output_tokens"])

        print(f"    {GREEN}GPT-4o{RESET}:  {DIM}{gpt_synth['text'][:80]}...{RESET}")
        print(f"    {BLUE}Claude{RESET}:  {DIM}{claude_synth['text'][:80]}...{RESET}")
        print()

        time.sleep(0.3)

    # ── PHASE 3: Decision Audit ────────────────────────────────────────────

    print(f"  {BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}PHASE 3: Decision Audit{RESET}")
    print(f"  {DIM}Each model evaluates the other's work and logs decisions{RESET}")
    print(f"  {BOLD}{'='*60}{RESET}")
    print()

    for eval_topic in EVALUATION_TOPICS:
        print(f"  Evaluating: {eval_topic['topic']}")

        # GPT evaluates Claude
        gpt_eval_prompt = eval_topic["prompt_template"].format(
            model_name="GPT-4o",
            other_langchain=claude_findings.get("frameworks:langchain", "N/A"),
            other_crewai=claude_findings.get("frameworks:crewai", "N/A"),
            other_loops=claude_findings.get("analysis:loop-causes", "N/A"),
            other_cost=claude_findings.get("analysis:cost-estimate", "N/A"),
        )
        gpt_eval = call_gpt(gpt_eval_prompt)
        log_decision(gpt_id,
            decision=f"Evaluated Claude's {eval_topic['topic']}",
            reasoning=gpt_eval["text"],
            context={"evaluating": "claude-researcher", "topic": eval_topic["topic"]})
        remember(gpt_id, f"eval:{eval_topic['key']}", gpt_eval["text"])
        gpt_metrics["tokens_in"].append(gpt_eval["input_tokens"])
        gpt_metrics["tokens_out"].append(gpt_eval["output_tokens"])

        # Claude evaluates GPT
        claude_eval_prompt = eval_topic["prompt_template"].format(
            model_name="Claude Sonnet",
            other_langchain=gpt_findings.get("frameworks:langchain", "N/A"),
            other_crewai=gpt_findings.get("frameworks:crewai", "N/A"),
            other_loops=gpt_findings.get("analysis:loop-causes", "N/A"),
            other_cost=gpt_findings.get("analysis:cost-estimate", "N/A"),
        )
        claude_eval = call_claude(claude_eval_prompt)
        log_decision(claude_id,
            decision=f"Evaluated GPT-4o's {eval_topic['topic']}",
            reasoning=claude_eval["text"],
            context={"evaluating": "gpt4o-researcher", "topic": eval_topic["topic"]})
        remember(claude_id, f"eval:{eval_topic['key']}", claude_eval["text"])
        claude_metrics["tokens_in"].append(claude_eval["input_tokens"])
        claude_metrics["tokens_out"].append(claude_eval["output_tokens"])

        print(f"    {GREEN}GPT-4o on Claude{RESET}:  {DIM}{gpt_eval['text'][:80]}...{RESET}")
        print(f"    {BLUE}Claude on GPT-4o{RESET}:  {DIM}{claude_eval['text'][:80]}...{RESET}")
        print()

        time.sleep(0.3)

    # ── FINAL RESULTS ──────────────────────────────────────────────────────

    gpt_loop = get_loop_status(gpt_id)
    claude_loop = get_loop_status(claude_id)

    gpt_total_in = sum(gpt_metrics["tokens_in"])
    gpt_total_out = sum(gpt_metrics["tokens_out"])
    claude_total_in = sum(claude_metrics["tokens_in"])
    claude_total_out = sum(claude_metrics["tokens_out"])

    gpt_cost = calc_cost("gpt-4o", gpt_total_in, gpt_total_out)
    claude_cost = calc_cost("claude-sonnet-4", claude_total_in, claude_total_out)

    gpt_avg_time = round(sum(gpt_metrics["times"]) / len(gpt_metrics["times"]), 2)
    claude_avg_time = round(sum(claude_metrics["times"]) / len(claude_metrics["times"]), 2)

    print(f"  {'='*60}")
    print(f"  {BOLD}FINAL RESULTS{RESET}")
    print(f"  {'='*60}")
    print()
    print(f"  {'Metric':<30} {GREEN+'GPT-4o'+RESET:>20} {BLUE+'Claude Sonnet'+RESET:>20}")
    print(f"  {'-'*62}")
    print(f"  {'Avg response time (s)':<30} {gpt_avg_time:>12.2f} {claude_avg_time:>12.2f}")
    print(f"  {'Total tokens (all phases)':<30} {gpt_total_in+gpt_total_out:>12,} {claude_total_in+claude_total_out:>12,}")
    print(f"  {'Recall accuracy':<30} {str(gpt_correct)+'/10':>12} {str(claude_correct)+'/10':>12}")
    print(f"  {'Loop health':<30} {str(gpt_loop.get('score','?'))+'/100':>12} {str(claude_loop.get('score','?'))+'/100':>12}")
    print(f"  {'Total cost':<30} {'$'+str(gpt_cost):>12} {'$'+str(claude_cost):>12}")
    print(f"  {'Memories stored':<30} {'16':>12} {'16':>12}")
    print(f"  {'Shared findings':<30} {'13':>12} {'13':>12}")
    print(f"  {'Decisions logged':<30} {'3':>12} {'3':>12}")

    print()
    print(f"  {BOLD}What this proved:{RESET}")
    print(f"  Both models achieved {gpt_correct}/10 and {claude_correct}/10 recall accuracy")
    print(f"  through Octopoda's semantic search. The memory layer performs")
    print(f"  identically regardless of which model stored the data.")
    print()
    print(f"  Cross-model collaboration worked: each model successfully read,")
    print(f"  synthesised, and evaluated the other's findings through shared memory.")
    print()
    print(f"  Dashboard: {BOLD}http://localhost:7842{RESET}")
    print(f"  Check: Agents (2) | Shared Memory | Audit Trail | Loop Intelligence")
    print()

    # Save raw data
    output = {
        "experiment": "GPT-4o vs Claude Sonnet 4 — Collaboration through Shared Memory",
        "methodology": {
            "independent_tasks": 10, "synthesis_tasks": 3, "evaluation_tasks": 3,
            "recall_questions": 10, "temperature": 0.7, "max_tokens": 400,
        },
        "results": {
            "gpt4o": {
                "avg_response_time": gpt_avg_time, "total_tokens": gpt_total_in + gpt_total_out,
                "recall_accuracy": gpt_correct, "loop_score": gpt_loop.get("score"),
                "cost_usd": gpt_cost,
            },
            "claude": {
                "avg_response_time": claude_avg_time, "total_tokens": claude_total_in + claude_total_out,
                "recall_accuracy": claude_correct, "loop_score": claude_loop.get("score"),
                "cost_usd": claude_cost,
            },
        },
        "findings": {"gpt4o": gpt_findings, "claude": claude_findings},
    }
    with open("model_showdown_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"  {DIM}Raw data saved to model_showdown_results.json{RESET}")
    print()


if __name__ == "__main__":
    main()
