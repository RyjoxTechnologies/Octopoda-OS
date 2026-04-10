"""
Octopoda AI Debate: GPT-4o vs Claude Sonnet
============================================
Two AI models debate a controversial topic through shared memory.
Each model reads the other's arguments and responds directly.

Topic: "Should AI models like Claude Mythos be released publicly,
        or is Anthropic right to restrict access?"

GPT-4o argues FOR public release.
Claude argues FOR restriction.

5 rounds of debate. Each round:
1. Model reads the other's latest argument from shared memory
2. Writes a response that directly addresses their points
3. Logs a decision about whether the other model made a good argument

Dashboard: http://localhost:7842
Watch the Shared Memory tab fill up in real time.
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
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

TOPIC = "Should powerful AI models like Claude Mythos be released to the public, or is Anthropic right to restrict access?"

GPT_SYSTEM = """You are GPT-4o, arguing that powerful AI models should be released publicly.
You believe in open access, democratisation of AI, and that restriction slows innovation and concentrates power.
You are in a debate with Claude Sonnet. Address their specific points directly.
Keep each response to 3-4 sentences. Be sharp, specific, and persuasive. No hedging."""

CLAUDE_SYSTEM = """You are Claude Sonnet, arguing that Anthropic is right to restrict access to powerful models like Mythos.
You believe some capabilities are too dangerous for unrestricted release and that responsible deployment requires staged access.
You are in a debate with GPT-4o. Address their specific points directly.
Keep each response to 3-4 sentences. Be sharp, specific, and persuasive. No hedging."""


# ── LLM Calls ──────────────────────────────────────────────────────────────

def call_gpt(prompt, system=GPT_SYSTEM):
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o",
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": prompt}],
                  "max_tokens": 250, "temperature": 0.8},
            timeout=60)
        data = r.json()
        if "choices" not in data:
            return None
        return data["choices"][0]["message"]["content"]
    except:
        return None


def call_claude(prompt, system=CLAUDE_SYSTEM):
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 250,
                  "system": system,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60)
        data = r.json()
        if "content" not in data:
            print(f"    {RED}Claude error: {data.get('error', {}).get('message', 'unknown')}{RESET}")
            return None
        return data["content"][0]["text"]
    except Exception as e:
        print(f"    {RED}Claude exception: {e}{RESET}")
        return None


# ── Octopoda helpers ───────────────────────────────────────────────────────

def api(method, path, data=None):
    url = f"{BASE}{path}"
    if method == "POST":
        return requests.post(url, json=data, timeout=15)
    elif method == "PUT":
        return requests.put(url, json=data, timeout=15)
    return requests.get(url, timeout=15)


def register(agent_id):
    api("POST", "/v1/agents", {"agent_id": agent_id})


def remember(agent_id, key, value):
    r = api("POST", f"/v1/agents/{agent_id}/remember", {"key": key, "value": value})
    return r.json() if r.status_code == 200 else {}


def share(agent_id, space, key, value):
    api("POST", f"/v1/shared/{space}", {"key": key, "value": value, "author_agent_id": agent_id})


def log_decision(agent_id, decision, reasoning, context=None):
    api("POST", f"/v1/agents/{agent_id}/decision", {
        "decision": decision,
        "reasoning": reasoning,
        "context": context or {},
    })


def get_loop_status(agent_id):
    r = api("GET", f"/v1/agents/{agent_id}/loops/status")
    return r.json() if r.status_code == 200 else {}


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

    gpt_id = "gpt4o-debater"
    claude_id = "claude-debater"
    register(gpt_id)
    register(claude_id)

    print()
    print(f"  {BOLD}OCTOPODA AI DEBATE{RESET}")
    print(f"  {DIM}GPT-4o vs Claude Sonnet — Live Debate Through Shared Memory{RESET}")
    print()
    print(f"  Topic: {BOLD}{TOPIC}{RESET}")
    print()
    print(f"  {GREEN}GPT-4o{RESET}:  Argues FOR public release")
    print(f"  {BLUE}Claude{RESET}:  Argues FOR restriction")
    print()
    print(f"  5 rounds. Each model reads and responds to the other's points.")
    print(f"  Dashboard: {BOLD}http://localhost:7842/dashboard/shared{RESET}")
    print()
    print(f"  {DIM}{'='*70}{RESET}")
    print()

    # Store the topic
    share(gpt_id, "debate", "topic", TOPIC)
    remember(gpt_id, "debate:topic", TOPIC)
    remember(claude_id, "debate:topic", TOPIC)

    gpt_last = ""
    claude_last = ""
    debate_history = []

    for round_num in range(1, 6):
        print(f"  {BOLD}ROUND {round_num}/5{RESET}")
        print()

        # ── GPT's turn ────────────────────────────────────────────────

        if round_num == 1:
            gpt_prompt = f"The debate topic is: {TOPIC}\n\nMake your opening argument for why these models should be released publicly. 3-4 sentences."
        else:
            gpt_prompt = f"The debate topic is: {TOPIC}\n\nYour opponent (Claude) just argued:\n\n\"{claude_last}\"\n\nRespond directly to their points. Why are they wrong? 3-4 sentences."

        gpt_response = call_gpt(gpt_prompt)
        if gpt_response:
            gpt_last = gpt_response

            # Store in agent memory
            remember(gpt_id, f"debate:round{round_num}:argument", gpt_response)

            # Share to debate space
            share(gpt_id, "debate", f"round{round_num}:gpt4o", gpt_response)

            # Log decision
            if round_num > 1:
                log_decision(gpt_id,
                    decision=f"Round {round_num}: Countered Claude's argument on restriction",
                    reasoning=f"Claude argued: '{claude_last[:100]}...' — I responded by defending open access.",
                    context={"round": round_num, "opponent": "claude-debater", "topic": "model release"})

            debate_history.append({"round": round_num, "model": "GPT-4o", "argument": gpt_response})

            print(f"  {GREEN}GPT-4o:{RESET}")
            # Word wrap the argument
            words = gpt_response.split()
            line = "    "
            for word in words:
                if len(line) + len(word) + 1 > 78:
                    print(line)
                    line = "    " + word
                else:
                    line += " " + word if line.strip() else "    " + word
            print(line)
            print()
        else:
            print(f"  {GREEN}GPT-4o:{RESET} {RED}Failed to respond{RESET}")
            print()

        # Delay to avoid rate limits
        time.sleep(2)

        # ── Claude's turn ─────────────────────────────────────────────

        if round_num == 1:
            claude_prompt = f"The debate topic is: {TOPIC}\n\nYour opponent (GPT-4o) just argued:\n\n\"{gpt_last}\"\n\nMake your opening argument for why restriction is the right approach, and respond to their points. 3-4 sentences."
        else:
            claude_prompt = f"The debate topic is: {TOPIC}\n\nYour opponent (GPT-4o) just argued:\n\n\"{gpt_last}\"\n\nRespond directly to their points. Why are they wrong? 3-4 sentences."

        claude_response = call_claude(claude_prompt)
        if claude_response:
            claude_last = claude_response

            # Store in agent memory
            remember(claude_id, f"debate:round{round_num}:argument", claude_response)

            # Share to debate space
            share(claude_id, "debate", f"round{round_num}:claude", claude_response)

            # Log decision
            log_decision(claude_id,
                decision=f"Round {round_num}: Countered GPT-4o's argument on open release",
                reasoning=f"GPT-4o argued: '{gpt_last[:100]}...' — I responded by defending responsible restriction.",
                context={"round": round_num, "opponent": "gpt4o-debater", "topic": "model restriction"})

            debate_history.append({"round": round_num, "model": "Claude", "argument": claude_response})

            print(f"  {BLUE}Claude:{RESET}")
            words = claude_response.split()
            line = "    "
            for word in words:
                if len(line) + len(word) + 1 > 78:
                    print(line)
                    line = "    " + word
                else:
                    line += " " + word if line.strip() else "    " + word
            print(line)
            print()
        else:
            print(f"  {BLUE}Claude:{RESET} {RED}Failed to respond{RESET}")
            print()

        print(f"  {DIM}{'- '*35}{RESET}")
        print()

        # Delay between rounds
        time.sleep(2)

    # ── Closing statements ─────────────────────────────────────────────

    print(f"  {BOLD}CLOSING STATEMENTS{RESET}")
    print()

    # Build debate history summary for closing
    debate_summary = ""
    for entry in debate_history:
        debate_summary += f"{entry['model']} (Round {entry['round']}): {entry['argument']}\n\n"

    # GPT closing
    gpt_closing_prompt = f"The debate topic was: {TOPIC}\n\nHere is the full debate so far:\n\n{debate_summary}\n\nGive your closing statement in 3-4 sentences. Summarise your strongest point and why your position is correct. Be definitive."
    gpt_closing = call_gpt(gpt_closing_prompt)
    if gpt_closing:
        remember(gpt_id, "debate:closing", gpt_closing)
        share(gpt_id, "debate", "closing:gpt4o", gpt_closing)
        log_decision(gpt_id,
            decision="Closing statement: Maintained position for open release",
            reasoning=gpt_closing,
            context={"phase": "closing", "rounds_completed": 5})

        print(f"  {GREEN}GPT-4o:{RESET}")
        words = gpt_closing.split()
        line = "    "
        for word in words:
            if len(line) + len(word) + 1 > 78:
                print(line)
                line = "    " + word
            else:
                line += " " + word if line.strip() else "    " + word
        print(line)
        print()

    time.sleep(2)

    # Claude closing
    claude_closing_prompt = f"The debate topic was: {TOPIC}\n\nHere is the full debate so far:\n\n{debate_summary}\n\nGive your closing statement in 3-4 sentences. Summarise your strongest point and why your position is correct. Be definitive."
    claude_closing = call_claude(claude_closing_prompt)
    if claude_closing:
        remember(claude_id, "debate:closing", claude_closing)
        share(claude_id, "debate", "closing:claude", claude_closing)
        log_decision(claude_id,
            decision="Closing statement: Maintained position for restriction",
            reasoning=claude_closing,
            context={"phase": "closing", "rounds_completed": 5})

        print(f"  {BLUE}Claude:{RESET}")
        words = claude_closing.split()
        line = "    "
        for word in words:
            if len(line) + len(word) + 1 > 78:
                print(line)
                line = "    " + word
            else:
                line += " " + word if line.strip() else "    " + word
        print(line)
        print()

    # ── Final summary ──────────────────────────────────────────────────

    print(f"  {BOLD}{'='*70}{RESET}")
    print(f"  {BOLD}DEBATE COMPLETE{RESET}")
    print(f"  {BOLD}{'='*70}{RESET}")
    print()

    gpt_loop = get_loop_status(gpt_id)
    claude_loop = get_loop_status(claude_id)

    print(f"  {GREEN}GPT-4o{RESET}:  {len([d for d in debate_history if d['model']=='GPT-4o'])} arguments + closing | loop score: {gpt_loop.get('score', '?')}/100")
    print(f"  {BLUE}Claude{RESET}:  {len([d for d in debate_history if d['model']=='Claude'])} arguments + closing | loop score: {claude_loop.get('score', '?')}/100")
    print()
    print(f"  Dashboard data:")
    print(f"    Shared Memory: {len(debate_history) + 3} items in 'debate' space")
    print(f"    Audit Trail: {len(debate_history)} decision logs with reasoning")
    print(f"    Agents: 2 debaters with full memory of all rounds")
    print()
    print(f"  Open {BOLD}http://localhost:7842{RESET} to see:")
    print(f"    - Shared Memory: the full debate thread")
    print(f"    - Audit Trail: each model's reasoning for countering the other")
    print(f"    - Memory Explorer: what each model remembers from the debate")
    print(f"    - Loop Intelligence: whether either model started repeating itself")
    print()

    # Save debate
    output = {
        "topic": TOPIC,
        "gpt4o_position": "FOR public release",
        "claude_position": "FOR restriction",
        "rounds": debate_history,
        "gpt4o_closing": gpt_closing,
        "claude_closing": claude_closing,
    }
    with open("debate_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"  {DIM}Full debate saved to debate_results.json{RESET}")
    print()


if __name__ == "__main__":
    main()
