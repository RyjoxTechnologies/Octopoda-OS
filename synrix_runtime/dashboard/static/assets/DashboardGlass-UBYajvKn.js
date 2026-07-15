import{aM as r,aN as e,aU as n,aP as l}from"./index-RsFqQstg.js";import{S as c}from"./search-BJpC_HKc.js";import{B as p}from"./bell-CPwy3SQi.js";import{C as g}from"./chevron-down-CE0RuKpi.js";import{R as x}from"./radio-nNmZY3LU.js";import{C as m}from"./clock-Cv6ueR8h.js";const h=["Overview","Agents","Memory Explorer","Shared Memory","Performance","Analytics","Audit Ledger","Loop Intelligence","Settings"],b=[{name:"support_copilot",pct:92},{name:"research_assist",pct:86},{name:"sales_copilot",pct:74},{name:"code_reviewer",pct:58},{name:"pipeline_sentinel",pct:22}],f=[{name:"support_copilot",status:"registered",score:76.5,ops:147,lat:"182.8ms"},{name:"health_probe",status:"running",score:56.2,ops:9,lat:"77.6ms"},{name:"research_assistant",status:"registered",score:76.2,ops:143,lat:"199.0ms"},{name:"code_reviewer",status:"registered",score:76.5,ops:99,lat:"154.0ms"},{name:"sales_copilot",status:"running",score:71.8,ops:121,lat:"168.3ms"}];function z(){const[i,d]=r.useState(1371173),[t,o]=r.useState(1247);return r.useEffect(()=>{if(!document.getElementById("geist-fonts")){const s=document.createElement("link");s.id="geist-fonts",s.rel="stylesheet",s.href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600;700&display=swap",document.head.appendChild(s)}const a=window.setInterval(()=>{d(s=>s+Math.floor(Math.random()*45+8)),Math.random()<.06&&o(s=>s+1)},900);return()=>clearInterval(a)},[]),e.jsxs("div",{className:"dg-root",children:[e.jsx("style",{children:j}),e.jsx(n,{title:"Dashboard Glass — Design Preview",description:"Glassmorphism dashboard design preview.",noIndex:!0}),e.jsxs("div",{className:"dg-banner",children:["DESIGN PREVIEW · demo data · the live dashboard is untouched ·"," ",e.jsx(l,{to:"/dashboard",children:"open real dashboard"})]}),e.jsxs("div",{className:"dg-frame",children:[e.jsxs("header",{className:"dg-top",children:[e.jsxs("div",{className:"dg-top-row",children:[e.jsxs("div",{className:"dg-brand",children:[e.jsx("span",{className:"dg-brand-dot"}),"Octopoda"]}),e.jsxs("div",{className:"dg-tools",children:[e.jsxs("div",{className:"dg-search",children:[e.jsx(c,{size:13})," Search agents, memories, events"]}),e.jsx("span",{className:"dg-icon-btn",children:e.jsx(p,{size:14})}),e.jsxs("span",{className:"dg-avatar",children:["JR ",e.jsx(g,{size:12})]})]})]}),e.jsx("nav",{className:"dg-tabs",children:h.map((a,s)=>e.jsx("span",{className:s===0?"dg-tab dg-tab-active":"dg-tab",children:a},a))})]}),e.jsxs("main",{className:"dg-main",children:[e.jsxs("div",{className:"dg-head",children:[e.jsxs("div",{children:[e.jsxs("h1",{children:["Overview ",e.jsxs("span",{className:"dg-live",children:[e.jsx(x,{size:11})," Live"]})]}),e.jsx("p",{children:"Real time activity across all connected agents."})]}),e.jsxs("span",{className:"dg-range",children:[e.jsx(m,{size:12})," Last 24h"]})]}),e.jsxs("div",{className:"dg-stats",children:[e.jsxs("div",{className:"dg-card dg-stat",children:[e.jsx("label",{children:"ACTIVE AGENTS"}),e.jsx("b",{children:"24"}),e.jsx("span",{children:"24 total"})]}),e.jsxs("div",{className:"dg-card dg-stat",children:[e.jsx("label",{children:"TOTAL OPS"}),e.jsx("b",{children:i.toLocaleString("en-US")}),e.jsx("span",{children:"across 24 agents"})]}),e.jsxs("div",{className:"dg-card dg-stat",children:[e.jsx("label",{children:"AVG SCORE"}),e.jsx("b",{children:"89.2"}),e.jsx("span",{children:"0 alerting"})]}),e.jsxs("div",{className:"dg-card dg-stat",children:[e.jsx("label",{children:"ANOMALIES"}),e.jsx("b",{children:"3"}),e.jsx("span",{children:"last 24h"})]}),e.jsxs("div",{className:"dg-card dg-stat dg-stat-hero",children:[e.jsx("label",{children:"SAVED BY OCTOPODA"}),e.jsxs("b",{children:["$",t.toLocaleString("en-US")]}),e.jsx("span",{children:"42 loops avoided"})]})]}),e.jsxs("div",{className:"dg-mid",children:[e.jsxs("div",{className:"dg-card dg-panel",children:[e.jsx("h3",{children:"OPERATIONS OVERVIEW"}),b.map(a=>e.jsxs("div",{className:"dg-bar-row",children:[e.jsx("span",{children:a.name}),e.jsx("div",{className:"dg-bar",children:e.jsx("i",{style:{width:`${a.pct}%`}})})]},a.name))]}),e.jsxs("div",{className:"dg-card dg-panel",children:[e.jsx("h3",{children:"AGENT HEALTH"}),e.jsxs("div",{className:"dg-health",children:[e.jsx("div",{className:"dg-donut",children:e.jsxs("span",{children:[e.jsx("b",{children:"24"}),e.jsx("small",{children:"AGENTS"})]})}),e.jsxs("ul",{children:[e.jsxs("li",{children:[e.jsx("i",{className:"dg-dot-ok"})," HEALTHY ",e.jsx("b",{children:"15"})]}),e.jsxs("li",{children:[e.jsx("i",{className:"dg-dot-warn"})," WARNING ",e.jsx("b",{children:"9"})]}),e.jsxs("li",{children:[e.jsx("i",{className:"dg-dot-crit"})," CRITICAL ",e.jsx("b",{children:"0"})]})]})]})]})]}),e.jsxs("div",{className:"dg-bot",children:[e.jsx("div",{className:"dg-card dg-panel",children:e.jsxs("table",{className:"dg-table",children:[e.jsx("thead",{children:e.jsxs("tr",{children:[e.jsx("th",{children:"AGENT"}),e.jsx("th",{children:"STATUS"}),e.jsx("th",{children:"SCORE"}),e.jsx("th",{children:"OPS"}),e.jsx("th",{children:"W. LAT"})]})}),e.jsx("tbody",{children:f.map(a=>e.jsxs("tr",{children:[e.jsxs("td",{children:[e.jsx("i",{className:"dg-dot"})," ",a.name]}),e.jsx("td",{children:e.jsx("span",{className:a.status==="running"?"dg-pill dg-pill-run":"dg-pill",children:a.status})}),e.jsx("td",{children:a.score}),e.jsx("td",{children:a.ops}),e.jsx("td",{children:a.lat})]},a.name))})]})}),e.jsxs("div",{className:"dg-col",children:[e.jsxs("div",{className:"dg-card dg-panel",children:[e.jsxs("h3",{children:["ANOMALIES ",e.jsx("em",{className:"dg-count",children:"3"})]}),e.jsxs("div",{className:"dg-anom",children:[e.jsx("span",{children:"email_drafter"}),e.jsx("em",{children:"REFLECTION LOOP"})]}),e.jsxs("div",{className:"dg-anom",children:[e.jsx("span",{children:"market_scraper"}),e.jsx("em",{children:"TOOL SPAM"})]})]}),e.jsxs("div",{className:"dg-card dg-panel",children:[e.jsxs("h3",{children:["LIVE EVENTS ",e.jsx("em",{className:"dg-stream",children:"streaming"})]}),e.jsxs("div",{className:"dg-ev",children:[e.jsx("b",{children:"1m"})," code_reviewer checkpoint 4211"]}),e.jsxs("div",{className:"dg-ev",children:[e.jsx("b",{children:"2m"})," sales_copilot recall customer:acme"]}),e.jsxs("div",{className:"dg-ev",children:[e.jsx("b",{children:"4m"})," support_copilot loop check passed"]})]})]})]})]})]})]})}const j=`
.dg-root{
  --ink:#F5F2ED;--ink2:rgba(245,242,237,.85);--ink3:rgba(245,242,237,.62);
  --amber:oklch(0.74 0.15 55);
  min-height:100vh;color:var(--ink);
  font-family:'Geist',system-ui,sans-serif;-webkit-font-smoothing:antialiased;
  background:#0A0908 url('/newdesign/assets/hero-sunset.png') center/cover fixed no-repeat;
  position:relative;
}
.dg-root::before{content:"";position:fixed;inset:0;background:linear-gradient(180deg,rgba(10,9,8,.5),rgba(10,9,8,.72));backdrop-filter:blur(7px);-webkit-backdrop-filter:blur(7px);pointer-events:none}
.dg-root *{box-sizing:border-box}
.dg-root h1,.dg-root h2,.dg-root h3{color:var(--ink)}
.dg-banner{
  position:relative;z-index:3;text-align:center;padding:8px 14px;
  font-family:'Geist Mono',monospace;font-size:10.5px;letter-spacing:.12em;
  background:rgba(222,140,66,.14);border-bottom:1px solid rgba(222,140,66,.3);color:var(--ink2);
}
.dg-banner a{color:var(--amber);text-decoration:none;font-weight:600}

.dg-frame{position:relative;z-index:2;max-width:1280px;margin:0 auto;padding:20px 24px 48px}

/* glass recipe */
.dg-card,.dg-top{
  background:rgba(14,10,8,.55);
  backdrop-filter:blur(22px) saturate(150%);-webkit-backdrop-filter:blur(22px) saturate(150%);
  border:1px solid rgba(255,255,255,.14);border-radius:16px;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 24px 60px -24px rgba(0,0,0,.6);
}

/* top bar */
.dg-top{padding:14px 18px 0;margin-bottom:22px}
.dg-top-row{display:flex;align-items:center;justify-content:space-between;gap:20px}
.dg-brand{display:flex;align-items:center;gap:9px;font-weight:600;font-size:17px;letter-spacing:-.02em}
.dg-brand-dot{width:18px;height:18px;border-radius:50%;background:var(--amber);box-shadow:0 0 16px rgba(222,140,66,.5)}
.dg-tools{display:flex;align-items:center;gap:10px}
.dg-search{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--ink3);font-family:'Geist Mono',monospace;border:1px solid rgba(255,255,255,.12);border-radius:10px;padding:8px 12px;min-width:280px}
.dg-icon-btn{display:grid;place-items:center;width:32px;height:32px;border-radius:9px;border:1px solid rgba(255,255,255,.14);color:var(--ink2)}
.dg-avatar{display:flex;align-items:center;gap:5px;font-size:12px;font-weight:600;padding:7px 11px;border-radius:99px;border:1px solid rgba(255,255,255,.14)}
.dg-tabs{display:flex;gap:4px;margin-top:12px;overflow-x:auto;padding-bottom:0}
.dg-tab{
  white-space:nowrap;font-size:13px;color:var(--ink2);padding:10px 14px 12px;cursor:default;
  border-bottom:2px solid transparent;
}
.dg-tab-active{color:var(--ink);font-weight:500;border-bottom-color:var(--amber)}

/* head */
.dg-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px}
.dg-head h1{margin:0;font-family:'Geist Mono',monospace;font-size:24px;font-weight:700;display:flex;align-items:center;gap:12px}
.dg-live{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:500;color:#7ddb8a}
.dg-head p{margin:6px 0 0;font-family:'Geist Mono',monospace;font-size:12px;color:var(--ink3)}
.dg-range{display:inline-flex;align-items:center;gap:7px;font-family:'Geist Mono',monospace;font-size:11.5px;color:var(--ink2);border:1px solid rgba(255,255,255,.16);border-radius:99px;padding:7px 14px;background:rgba(14,10,8,.5)}

/* stats */
.dg-stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:14px}
.dg-stat{padding:14px 15px}
.dg-stat label{font-family:'Geist Mono',monospace;font-size:9.5px;letter-spacing:.1em;color:var(--amber)}
.dg-stat b{display:block;font-family:'Geist Mono',monospace;font-size:24px;font-weight:600;margin-top:8px}
.dg-stat span{display:block;font-family:'Geist Mono',monospace;font-size:10px;color:var(--ink3);margin-top:3px}
.dg-amber{color:var(--amber)}
.dg-stat-hero{border-color:oklch(0.74 0.15 55 / .5);background:oklch(0.74 0.15 55 / .08);box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 0 32px -8px oklch(0.74 0.15 55 / .35)}
.dg-stat-hero label{color:oklch(0.78 0.13 55)}

/* panels */
.dg-mid{display:grid;grid-template-columns:1.6fr 1fr;gap:12px;margin-bottom:14px}
.dg-bot{display:grid;grid-template-columns:1.6fr 1fr;gap:12px}
.dg-col{display:flex;flex-direction:column;gap:12px}
.dg-panel{padding:16px 18px}
.dg-panel h3{margin:0 0 14px;font-family:'Geist Mono',monospace;font-size:11px;letter-spacing:.1em;font-weight:600;color:var(--amber);display:flex;align-items:center;gap:8px}
.dg-bar-row{display:grid;grid-template-columns:130px 1fr;gap:12px;align-items:center;margin-bottom:9px}
.dg-bar-row span{font-family:'Geist Mono',monospace;font-size:11px;color:var(--ink2)}
.dg-bar{height:9px;border-radius:99px;background:rgba(255,255,255,.06)}
.dg-bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,oklch(0.74 0.15 55 / .9),oklch(0.80 0.13 62 / .75))}

