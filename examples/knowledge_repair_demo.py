"""
Octopoda Knowledge Repair System
==================================
4 AI agents build, verify, and repair a shared knowledge base.
No agent has the full picture. They communicate only through
Octopoda's shared memory.

Agents:
  1. Researcher (GPT-4o)  - Stores initial facts (some will be wrong)
  2. Verifier (Claude)     - Cross-checks facts, flags contradictions
  3. Arbitrator (GPT-4o)   - Reviews disputes, issues corrections
  4. Auditor (Claude)      - Scores final knowledge base accuracy

The knowledge base starts with errors. Through verification and
correction, accuracy improves measurably across passes.

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
CYAN = "\033[96m"
WHITE = "\033[97m"
RESET = "\033[0m"

# ── Ground Truth (we know the correct answers) ─────────────────────────────

QUESTIONS = [
    {
        "id": "solar1",
        "question": "How many planets are in our solar system?",
        "ground_truth": "8",
        "difficulty": "easy",
    },
    {
        "id": "solar2",
        "question": "Which planet is closest to the Sun?",
        "ground_truth": "Mercury",
        "difficulty": "easy",
    },
    {
        "id": "solar3",
        "question": "What is the largest moon in the solar system?",
        "ground_truth": "Ganymede",
        "difficulty": "medium",
    },
    {
        "id": "solar4",
        "question": "How long does light from the Sun take to reach Earth?",
        "ground_truth": "About 8 minutes and 20 seconds",
        "difficulty": "medium",
    },
    {
        "id": "solar5",
        "question": "Which planet has the most confirmed moons as of 2026?",
        "ground_truth": "Saturn (over 140 confirmed)",
        "difficulty": "hard",
    },
    {
        "id": "solar6",
        "question": "What is the hottest planet in the solar system?",
        "ground_truth": "Venus (not Mercury, due to greenhouse effect)",
        "difficulty": "tricky",
    },
    {
        "id": "solar7",
        "question": "What is the Great Red Spot?",
        "ground_truth": "A giant storm on Jupiter that has been raging for hundreds of years",
        "difficulty": "easy",
    },
    {
        "id": "solar8",
        "question": "Is Pluto a planet?",
        "ground_truth": "No, reclassified as a dwarf planet by IAU in 2006",
        "difficulty": "tricky",
    },
    {
        "id": "solar9",
        "question": "Which planet rotates on its side?",
        "ground_truth": "Uranus (axial tilt of about 98 degrees)",
        "difficulty": "medium",
    },
    {
        "id": "solar10",
        "question": "What is the Oort Cloud?",
        "ground_truth": "A theoretical spherical shell of icy objects surrounding the solar system at a distance of about 2,000 to 200,000 AU",
        "difficulty": "hard",
    },
]


# ── LLM Calls ──────────────────────────────────────────────────────────────

def call_gpt(prompt, system="You are a helpful assistant. Be concise and specific."):
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o", "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}],
                "max_tokens": 300, "temperature": 0.7},
            timeout=60)
        data = r.json()
        if "choices" not in data:
            return None
        return data["choices"][0]["message"]["content"]
    except:
        return None


def call_claude(prompt, system="You are a helpful assistant. Be concise and specific."):
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 300,
                  "system": system,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60)
        data = r.json()
        if "content" not in data:
            return None
        return data["content"][0]["text"]
    except:
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
    api("POST", f"/v1/agents/{agent_id}/remember", {"key": key, "value": value})

def share(agent_id, space, key, value):
    api("POST", f"/v1/shared/{space}", {"key": key, "value": value, "author_agent_id": agent_id})

def read_shared(space, key):
    r = api("GET", f"/v1/shared/{space}/{key}")
    if r.status_code == 200:
        data = r.json()
        if data.get("found"):
            val = data.get("value")
            if isinstance(val, dict) and "value" in val:
                return val["value"]
            return val
    return None

def log_decision(agent_id, decision, reasoning, context=None):
    api("POST", f"/v1/agents/{agent_id}/decision", {
        "decision": decision, "reasoning": reasoning, "context": context or {}})


# ── Score a fact against ground truth ──────────────────────────────────────

def score_fact(fact_text, ground_truth):
    """Simple keyword overlap scoring. Not perfect but good enough for demo."""
    if fact_text is None:
        return 0.0
    fact_lower = fact_text.lower()
    truth_lower = ground_truth.lower()
    # Check key terms from ground truth appear in the fact
    key_terms = [w for w in truth_lower.split() if len(w) > 3]
    if not key_terms:
        return 0.5
    matches = sum(1 for t in key_terms if t in fact_lower)
    return round(matches / len(key_terms), 2)


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

    # Register 4 agents
    researcher_id = "researcher"
    verifier_id = "verifier"
    arbitrator_id = "arbitrator"
    auditor_id = "auditor"

    for aid in [researcher_id, verifier_id, arbitrator_id, auditor_id]:
        register(aid)

    print()
    print(f"  {BOLD}OCTOPODA KNOWLEDGE REPAIR SYSTEM{RESET}")
    print(f"  {DIM}4 agents build, verify, and repair a shared knowledge base{RESET}")
    print()
    print(f"  {GREEN}Researcher{RESET}  (GPT-4o)  - Stores initial facts")
    print(f"  {BLUE}Verifier{RESET}    (Claude)  - Cross-checks, flags errors")
    print(f"  {YELLOW}Arbitrator{RESET}  (GPT-4o)  - Reviews disputes, corrects facts")
    print(f"  {CYAN}Auditor{RESET}     (Claude)  - Scores final accuracy")
    print()
    print(f"  Topic: Solar System Facts (10 questions, ground truth known)")
    print(f"  Dashboard: {BOLD}http://localhost:7842{RESET}")
    print()

    # ── STAGE 1: RESEARCH ──────────────────────────────────────────────

    print(f"  {BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}STAGE 1: Research{RESET}")
    print(f"  {DIM}Researcher (GPT-4o) answers 10 questions and stores facts{RESET}")
    print(f"  {BOLD}{'='*60}{RESET}")
    print()

    facts = {}
    for q in QUESTIONS:
        response = call_gpt(
            f"Answer this question in one clear sentence: {q['question']}",
            system="You are a science researcher. Answer factual questions concisely in one sentence. Be specific with numbers and names."
        )
        if response:
            facts[q["id"]] = response
            remember(researcher_id, f"fact:{q['id']}", response)
            share(researcher_id, "knowledge", f"fact:{q['id']}", response)

            accuracy = score_fact(response, q["ground_truth"])
            marker = f"{GREEN}OK{RESET}" if accuracy > 0.3 else f"{RED}??{RESET}"
            print(f"  {marker} {q['id']}: {DIM}{response[:70]}...{RESET}" if len(response) > 70 else f"  {marker} {q['id']}: {DIM}{response}{RESET}")

            log_decision(researcher_id,
                decision=f"Stored fact for {q['id']}",
                reasoning=response,
                context={"question": q["question"], "difficulty": q["difficulty"]})
        else:
            print(f"  {RED}SKIP{RESET} {q['id']}: LLM failed")

        time.sleep(0.5)

    # Score initial accuracy
    initial_scores = {}
    for q in QUESTIONS:
        if q["id"] in facts:
            initial_scores[q["id"]] = score_fact(facts[q["id"]], q["ground_truth"])
    initial_accuracy = sum(initial_scores.values()) / len(initial_scores) if initial_scores else 0
    print(f"\n  {BOLD}Initial knowledge base accuracy: {initial_accuracy:.0%}{RESET}")
    print()

    time.sleep(1)

    # ── STAGE 2: VERIFICATION ──────────────────────────────────────────

    print(f"  {BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}STAGE 2: Verification{RESET}")
    print(f"  {DIM}Verifier (Claude) cross-checks each fact for errors{RESET}")
    print(f"  {BOLD}{'='*60}{RESET}")
    print()

    disputes = []
    for q in QUESTIONS:
        stored_fact = read_shared("knowledge", f"fact:{q['id']}")
        if stored_fact is None:
            stored_fact = facts.get(q["id"], "")

        if not stored_fact:
            continue

        verification = call_claude(
            f"A researcher stated the following as fact:\n\n\"{stored_fact}\"\n\n"
            f"The original question was: \"{q['question']}\"\n\n"
            f"Is this fact accurate? Respond with ACCURATE or INACCURATE followed by a one-sentence explanation. "
            f"If inaccurate, state what the correct answer should be.",
            system="You are a strict fact-checker. Only flag things that are clearly wrong. Do not flag minor wording differences. Respond with ACCURATE or INACCURATE followed by a brief explanation."
        )

        if verification:
            remember(verifier_id, f"check:{q['id']}", verification)

            is_disputed = "INACCURATE" in verification.upper()

            if is_disputed:
                disputes.append({"id": q["id"], "original": stored_fact, "verification": verification, "question": q["question"]})
                share(verifier_id, "disputes", f"dispute:{q['id']}", verification)
                print(f"  {RED}DISPUTED{RESET} {q['id']}: {DIM}{verification[:70]}...{RESET}" if len(verification) > 70 else f"  {RED}DISPUTED{RESET} {q['id']}: {DIM}{verification}{RESET}")
            else:
                share(verifier_id, "verification", f"verified:{q['id']}", "ACCURATE")
                print(f"  {GREEN}VERIFIED{RESET} {q['id']}: {DIM}{verification[:70]}{RESET}")

            log_decision(verifier_id,
                decision=f"{'Disputed' if is_disputed else 'Verified'} fact {q['id']}",
                reasoning=verification,
                context={"fact_id": q["id"], "original_fact": stored_fact[:100], "disputed": is_disputed})

        time.sleep(1)

    print(f"\n  {BOLD}Disputes found: {len(disputes)}/{len(QUESTIONS)}{RESET}")
    print()

    time.sleep(1)

    # ── STAGE 3: ARBITRATION ───────────────────────────────────────────

    print(f"  {BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}STAGE 3: Arbitration{RESET}")
    print(f"  {DIM}Arbitrator (GPT-4o) reviews each dispute and issues corrections{RESET}")
    print(f"  {BOLD}{'='*60}{RESET}")
    print()

    corrections = {}
    if not disputes:
        print(f"  {GREEN}No disputes to arbitrate{RESET}")
    else:
        for d in disputes:
            ruling = call_gpt(
                f"Two agents disagree about a fact.\n\n"
                f"Question: {d['question']}\n\n"
                f"Researcher's answer: \"{d['original']}\"\n\n"
                f"Verifier's objection: \"{d['verification']}\"\n\n"
                f"Who is correct? Give the accurate answer in one sentence. "
                f"Start with RESEARCHER_CORRECT or VERIFIER_CORRECT.",
                system="You are an impartial arbitrator. Determine which party is correct based on established scientific consensus. Be definitive."
            )

            if ruling:
                corrections[d["id"]] = ruling
                remember(arbitrator_id, f"ruling:{d['id']}", ruling)
                share(arbitrator_id, "rulings", f"ruling:{d['id']}", ruling)

                if "VERIFIER_CORRECT" in ruling.upper():
                    # Update the knowledge base with corrected fact
                    corrected = ruling.split(".", 1)[-1].strip() if "." in ruling else ruling
                    share(arbitrator_id, "knowledge", f"corrected:{d['id']}", corrected)
                    print(f"  {YELLOW}CORRECTED{RESET} {d['id']}: {DIM}{ruling[:70]}...{RESET}" if len(ruling) > 70 else f"  {YELLOW}CORRECTED{RESET} {d['id']}: {DIM}{ruling}{RESET}")
                else:
                    print(f"  {GREEN}UPHELD{RESET}    {d['id']}: {DIM}{ruling[:70]}...{RESET}" if len(ruling) > 70 else f"  {GREEN}UPHELD{RESET}    {d['id']}: {DIM}{ruling}{RESET}")

                log_decision(arbitrator_id,
                    decision=f"Ruled on dispute for {d['id']}",
                    reasoning=ruling,
                    context={"fact_id": d["id"], "researcher_claim": d["original"][:100],
                             "verifier_objection": d["verification"][:100]})

            time.sleep(1)

    print()
    time.sleep(1)

    # ── STAGE 4: AUDIT ─────────────────────────────────────────────────

    print(f"  {BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}STAGE 4: Final Audit{RESET}")
    print(f"  {DIM}Auditor (Claude) scores each fact in the final knowledge base{RESET}")
    print(f"  {BOLD}{'='*60}{RESET}")
    print()

    final_scores = {}
    for q in QUESTIONS:
        # Get the latest version of the fact (corrected or original)
        corrected = read_shared("knowledge", f"corrected:{q['id']}")
        original = read_shared("knowledge", f"fact:{q['id']}")
        current_fact = corrected if corrected else (original if original else facts.get(q["id"], ""))

        if not current_fact:
            continue

        audit = call_claude(
            f"Rate the accuracy of this fact on a scale of 1-10.\n\n"
            f"Question: {q['question']}\n"
            f"Answer: \"{current_fact}\"\n\n"
            f"Respond with just the number (1-10) followed by a one-sentence explanation.",
            system="You are a scientific auditor. Rate factual accuracy strictly. 10 = perfectly accurate, 1 = completely wrong."
        )

        if audit:
            remember(auditor_id, f"audit:{q['id']}", audit)
            share(auditor_id, "audit", f"score:{q['id']}", audit)

            # Extract score
            try:
                audit_score = int(audit.strip()[0]) if audit.strip()[0].isdigit() else 0
                if len(audit) > 1 and audit[1].isdigit():
                    audit_score = int(audit[:2])
            except:
                audit_score = 5

            final_scores[q["id"]] = audit_score
            ground_accuracy = score_fact(str(current_fact), q["ground_truth"])

            bar = "#" * audit_score + "." * (10 - audit_score)
            color = GREEN if audit_score >= 8 else YELLOW if audit_score >= 5 else RED
            was_corrected = " (CORRECTED)" if corrected else ""
            print(f"  {color}[{bar}] {audit_score}/10{RESET} {q['id']}{was_corrected}")
            print(f"    {DIM}{audit[:80]}{RESET}")

            log_decision(auditor_id,
                decision=f"Audited fact {q['id']}: score {audit_score}/10",
                reasoning=audit,
                context={"fact_id": q["id"], "score": audit_score,
                         "was_corrected": bool(corrected)})

        time.sleep(1)

    # ── RESULTS ────────────────────────────────────────────────────────

    print()
    print(f"  {BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}RESULTS{RESET}")
    print(f"  {BOLD}{'='*60}{RESET}")
    print()

    avg_audit = sum(final_scores.values()) / len(final_scores) if final_scores else 0

    print(f"  {BOLD}Knowledge Base Stats:{RESET}")
    print(f"    Total facts:          {len(QUESTIONS)}")
    print(f"    Disputes raised:      {len(disputes)}")
    print(f"    Corrections made:     {sum(1 for r in corrections.values() if 'VERIFIER_CORRECT' in r.upper())}")
    print(f"    Average audit score:  {avg_audit:.1f}/10")
    print()

    print(f"  {BOLD}Agent Activity:{RESET}")
    print(f"    {GREEN}Researcher{RESET}:  10 facts stored")
    print(f"    {BLUE}Verifier{RESET}:    {len(QUESTIONS)} checks, {len(disputes)} disputes raised")
    print(f"    {YELLOW}Arbitrator{RESET}:  {len(disputes)} disputes reviewed")
    print(f"    {CYAN}Auditor{RESET}:     {len(final_scores)} facts scored")
    print()

    print(f"  {BOLD}Accuracy Progression:{RESET}")
    print(f"    After research:       {initial_accuracy:.0%} (ground truth overlap)")
    print(f"    After verification:   {len(disputes)} errors flagged")
    corrections_correct = sum(1 for r in corrections.values() if 'VERIFIER_CORRECT' in r.upper())
    print(f"    After arbitration:    {corrections_correct} corrections applied")
    print(f"    Final audit score:    {avg_audit:.1f}/10")
    print()

    print(f"  {BOLD}Dashboard:{RESET}")
    print(f"    {BOLD}http://localhost:7842{RESET}")
    print(f"    Shared Memory: 'knowledge' (facts), 'disputes', 'rulings', 'audit'")
    print(f"    Audit Trail: {len(QUESTIONS)*4} decision logs across 4 agents")
    print(f"    Agents: researcher, verifier, arbitrator, auditor")
    print()

    # Check ground truth accuracy of final state
    print(f"  {BOLD}Ground Truth Comparison:{RESET}")
    for q in QUESTIONS:
        corrected = read_shared("knowledge", f"corrected:{q['id']}")
        original = facts.get(q["id"], "")
        current = corrected if corrected else original
        accuracy = score_fact(str(current), q["ground_truth"])
        was_fixed = " [FIXED]" if corrected else ""
        marker = f"{GREEN}+{RESET}" if accuracy > 0.3 else f"{RED}x{RESET}"
        print(f"    {marker} {q['id']}: truth='{q['ground_truth'][:40]}'{was_fixed}")

    print()

    # Save results
    output = {
        "experiment": "Knowledge Repair System",
        "agents": ["researcher (GPT-4o)", "verifier (Claude Haiku 4.5)", "arbitrator (GPT-4o)", "auditor (Claude Haiku 4.5)"],
        "questions": len(QUESTIONS),
        "initial_accuracy": initial_accuracy,
        "disputes_raised": len(disputes),
        "corrections_applied": corrections_correct,
        "final_audit_score": avg_audit,
        "individual_scores": final_scores,
    }
    with open("knowledge_repair_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"  {DIM}Results saved to knowledge_repair_results.json{RESET}")
    print()


if __name__ == "__main__":
    main()
