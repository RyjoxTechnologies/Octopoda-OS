import{aN as e,aP as l,aY as i,aM as d,a_ as p,a$ as v,b1 as x}from"./index-RsFqQstg.js";const n=[{label:"Get started",items:[{to:"/docs",label:"Overview"},{to:"/docs/quickstart",label:"Quickstart"},{to:"/docs/setup-with-ai",label:"Using AI or Assisted Coding Start Here!"},{to:"/docs/getting-started",label:"Getting started"}]},{label:"Frameworks",items:[{to:"/docs/vanilla-python",label:"Vanilla Python"},{to:"/docs/langchain",label:"LangChain"},{to:"/docs/crewai",label:"CrewAI"},{to:"/docs/autogen",label:"AutoGen"},{to:"/docs/openai-assistants",label:"OpenAI Assistants API"},{to:"/docs/openai-agents-sdk",label:"OpenAI Agents SDK"},{to:"/docs/anthropic",label:"Anthropic"},{to:"/docs/mcp",label:"MCP (Claude, Cursor…)"},{to:"/docs/rest-api",label:"REST API / Webhooks"}]},{label:"After install",items:[{to:"/docs/cloud-vs-local",label:"Cloud vs local mode"},{to:"/docs/free-tier-extraction",label:"Free tier & extraction"},{to:"/docs/troubleshooting",label:"Troubleshooting"},{to:"/docs/verified",label:"What is verified"},{to:"/docs/support",label:"Still stuck"}]}],u=({children:a,lang:o})=>e.jsx("pre",{className:"v3-code","data-lang":o||"bash",children:e.jsx("code",{children:a})}),f=({children:a})=>e.jsx("code",{className:"v3-icode",children:a}),h=({tone:a="info",title:o,children:t})=>e.jsxs("div",{className:`v3-callout v3-callout-${a}`,children:[e.jsx("div",{className:"v3-callout-title",children:o}),e.jsx("div",{className:"v3-callout-body",children:t})]}),k=({eyebrow:a,title:o,lede:t,meta:r})=>e.jsxs("header",{className:"v3-docs-hero",children:[e.jsxs("span",{className:"v3-eyebrow",children:[e.jsx("span",{className:"v3-dot"})," ",a]}),e.jsx("h1",{children:o}),e.jsx("p",{className:"v3-docs-lede",children:t}),r&&r.length>0&&e.jsx("div",{className:"v3-docs-meta",children:r.map((s,c)=>e.jsxs("span",{className:"v3-docs-meta-item",children:[c>0&&e.jsx("span",{className:"v3-dot-sep",children:"•"}),e.jsx("span",{children:s})]},c))})]}),g=()=>{const{pathname:a}=i();return e.jsx("aside",{className:"v3-docs-toc",children:e.jsx("div",{className:"v3-docs-toc-inner",children:n.map(o=>e.jsxs("div",{className:"v3-docs-toc-group",children:[e.jsx("div",{className:"v3-docs-toc-label",children:o.label}),e.jsx("ul",{children:o.items.map(t=>{const r=t.to==="/docs/quickstart",s=[a===t.to?"is-active":"",r?"is-highlight":""].filter(Boolean).join(" ");return e.jsx("li",{children:e.jsx(l,{to:t.to,className:s,children:t.label})},t.to)})})]},o.label))})})},w=({prev:a,next:o})=>e.jsxs("nav",{className:"v3-docs-prevnext",children:[a?e.jsxs(l,{to:a.to,className:"v3-docs-prevnext-card",children:[e.jsx("span",{className:"v3-docs-prevnext-label",children:"← Previous"}),e.jsx("span",{className:"v3-docs-prevnext-title",children:a.label})]}):e.jsx("span",{}),o?e.jsxs(l,{to:o.to,className:"v3-docs-prevnext-card v3-docs-prevnext-next",children:[e.jsx("span",{className:"v3-docs-prevnext-label",children:"Next →"}),e.jsx("span",{className:"v3-docs-prevnext-title",children:o.label})]}):e.jsx("span",{})]}),y=({children:a})=>{const{pathname:o}=i();return d.useEffect(()=>{window.scrollTo({top:0,behavior:"instant"})},[o]),e.jsxs(p,{children:[e.jsx("style",{children:b}),e.jsx(v,{}),e.jsx("main",{className:"v3-wrap v3-docs-wrap",children:e.jsxs("div",{className:"v3-docs-grid",children:[e.jsx(g,{}),e.jsx("article",{className:"v3-docs-article",children:a})]})}),e.jsx(x,{})]})};function j(){const{pathname:a}=i(),o=n.flatMap(r=>r.items),t=o.findIndex(r=>r.to===a);return{prev:t>0?o[t-1]:void 0,next:t>=0&&t<o.length-1?o[t+1]:void 0}}const b=`
  .v3-docs-wrap{position:relative;z-index:1;padding-top:48px;padding-bottom:64px}

  /* Hero */
  .v3-docs-hero{max-width:880px;margin:8px 0 40px}
  .v3-docs-hero h1{font-size:clamp(36px,4.6vw,56px);margin:18px 0 18px;letter-spacing:-0.02em}
  .v3-docs-lede{font-size:17px;line-height:1.65;color:var(--v3-ink-2);max-width:720px}
  .v3-docs-meta{display:flex;align-items:center;gap:10px;margin-top:22px;color:var(--v3-ink-3);font-size:13px;flex-wrap:wrap}
  .v3-docs-meta-item{display:inline-flex;align-items:center;gap:10px}
  .v3-dot-sep{color:var(--v3-ink-3);opacity:.5}

  /* Grid */
  .v3-docs-grid{display:grid;grid-template-columns:240px 1fr;gap:64px;align-items:start}
  @media (max-width:980px){.v3-docs-grid{grid-template-columns:1fr;gap:24px}}

  /* TOC */
  .v3-docs-toc{position:sticky;top:104px;align-self:start;max-height:calc(100vh - 140px);overflow-y:auto}
  .v3-docs-toc::-webkit-scrollbar{width:6px}
  .v3-docs-toc::-webkit-scrollbar-thumb{background:rgba(255,255,255,.08);border-radius:999px}
  .v3-docs-toc-inner{display:flex;flex-direction:column;gap:22px;padding-right:8px}
  .v3-docs-toc-group .v3-docs-toc-label{
    font-size:11px;letter-spacing:.14em;text-transform:uppercase;
    color:var(--v3-ink-3);margin-bottom:8px;padding-left:12px;
  }
  .v3-docs-toc ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column}
  .v3-docs-toc a{
    display:block;padding:6px 12px;border-left:2px solid transparent;
    color:var(--v3-ink-3);font-size:13.5px;line-height:1.45;
    transition:color .15s ease,border-color .15s ease;
    text-decoration:none;
  }
  .v3-docs-toc a:hover{color:var(--v3-ink-2)}
  .v3-docs-toc a.is-active{color:var(--v3-accent);border-left-color:var(--v3-accent)}
  .v3-docs-toc a.is-highlight{color:#f97316;font-weight:600}
  .v3-docs-toc a.is-highlight:hover{color:#fb923c}
  .v3-docs-toc a.is-highlight.is-active{color:#f97316;border-left-color:#f97316}
  @media (max-width:980px){.v3-docs-toc{position:static;max-height:none}}

  /* Article */
  .v3-docs-article{min-width:0;display:flex;flex-direction:column;gap:18px}
  .v3-docs-article h2{font-size:clamp(22px,2.6vw,28px);margin:32px 0 6px;letter-spacing:-0.015em;color:var(--v3-ink)}
  .v3-docs-article h3{font-size:17px;font-weight:600;color:var(--v3-ink);margin:18px 0 4px;letter-spacing:-0.01em}
  .v3-docs-article p{font-size:15.5px;line-height:1.7;color:var(--v3-ink-2);margin:0}

  /* Lists */
  .v3-list{margin:0;padding:0 0 0 22px;display:flex;flex-direction:column;gap:8px;color:var(--v3-ink-2);font-size:15.5px;line-height:1.7}
  .v3-list li::marker{color:var(--v3-accent)}

  /* Code */
  .v3-code{
    position:relative;margin:0;padding:18px 20px;border-radius:14px;
    background:#0a0a0b;border:1px solid var(--v3-line);
    overflow-x:auto;font-family:'Geist Mono',ui-monospace,monospace;
    font-size:13.5px;line-height:1.65;color:#e7e7ea;
  }
  .v3-code::before{
    content:attr(data-lang);position:absolute;top:10px;right:14px;
    font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;
    color:var(--v3-ink-3);font-family:'Geist',sans-serif;
  }
  .v3-code code{background:none;padding:0;border:0;color:inherit;font-size:inherit}
  .v3-icode{
    background:rgba(255,255,255,.06);border:1px solid var(--v3-line);
    padding:1px 6px;border-radius:6px;
    font-family:'Geist Mono',ui-monospace,monospace;font-size:.88em;color:#fff;
  }

  /* Callouts */
  .v3-callout{
    padding:16px 18px;border-radius:14px;border:1px solid var(--v3-line);
    background:rgba(255,255,255,.02);display:flex;flex-direction:column;gap:6px;
  }
  .v3-callout-title{font-weight:600;font-size:13.5px;letter-spacing:-0.005em}
  .v3-callout-body{font-size:14.5px;line-height:1.6;color:var(--v3-ink-2)}
  .v3-callout-info{border-left:3px solid #60a5fa}
  .v3-callout-info .v3-callout-title{color:#93c5fd}
  .v3-callout-warn{border-left:3px solid #fbbf24;background:rgba(251,191,36,.04)}
  .v3-callout-warn .v3-callout-title{color:#fbbf24}
  .v3-callout-success{border-left:3px solid #4ade80}
  .v3-callout-success .v3-callout-title{color:#86efac}

  /* Two col */
  .v3-twocol{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  @media (max-width:760px){.v3-twocol{grid-template-columns:1fr}}
  .v3-twocol-card{
    padding:18px;border:1px solid var(--v3-line);border-radius:14px;
    background:rgba(255,255,255,.015);display:flex;flex-direction:column;gap:8px;
  }
  .v3-twocol-card h4{font-size:14px;font-weight:600;color:var(--v3-ink);margin:0;letter-spacing:-0.005em}

  /* Hub cards */
  .v3-docs-hub-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;margin-top:8px}
  .v3-docs-hub-card{
    display:flex;flex-direction:column;gap:8px;padding:20px;
    border:1px solid var(--v3-line);border-radius:14px;
    background:rgba(255,255,255,.015);text-decoration:none;
    transition:border-color .15s ease,background .15s ease,transform .15s ease;
  }
  .v3-docs-hub-card:hover{border-color:rgba(222,140,66,.45);background:rgba(222,140,66,.04);transform:translateY(-1px)}
  .v3-docs-hub-card-eyebrow{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--v3-ink-3)}
  .v3-docs-hub-card-title{font-size:16px;font-weight:600;color:var(--v3-ink);letter-spacing:-0.01em}
  .v3-docs-hub-card-desc{font-size:13.5px;line-height:1.55;color:var(--v3-ink-2)}

  /* Troubleshooting accordion */
  .v3-trouble{display:flex;flex-direction:column;gap:10px}
  .v3-trouble details{
    border:1px solid var(--v3-line);border-radius:14px;
    background:rgba(255,255,255,.015);overflow:hidden;
  }
  .v3-trouble summary{
    list-style:none;cursor:pointer;padding:14px 18px;
    font-size:14.5px;font-weight:500;color:var(--v3-ink);
    display:flex;align-items:center;justify-content:space-between;gap:12px;
    transition:background .15s ease;
  }
  .v3-trouble summary::-webkit-details-marker{display:none}
  .v3-trouble summary:hover{background:rgba(255,255,255,.02)}
  .v3-trouble summary::after{
    content:"+";color:var(--v3-accent);font-weight:400;font-size:18px;
  }
  .v3-trouble details[open] summary::after{content:"−"}
  .v3-trouble details > *:not(summary){padding:0 18px 16px}
  .v3-trouble details > p,
  .v3-trouble details > ol,
  .v3-trouble details > ul{margin-top:0;color:var(--v3-ink-2);font-size:14.5px;line-height:1.65}
  .v3-trouble details pre.v3-code{margin:10px 18px 16px;padding:14px 16px}

  /* Table */
  .v3-table-wrap{
    border:1px solid var(--v3-line);border-radius:14px;overflow:hidden;
    background:rgba(255,255,255,.015);
  }
  .v3-table{width:100%;border-collapse:collapse;font-size:14px}
  .v3-table th,.v3-table td{
    text-align:left;padding:12px 18px;border-bottom:1px solid var(--v3-line);
    color:var(--v3-ink-2);
  }
  .v3-table th{
    color:var(--v3-ink-3);font-weight:500;text-transform:uppercase;
    letter-spacing:.1em;font-size:11px;background:rgba(255,255,255,.02);
  }
  .v3-table td:first-child{font-family:'Geist Mono',ui-monospace,monospace;color:var(--v3-ink)}
  .v3-table tr:last-child td{border-bottom:0}

  /* Prev/Next */
  .v3-docs-prevnext{
    display:grid;grid-template-columns:1fr 1fr;gap:14px;
    margin-top:48px;padding-top:24px;border-top:1px solid var(--v3-line);
  }
  @media (max-width:680px){.v3-docs-prevnext{grid-template-columns:1fr}}
  .v3-docs-prevnext-card{
    display:flex;flex-direction:column;gap:4px;padding:16px 18px;
    border:1px solid var(--v3-line);border-radius:12px;text-decoration:none;
    background:rgba(255,255,255,.015);
    transition:border-color .15s ease,background .15s ease;
  }
  .v3-docs-prevnext-card:hover{border-color:rgba(222,140,66,.4);background:rgba(222,140,66,.03)}
  .v3-docs-prevnext-next{text-align:right}
  .v3-docs-prevnext-label{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--v3-ink-3)}
  .v3-docs-prevnext-title{font-size:15px;font-weight:600;color:var(--v3-ink)}

  .v3-cta-row{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px}
`;export{u as C,k as D,f as I,w as P,n as V,y as a,h as b,j as u};
