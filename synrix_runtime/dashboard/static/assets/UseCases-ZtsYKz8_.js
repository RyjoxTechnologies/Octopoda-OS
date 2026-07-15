import{bg as d,aN as e,aU as c,aV as m,aP as n,aQ as h}from"./index-RsFqQstg.js";import{B as p}from"./button-DxYfa4mm.js";import{N as u,F as g}from"./Footer-Bckgcb7L.js";import{C as x}from"./CodeBlock-eZgfYd4-.js";import{m as i}from"./proxy-DETd9jo6.js";import{B as y}from"./bot-DH_M4Xsn.js";import{C as v}from"./chart-column-DRAuAM2L.js";import"./octopoda-logo-D6lOdQdh.js";import"./courseModules-COM931Z8.js";import"./chevron-down-CE0RuKpi.js";import"./graduation-cap-CWqaQ3bM.js";import"./book-open-BvWlqggq.js";import"./newspaper-CrW3od4g.js";import"./layout-dashboard-Cgrz2Nza.js";import"./copy-XIpaKHQY.js";/**
 * @license lucide-react v0.462.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const w=d("Headphones",[["path",{d:"M3 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a9 9 0 0 1 18 0v7a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3",key:"1xhozi"}]]);/**
 * @license lucide-react v0.462.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const f=d("Microscope",[["path",{d:"M6 18h8",key:"1borvv"}],["path",{d:"M3 22h18",key:"8prr45"}],["path",{d:"M14 22a7 7 0 1 0 0-14h-1",key:"1jwaiy"}],["path",{d:"M9 14h2",key:"197e7h"}],["path",{d:"M9 12a2 2 0 0 1-2-2V6h6v4a2 2 0 0 1-2 2Z",key:"1bmzmy"}],["path",{d:"M12 6V3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3",key:"1drr47"}]]),l=[{id:"customer-support",icon:w,title:"Customer Support Agent That Remembers Every Customer",problem:`Your support bot asks customers to repeat themselves every session. "What's your order number?" for the 5th time. Customers hate it.`,solution:"With Octopoda, the agent remembers every customer interaction. Their name, order history, previous issues, preferences — all recalled instantly.",code:`from octopoda import LangChainMemory
from langchain.chains import ConversationChain
from langchain_openai import ChatOpenAI

# Each customer gets persistent memory
memory = LangChainMemory(f"support_{customer_id}")
chain = ConversationChain(llm=ChatOpenAI(), memory=memory)

# First interaction
chain.invoke({"input": "Hi, I'm Alice. Order #12345 hasn't arrived."})

# Days later — agent remembers everything
chain.invoke({"input": "Any update on my order?"})
# Agent recalls: Alice, order #12345, shipping issue
# No need to ask again`,language:"python",results:[{metric:"Customer satisfaction",value:"Up",detail:"No repetition"},{metric:"Resolution time",value:"Down",detail:"Instant context"},{metric:"Ticket throughput",value:"3x",detail:"Less back-and-forth"}]},{id:"research-team",icon:f,title:"Multi-Agent Research Team with Shared Memory",problem:"You have a CrewAI setup with a researcher, analyst, and writer. But Agent A discovers something and Agent B has no idea. They duplicate work, miss connections, and produce inconsistent reports.",solution:"Octopoda's shared memory bus lets all agents access the same knowledge. The researcher stores findings, the analyst reads them, and the writer pulls from both.",code:`from octopoda import CrewAIMemory

crew_memory = CrewAIMemory("research_team")

# Researcher stores findings
crew_memory.save_agent_output("researcher", "market_data",
    "AI agent market growing at 34% CAGR, expected $12B by 2028")

# Analyst accesses researcher's work
crew_memory.save_agent_output("analyst", "competitive_landscape",
    "Top 5 players hold 67% market share. Biggest gap: agent memory.")

# Writer searches across ALL agent knowledge
results = crew_memory.search("market growth projections")
# Finds both researcher and analyst outputs instantly

# Track what the crew knows
summary = crew_memory.get_crew_summary()
# {"task_results": 3, "agent_outputs": 8, "shared_knowledge": 5}`,language:"python",results:[{metric:"Duplicate research",value:"0",detail:"Eliminated"},{metric:"Agent collaboration",value:"Real-time",detail:"Shared memory bus"},{metric:"Report quality",value:"Up",detail:"Consistent & comprehensive"}]},{id:"personal-assistant",icon:y,title:"Personal Assistant That Actually Knows You",problem:"Every AI assistant starts as a stranger. It doesn't know your preferences, your schedule patterns, your communication style, or what you're working on.",solution:"With Octopoda, your assistant builds a growing understanding of you over time. It remembers your preferences, learns your patterns, and gets better every conversation.",code:`from octopoda import OpenAIAgentsMemory
from agents import Agent, Runner

memory = OpenAIAgentsMemory()

assistant = Agent(
    name="Personal Assistant",
    instructions="""You are a personal AI assistant.
    Use your memory tools to learn about the user over time.
    Always check your memory before asking questions they've already answered.""",
    tools=memory.tools(),
)

# Week 1
Runner.run_sync(assistant, "I'm Alice, CTO at TechCorp. I prefer bullet points.")
Runner.run_sync(assistant, "Schedule a meeting with the ML team for Thursday")

# Week 4 — assistant knows everything
Runner.run_sync(assistant, "Prepare talking points for my next meeting")
# Agent searches memory → knows Alice is CTO, prefers bullets,
# has ML team meetings on Thursdays, and what was discussed last time`,language:"python",results:[{metric:"Learning",value:"Continuous",detail:"Gets smarter over time"},{metric:"Repeat questions",value:"0",detail:"Never asks twice"},{metric:"Context",value:"Day one",detail:"Aware from the start"}]},{id:"production-monitoring",icon:v,title:"Mission Control for AI Agents in Production",problem:"You deploy 20 agents to production. One crashes. Another starts giving weird answers. A third has been idle for 2 hours. You have no visibility into any of this.",solution:"Octopoda's dashboard shows every agent's health, memory state, and activity in real-time. Set alerts for crashes, anomalies, and limits approaching.",dashboardFeatures:["Real-time agent health scores (0-100)","Memory usage per agent with trend charts","Knowledge graph visualization — see what your agents know","Temporal history — trace how any piece of knowledge evolved","Crash detection with instant alerts","One dashboard for agents across LangChain, CrewAI, OpenAI, and custom frameworks"],results:[{metric:"Visibility",value:"Instant",detail:"All agents, one view"},{metric:"Problem detection",value:"Proactive",detail:"Before users notice"},{metric:"Compliance",value:"Built-in",detail:"Full audit trail"}]}],b=({useCase:t,index:a})=>{const o=t.icon,r=a%2===0;return e.jsxs(i.div,{id:t.id,className:`${r?"pos-card":"pos-card-dark"} scroll-mt-24`,initial:{opacity:0,y:24},whileInView:{opacity:1,y:0},viewport:{once:!0},transition:{duration:.5,delay:.1},children:[e.jsxs("div",{className:"flex items-start gap-4 mb-8",children:[e.jsx("div",{className:`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl ${r?"bg-foreground/5":"bg-white/10"}`,children:e.jsx(o,{className:`h-6 w-6 ${r?"text-foreground/70":"text-primary"}`})}),e.jsx("h3",{className:`text-xl font-semibold md:text-2xl ${r?"text-foreground":"text-white"}`,children:t.title})]}),e.jsxs("div",{className:"grid gap-6 md:grid-cols-2 mb-8",children:[e.jsxs("div",{children:[e.jsx("div",{className:`text-xs font-medium uppercase tracking-wider mb-2 ${r?"text-destructive/70":"text-destructive/80"}`,children:"The Problem"}),e.jsx("p",{className:`text-sm leading-relaxed ${r?"text-foreground/60":"text-white/60"}`,children:t.problem})]}),e.jsxs("div",{children:[e.jsx("div",{className:"text-xs font-medium uppercase tracking-wider mb-2 text-primary",children:"The Solution"}),e.jsx("p",{className:`text-sm leading-relaxed ${r?"text-foreground/60":"text-white/60"}`,children:t.solution})]})]}),"code"in t&&t.code?e.jsx("div",{className:"mb-8",children:e.jsx(x,{code:t.code,language:t.language||"python"})}):null,"dashboardFeatures"in t&&t.dashboardFeatures?e.jsx("div",{className:"mb-8",children:e.jsxs("div",{className:`rounded-2xl border p-6 ${r?"border-foreground/10 bg-foreground/[0.02]":"border-white/10 bg-white/5"}`,children:[e.jsx("div",{className:`text-xs font-medium uppercase tracking-wider mb-4 ${r?"text-foreground/40":"text-white/40"}`,children:"Dashboard Capabilities"}),e.jsx("div",{className:"grid gap-3 sm:grid-cols-2",children:t.dashboardFeatures.map(s=>e.jsxs("div",{className:`flex items-start gap-2 text-sm ${r?"text-foreground/60":"text-white/60"}`,children:[e.jsx(h,{className:"h-3.5 w-3.5 mt-0.5 shrink-0 text-primary"}),s]},s))})]})}):null,e.jsx("div",{className:"grid gap-4 sm:grid-cols-3",children:t.results.map(s=>e.jsxs("div",{className:`rounded-xl p-4 text-center ${r?"bg-foreground/[0.03] border border-foreground/5":"bg-white/5 border border-white/10"}`,children:[e.jsx("div",{className:`text-2xl font-bold ${r?"text-foreground":"text-white"}`,children:s.value}),e.jsx("div",{className:`text-xs mt-1 ${r?"text-foreground/40":"text-white/40"}`,children:s.metric}),e.jsx("div",{className:"text-[10px] mt-0.5 text-primary",children:s.detail})]},s.metric))})]})},F=()=>e.jsxs("div",{className:"min-h-screen bg-background",children:[e.jsx(c,{title:"Use Cases",description:m["/use-cases"],path:"/use-cases"}),e.jsx(u,{}),e.jsx("section",{className:"pt-24 pb-12",children:e.jsxs("div",{className:"container mx-auto px-4",children:[e.jsxs(i.div,{className:"max-w-2xl",initial:{opacity:0,y:20},animate:{opacity:1,y:0},transition:{duration:.5},children:[e.jsxs("h1",{className:"text-[clamp(2rem,4vw,3rem)] font-semibold leading-[1.1] text-foreground",children:["What developers build with"," ",e.jsx("span",{className:"text-highlight",children:"Octopoda"})]}),e.jsx("p",{className:"mt-4 text-base text-foreground/60 leading-relaxed max-w-lg",children:"Real use cases, real code. See how developers use Octopoda to manage, monitor, and give their agents persistent memory."})]}),e.jsx(i.div,{className:"mt-8 flex flex-wrap gap-2",initial:{opacity:0},animate:{opacity:1},transition:{delay:.3},children:l.map(t=>{const a=t.icon;return e.jsxs("a",{href:`#${t.id}`,className:"inline-flex items-center gap-2 rounded-full bg-foreground/5 px-4 py-2 text-sm text-foreground/60 hover:bg-foreground/10 hover:text-foreground transition-all",children:[e.jsx(a,{className:"h-3.5 w-3.5"}),t.id.split("-").map(o=>o.charAt(0).toUpperCase()+o.slice(1)).join(" ")]},t.id)})})]})}),e.jsx("section",{className:"pb-20",children:e.jsx("div",{className:"container mx-auto px-4 space-y-8",children:l.map((t,a)=>e.jsx(b,{useCase:t,index:a},t.id))})}),e.jsx("section",{className:"pb-20",children:e.jsx("div",{className:"container mx-auto px-4",children:e.jsxs(i.div,{className:"pos-card-accent text-center py-14",initial:{opacity:0,y:16},whileInView:{opacity:1,y:0},viewport:{once:!0},children:[e.jsx("h2",{className:"text-3xl font-semibold text-foreground md:text-4xl",children:"Ready to take control of your agents?"}),e.jsx("p",{className:"mx-auto mt-4 max-w-md text-base text-foreground/70",children:"Start with any use case. Memory, monitoring, crash recovery, and diagnostics — all included."}),e.jsxs("div",{className:"mt-8 flex flex-col items-center gap-4 sm:flex-row sm:justify-center",children:[e.jsx(n,{to:"/docs/quickstart",children:e.jsx(p,{variant:"hero",size:"lg",children:"Get Started Free →"})}),e.jsx(n,{to:"/docs/quickstart",className:"text-sm text-foreground/60 hover:text-foreground transition-colors underline underline-offset-4",children:"Read the documentation →"})]})]})})}),e.jsx(g,{})]});export{F as default};