.dg-health{display:flex;align-items:center;justify-content:center;gap:26px;height:calc(100% - 28px);min-height:120px}
.dg-donut{width:96px;height:96px;border-radius:50%;background:conic-gradient(#7ddb8a 0 62%,var(--amber) 62% 100%);display:grid;place-items:center}
.dg-donut span{width:70px;height:70px;border-radius:50%;background:rgba(14,10,8,.85);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;text-align:center;line-height:1}
.dg-donut b{font-family:'Geist Mono',monospace;font-size:19px}
.dg-donut small{font-size:7.5px;letter-spacing:.14em;color:var(--ink3)}
.dg-health ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:9px;font-family:'Geist Mono',monospace;font-size:11px;color:var(--ink2)}
.dg-health li{display:flex;align-items:center;gap:8px}
.dg-health b{color:var(--ink);margin-left:4px}
.dg-health i{width:7px;height:7px;border-radius:50%}
.dg-dot-ok{background:#7ddb8a}.dg-dot-warn{background:var(--amber)}.dg-dot-crit{background:#e5634f}

/* table */
.dg-table{width:100%;border-collapse:collapse;font-family:'Geist Mono',monospace;font-size:11.5px}
.dg-table th{text-align:left;font-size:9.5px;letter-spacing:.1em;color:var(--amber);font-weight:500;padding:0 10px 10px;border-bottom:1px solid rgba(255,255,255,.08)}
.dg-table td{padding:11px 10px;border-bottom:1px solid rgba(255,255,255,.05);color:var(--ink2)}
.dg-table tr:last-child td{border-bottom:0}
.dg-table td:first-child{color:var(--ink)}
.dg-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--amber);margin-right:7px;vertical-align:1px}
.dg-pill{font-size:10px;border:1px solid rgba(255,255,255,.16);border-radius:99px;padding:3.5px 10px;color:var(--ink2)}
.dg-pill-run{border-color:rgba(125,219,138,.5);color:#7ddb8a}

/* anomalies + events */
.dg-count{font-style:normal;margin-left:auto;background:var(--amber);color:#0A0908;border-radius:6px;font-size:10.5px;font-weight:700;padding:1.5px 7px}
.dg-anom{display:flex;justify-content:space-between;align-items:center;font-family:'Geist Mono',monospace;font-size:11.5px;color:var(--ink2);padding:8px 0;border-bottom:1px solid rgba(255,255,255,.05)}
.dg-anom:last-child{border-bottom:0}
.dg-anom em{font-style:normal;font-size:9.5px;letter-spacing:.08em;color:var(--amber);border:1px solid oklch(0.74 0.15 55 / .45);border-radius:6px;padding:3px 8px}
.dg-stream{font-style:normal;margin-left:auto;font-size:10px;letter-spacing:.06em;color:#7ddb8a;font-weight:500}
.dg-ev{font-family:'Geist Mono',monospace;font-size:11px;color:var(--ink2);padding:7px 0;border-bottom:1px solid rgba(255,255,255,.05)}
.dg-ev:last-child{border-bottom:0}
.dg-ev b{color:var(--ink3);font-weight:500;margin-right:8px}

@media (max-width:1000px){
  .dg-search{min-width:0;flex:1}
  .dg-stats{grid-template-columns:repeat(2,1fr)}
  .dg-mid,.dg-bot{grid-template-columns:1fr}
}
`;export{z as default};
