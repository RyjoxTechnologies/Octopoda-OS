import{aN as e,aU as n}from"./index-RsFqQstg.js";import{u as i,a as c,D as l,C as t,I as o,b as s,P as d}from"./V3DocsShared-BKwaCxO9.js";function u(){const{prev:a,next:r}=i();return e.jsxs(c,{children:[e.jsx(n,{title:"Quickstart — Octopodas Docs",path:"/docs/quickstart",description:"Give any AI agent persistent memory, loop detection, audit trails and crash recovery in 2 lines — with no extra API keys."}),e.jsx(l,{eyebrow:"Start here",title:"Quickstart",lede:"Give any AI agent persistent memory, loop detection, audit trails & crash recovery — in 2 lines, with no extra API keys.",meta:["Python 3.9+","~30 sec"]}),e.jsx("h2",{children:"1. Install"}),e.jsx(t,{children:"pip install octopoda"}),e.jsx("h2",{children:"2. Get your key"}),e.jsxs("p",{children:["Sign up at ",e.jsx(o,{children:"octopodas.com/dashboard"})," (free), then:"]}),e.jsx(t,{children:'export OCTOPODA_API_KEY="sk-octopoda-..."'}),e.jsx("h2",{children:"3. Add 2 lines"}),e.jsx(t,{lang:"python",children:`import octopoda
octopoda.init()

# ↓ your existing agent code, unchanged ↓
from openai import OpenAI

client = OpenAI()
client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "My name is Alice and I love sailing."}],
)`}),e.jsx("p",{children:"On startup you'll see:"}),e.jsx(t,{children:`[octopoda] auto-detected: openai
[octopoda] agent_id: auto
[octopoda] dashboard: https://octopodas.com/dashboard
[octopoda] recall budget: 200 tokens/call | extraction: every 5 turns (server-side, free tier)`}),e.jsx("p",{children:"Octopoda now recalls and injects relevant memory, captures new facts, watches for runaway loops, and writes a tamper-evident audit trail — automatically. Watch it live in your dashboard."}),e.jsx(s,{tone:"info",title:"🔑 No OpenAI key?",children:"You still get memory — extraction runs on our servers, free for your first 2000 extractions."}),e.jsxs(s,{tone:"success",title:"🏠 Prefer local / no signup?",children:["See ",e.jsx(o,{children:"Vanilla Python"})," — it runs fully offline with no key."]}),e.jsx(d,{prev:a,next:r})]})}export{u as default};
