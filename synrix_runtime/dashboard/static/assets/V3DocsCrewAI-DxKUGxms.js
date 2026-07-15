import{aN as e,aU as i}from"./index-RsFqQstg.js";import{u as o,a,D as l,b as d,C as s,I as r,P as c}from"./V3DocsShared-BKwaCxO9.js";function p(){const{prev:t,next:n}=o();return e.jsxs(a,{children:[e.jsx(i,{title:"CrewAI — Octopodas Docs",path:"/docs/crewai",description:"Persist task outputs and role-tagged findings across CrewAI kickoffs with CrewAIMemory."}),e.jsx(l,{eyebrow:"Framework",title:"CrewAI",lede:"CrewAIMemory is a crew-scoped memory bus. Persist task outputs after each kickoff and store role-tagged findings that any future run can read.",meta:["CrewAI 1.x","~3 min"]}),e.jsxs(d,{title:"Before you start",children:[e.jsx("strong",{children:"Requires:"})," Python 3.9+, octopoda 3.1.4+, crewai 1.x."," ",e.jsx("strong",{children:"Prerequisite:"})," Finish Getting started so your API key is set."]}),e.jsx("h2",{children:"Install"}),e.jsx(s,{children:"pip install octopoda crewai"}),e.jsxs("p",{children:["Only ",e.jsx(r,{children:"OCTOPODA_API_KEY"})," is required for memory. If your Crew's LLM calls a provider directly, that provider's key (e.g."," ",e.jsx(r,{children:"OPENAI_API_KEY"}),", ",e.jsx(r,{children:"ANTHROPIC_API_KEY"}),") is optional and only needed for the LLM itself:"]}),e.jsx(s,{children:"export OPENAI_API_KEY=sk-...   # optional — only if your Crew uses OpenAI"}),e.jsx("h2",{children:"Two-step integration"}),e.jsx("h3",{children:"Step 1 — Import the memory bus"}),e.jsx(s,{lang:"python",children:"from octopoda import CrewAIMemory"}),e.jsx("h3",{children:"Step 2 — Attach it to your crew"}),e.jsx(s,{lang:"python",children:'memory = CrewAIMemory(crew_id="your_crew_id")'}),e.jsxs("p",{children:[e.jsx(r,{children:"crew_id"})," is one string per crew configuration. Use the same value every time you run the crew, or findings from prior runs won't be visible."]}),e.jsx("p",{children:"Common patterns:"}),e.jsx(s,{lang:"python",children:`CrewAIMemory(crew_id="market_research_crew")       # one per crew name
CrewAIMemory(crew_id=f"research_{project_id}")     # one per project`}),e.jsx("h2",{children:"Persist task results after each kickoff"}),e.jsx("p",{children:"After the crew finishes running, iterate the tasks output and persist each:"}),e.jsx(s,{lang:"python",children:`result = crew.kickoff()

for i, task_output in enumerate(result.tasks_output):
    memory.store_task_result(
        task_name=f"task_{i+1}",
        result=str(task_output.raw),
        agent_role=str(task_output.agent),
    )`}),e.jsx("h3",{children:"store_task_result signature"}),e.jsx(s,{lang:"python",children:"memory.store_task_result(task_name, result, agent_role)"}),e.jsx("p",{children:"Three positional arguments in this exact order. Pass them as keywords if you want to be explicit:"}),e.jsx(s,{lang:"python",children:`memory.store_task_result(
    task_name="market_scan",
    result="Found 3 vector DBs",
    agent_role="researcher",
)`}),e.jsx("h2",{children:"Store long-term findings"}),e.jsxs("p",{children:["Task results are episodic — they record what each task produced in a specific kickoff. For durable knowledge any future kickoff should read, use ",e.jsx(r,{children:"store_finding"}),":"]}),e.jsx(s,{lang:"python",children:`memory.store_finding(
    agent_role="researcher",
    key="top_competitor",
    finding="Pinecone leads in managed vector DBs",
)`}),e.jsx("h3",{children:"store_finding signature"}),e.jsx(s,{lang:"python",children:"memory.store_finding(agent_role, key, finding)"}),e.jsx("p",{children:"Three positional arguments. The order is DIFFERENT from store_task_result (agent_role comes first here, last there). Easy to mix up."}),e.jsxs("p",{children:[e.jsx(r,{children:"finding"})," can be any JSON-serialisable value: string, dict, list, nested."]}),e.jsx("h2",{children:"Retrieve findings in later runs"}),e.jsx(s,{lang:"python",children:`memory = CrewAIMemory(crew_id="your_crew_id")     # same crew_id
findings = memory.get_all_findings()

for f in findings:
    print(f["key"], "->", f["data"]["value"])`}),e.jsxs("p",{children:["Each finding is a dict with ",e.jsx(r,{children:"key"})," (what you passed as ",e.jsx(r,{children:"key"}),") and"," ",e.jsx(r,{children:"data"})," (which contains your original value under ",e.jsx(r,{children:'data["value"]'})," plus metadata tags)."]}),e.jsx("h2",{children:"More memory API"}),e.jsx("p",{children:"Octopoda provides additional methods for deeper memory management:"}),e.jsx(s,{lang:"python",children:`# One specific finding
memory.get_finding("top_competitor")

# All findings grouped for a knowledge base view
memory.get_crew_knowledge_base()

# Full crew snapshot (state + findings + task results)
memory.crew_snapshot(label="pre_migration")

# Restore from snapshot
memory.crew_restore(label="pre_migration")`}),e.jsx("h2",{children:"Task results vs findings — when to use which"}),e.jsxs("table",{children:[e.jsx("thead",{children:e.jsxs("tr",{children:[e.jsx("th",{children:"You're storing..."}),e.jsx("th",{children:"Use"})]})}),e.jsxs("tbody",{children:[e.jsxs("tr",{children:[e.jsx("td",{children:"What each task produced in one specific run"}),e.jsx("td",{children:e.jsx(r,{children:"store_task_result"})})]}),e.jsxs("tr",{children:[e.jsx("td",{children:"A fact that future runs should know"}),e.jsx("td",{children:e.jsx(r,{children:"store_finding"})})]}),e.jsxs("tr",{children:[e.jsx("td",{children:"A point-in-time checkpoint of everything"}),e.jsx("td",{children:e.jsx(r,{children:"crew_snapshot"})})]})]})]}),e.jsx("p",{children:`Rule of thumb: if it's "this run produced X" → task result. If it's "we now know X" → finding.`}),e.jsx("h2",{children:"Octopoda memory and CrewAI's built-in memory"}),e.jsxs("p",{children:["CrewAI has its own memory system (enabled with ",e.jsx(r,{children:"memory=True"})," on Crew). The two coexist:"]}),e.jsxs("ul",{children:[e.jsx("li",{children:"CrewAI's memory is episodic within a kickoff (keeps agents in sync during one run)"}),e.jsx("li",{children:"Octopoda memory is persistent across kickoffs (your team's knowledge base)"})]}),e.jsxs("p",{children:["You can use both. ",e.jsx(r,{children:"memory=True"})," on Crew doesn't interfere with Octopoda. If you only want Octopoda (simpler, no conflicts), leave ",e.jsx(r,{children:"memory=False"}),"."]}),e.jsx("h2",{children:"Full example"}),e.jsx(s,{lang:"python",children:`import os
os.environ["OPENAI_API_KEY"] = "sk-..."

from crewai import Agent, Task, Crew, Process, LLM
from octopoda import CrewAIMemory

llm = LLM(model="gpt-4o-mini", temperature=0.2)

researcher = Agent(
    role="Market Researcher",
    goal="Find emerging competitors in AI memory tools",
    backstory="You are a concise analyst who outputs short factual statements.",
    llm=llm,
    verbose=False,
)

task = Task(
    description="Name two popular open-source agent memory libraries in 2026.",
    expected_output="Two library names, one per line.",
    agent=researcher,
)

crew = Crew(agents=[researcher], tasks=[task], process=Process.sequential, verbose=False)

memory = CrewAIMemory(crew_id="market_research_crew")

# Print any prior findings the crew already knows
for f in memory.get_all_findings():
    print("Prior finding:", f["key"], "->", f["data"]["value"])

# Run the crew
result = crew.kickoff()

# Persist task results
for i, task_output in enumerate(result.tasks_output):
    memory.store_task_result(
        task_name=f"task_{i+1}",
        result=str(task_output.raw),
        agent_role=str(task_output.agent),
    )

# Store a new finding for future runs
memory.store_finding(
    agent_role="researcher",
    key="top_two_libraries_2026",
    finding=str(result),
)`}),e.jsx("h2",{children:"Common mistakes"}),e.jsx("h3",{children:"Swapping argument orders between store_finding and store_task_result"}),e.jsx(s,{lang:"python",children:`memory.store_finding("task_x", "result", "researcher")
# Wrong — this passes task_x as agent_role`}),e.jsx("p",{children:"Always use keyword args to be safe:"}),e.jsx(s,{lang:"python",children:'memory.store_finding(agent_role="researcher", key="task_x", finding="result")'}),e.jsx("h3",{children:"Changing crew_id between runs"}),e.jsx(s,{lang:"python",children:`# First run
CrewAIMemory(crew_id="research_crew").store_finding(...)

# Second run
CrewAIMemory(crew_id="research-crew").get_all_findings()
# Returns []  — underscore vs hyphen = different crew`}),e.jsxs("p",{children:["Stable ",e.jsx(r,{children:"crew_id"})," is the only way findings carry between runs."]}),e.jsx("h3",{children:"Forgetting Task needs expected_output"}),e.jsx(s,{lang:"python",children:`Task(description="...", agent=researcher)
# CrewAI 1.x: ValidationError — expected_output is required`}),e.jsxs("p",{children:["Always provide ",e.jsx(r,{children:"expected_output"})," with a short description of what the task should produce."]}),e.jsx("h3",{children:"Agent has no LLM"}),e.jsx(s,{lang:"python",children:`Agent(role="...", goal="...", backstory="...")
# CrewAI: error or silent fallback to default`}),e.jsxs("p",{children:["Explicitly pass ",e.jsx(r,{children:'llm=LLM(model="gpt-4o-mini")'})," or equivalent."]}),e.jsx("h2",{children:"Troubleshooting"}),e.jsx("h3",{children:"pydantic.ValidationError: expected_output Field required"}),e.jsxs("p",{children:["CrewAI 1.x requires ",e.jsx(r,{children:"expected_output"})," on every Task. Add it."]}),e.jsx("h3",{children:"openai.AuthenticationError"}),e.jsxs("p",{children:[e.jsx(r,{children:"OPENAI_API_KEY"})," not set. Export it."]}),e.jsx("h3",{children:"Findings from previous run don't appear"}),e.jsxs("p",{children:["Your ",e.jsx(r,{children:"crew_id"})," changed between runs. Case-sensitive, whitespace matters. Match exactly."]}),e.jsx("h3",{children:"store_finding silently stored with wrong fields"}),e.jsx("p",{children:"You mixed up argument order. Use keyword args:"}),e.jsx(s,{lang:"python",children:"memory.store_finding(agent_role=..., key=..., finding=...)"}),e.jsx("h3",{children:"AuthError: api_key is required"}),e.jsx("p",{children:"You're on octopoda < 3.1.4 in local mode. Upgrade:"}),e.jsx(s,{children:"pip install --upgrade octopoda"}),e.jsx("p",{children:"v3.1.4+ falls back to local SQLite automatically when no cloud key is set."}),e.jsx("h2",{children:"Next step"}),e.jsx("p",{children:"For single-agent persistence without CrewAI, see Vanilla Python. For multi-agent chat without task structure, see AutoGen."}),e.jsx(c,{prev:t,next:n})]})}export{p as default};
