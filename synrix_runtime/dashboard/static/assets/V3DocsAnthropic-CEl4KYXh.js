import{aN as e,aU as a}from"./index-RsFqQstg.js";import{u as i,a as n,D as c,C as t,I as o,b as d,P as l}from"./V3DocsShared-BKwaCxO9.js";function u(){const{prev:s,next:r}=i();return e.jsxs(n,{children:[e.jsx(a,{title:"Anthropic — Octopodas Docs",path:"/docs/anthropic",description:"Persistent memory, loop detection, audit trails & crash recovery for Anthropic Claude agents — automatic, in 2 lines."}),e.jsx(c,{eyebrow:"Framework",title:"Anthropic",lede:"Persistent memory, loop detection, audit trails & crash recovery for Anthropic Claude agents — automatic, in 2 lines.",meta:["Python 3.9+","~1 min"]}),e.jsx("h2",{children:"1. Install"}),e.jsx(t,{children:"pip install octopoda anthropic"}),e.jsxs("h2",{children:["2. Add 2 lines ",e.jsxs("span",{style:{fontWeight:400,color:"var(--v3-ink-3)"},children:["(set ",e.jsx(o,{children:"OCTOPODA_API_KEY"})," first — see ",e.jsx("a",{href:"/docs/quickstart",style:{color:"var(--v3-accent)"},children:"Quickstart"}),")"]})]}),e.jsx(t,{lang:"python",children:`import octopoda

octopoda.init()   # reads OCTOPODA_API_KEY; auto-detects the Anthropic-image Anthropic SDK

# ↓ your existing Claude code, unchanged ↓
from anthropic import Anthropic

client = Anthropic()

client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=512,
    messages=[{"role": "user", "content": "My name is Alice and I love sailing."}],
)`}),e.jsx("p",{children:"On startup you'll see:"}),e.jsx(t,{children:`[octopoda] auto-detected: anthropic
[octopoda] agent_id: auto
[octopoda] dashboard: https://octopodas.com/dashboard`}),e.jsx("p",{children:"Octopoda recalls relevant memory and injects it into your Claude prompts, captures new facts, and runs loop + audit guards — automatically. No OpenAI key needed — extraction runs server-side, free for your first 2000 extractions."}),e.jsxs(d,{tone:"info",title:"Auto-detection",children:[e.jsx(o,{children:"octopoda.init()"})," recognises the Anthropic SDK by import signature. No extra config required."]}),e.jsx(l,{prev:s,next:r})]})}export{u as default};
