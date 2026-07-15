import{aM as u,aN as e,a_ as b,aU as y,aV as j,a$ as k,aP as w,b1 as N,aR as S,aS as A,b2 as z,b3 as I,b4 as x}from"./index-RsFqQstg.js";import{A as L,a as q,b as M,c as C}from"./accordion-DfRWHrzy.js";import{U as v,P as r}from"./plans-D8XRPtkA.js";import{m as o}from"./proxy-DETd9jo6.js";import{U as F}from"./users-CyDsxrYR.js";import{Z as P}from"./zap-D4FUf74J.js";import{T as R}from"./trending-up-DzJPPe8m.js";import"./index-5PUimyy3.js";import"./chevron-down-CE0RuKpi.js";const E=[{name:r.free.name,planId:"free",audience:"For side projects",monthly:r.free.monthly,annual:r.free.annualMonthly,scale:[{num:r.free.agents,unit:"agents"},{num:r.free.apiRateLimit,unit:"api rate"}],features:["Full product — every feature, no functionality limits","Community support (GitHub + Discord)","Local SQLite or cloud sync — your choice"],story:'"Sign up, pip install octopoda, ship in an afternoon."',cta:"Start free",riskReversal:"No credit card required • Free forever"},{name:r.pro.name,planId:"pro",audience:"For individual developers",monthly:r.pro.monthly,annual:r.pro.annualMonthly,scale:[{num:r.pro.agents,unit:"agents"},{num:r.pro.apiRateLimit,unit:"api rate"}],features:["Everything in Free","Email support within 1 business day","Priority bug-fix queue"],story:`"You're past the prototype. Your agents are running for real users."`,cta:"Start Pro",riskReversal:"Cancel anytime • 14-day money-back guarantee"},{name:r.business.name,planId:"business",audience:"For teams",monthly:r.business.monthly,annual:r.business.annualMonthly,scale:[{num:r.business.agents,unit:"agents"},{num:r.business.apiRateLimit,unit:"api rate"}],features:["Everything in Pro","Priority support (4h business-hours response)","Webhooks","99.5% uptime SLA"],story:'"Your team is building on Octopoda every day. This is where you live."',cta:"Start Business",riskReversal:"Cancel anytime • 14-day money-back guarantee",featured:!0,badge:"Most Popular"},{name:r.scale.name,planId:"scale",audience:"For AI-first teams",monthly:r.scale.monthly,annual:r.scale.annualMonthly,scale:[{num:r.scale.agents,unit:"agents"},{num:r.scale.apiRateLimit,unit:"api rate"}],features:["Everything in Business","Dedicated shared Slack channel (same-day, any time zone)","99.9% uptime SLA + quarterly strategy review","SSO/SAML"],story:'"Agents are core to your product, not a feature."',cta:"Start Scale",riskReversal:"Cancel anytime • 14-day money-back guarantee"}],T=[{name:"Agents",free:r.free.agents,pro:r.pro.agents,business:r.business.agents,scale:r.scale.agents,enterprise:r.enterprise.agents},{name:"Semantic search",free:!0,pro:!0,business:!0,scale:!0,enterprise:!0},{name:"Loop detection",free:!0,pro:!0,business:!0,scale:!0,enterprise:!0},{name:"Agent messaging",free:!0,pro:!0,business:!0,scale:!0,enterprise:!0},{name:"Goal tracking",free:!0,pro:!0,business:!0,scale:!0,enterprise:!0},{name:"Memory health scoring",free:!0,pro:!0,business:!0,scale:!0,enterprise:!0},{name:"Knowledge graph",free:!0,pro:!0,business:!0,scale:!0,enterprise:!0},{name:"Temporal versioning",free:!0,pro:!0,business:!0,scale:!0,enterprise:!0},{name:"Crash recovery",free:!0,pro:!0,business:!0,scale:!0,enterprise:!0},{name:"Memory export/import",free:!0,pro:!0,business:!0,scale:!0,enterprise:!0},{name:"Shared memory spaces",free:r.free.sharedMemorySpaces,pro:r.pro.sharedMemorySpaces,business:r.business.sharedMemorySpaces,scale:r.scale.sharedMemorySpaces,enterprise:r.enterprise.sharedMemorySpaces},{name:"Webhooks",free:r.free.webhooks,pro:r.pro.webhooks,business:r.business.webhooks,scale:r.scale.webhooks,enterprise:r.enterprise.webhooks},{name:"Auto-tagging",free:!0,pro:!0,business:!0,scale:!0,enterprise:!0},{name:"Filtered search",free:!0,pro:!0,business:!0,scale:!0,enterprise:!0},{name:"Memory consolidation",free:!0,pro:!0,business:!0,scale:!0,enterprise:!0},{name:"Team members",free:r.free.teamMembers,pro:r.pro.teamMembers,business:r.business.teamMembers,scale:r.scale.teamMembers,enterprise:r.enterprise.teamMembers},{name:"API rate limit",free:r.free.apiRateLimit,pro:r.pro.apiRateLimit,business:r.business.apiRateLimit,scale:r.scale.apiRateLimit,enterprise:r.enterprise.apiRateLimit},{name:"Support",free:r.free.support,pro:r.pro.support,business:r.business.support,scale:r.scale.support,enterprise:r.enterprise.support},{name:"Uptime SLA",free:r.free.uptimeSla,pro:r.pro.uptimeSla,business:r.business.uptimeSla,scale:r.scale.uptimeSla,enterprise:r.enterprise.uptimeSla},{name:"SSO/SAML",free:r.free.sso,pro:r.pro.sso,business:r.business.sso,scale:r.scale.sso,enterprise:r.enterprise.sso}],O=[{q:"Is there really a free tier?",a:"Yes. 5 agents, fair-use memory, semantic search, loop detection, and crash recovery. No credit card required. Free forever."},{q:"How much memory do I get?",a:"Memory is fair-use on every plan — there is no hard cap. Plans differ on number of agents, API rate limit, seats, support, SLA, webhooks, and SSO."},{q:"How do AI extractions work?",a:"Every account gets 2,000 free platform AI extractions. After that, plug in your own OpenAI / Anthropic / Ollama key for unlimited extractions at provider cost."},{q:"Can I switch plans anytime?",a:"Yes. Upgrades take effect immediately. Downgrades take effect at the end of your billing period. Your data is always preserved."},{q:"Do you offer refunds?",a:"Yes, within 14 days of any payment. No questions asked."},{q:"Is my data safe?",a:"Every tenant gets a separate isolated database with row-level security. All data is encrypted in transit (TLS) and at rest. We're GDPR compliant with full data export and deletion endpoints."}],n=({value:t})=>t===!0?e.jsx(S,{className:"h-4 w-4 mx-auto",style:{color:"var(--v3-accent)"}}):t===!1?e.jsx(A,{className:"h-4 w-4 mx-auto",style:{color:"var(--v3-ink-3)",opacity:.4}}):e.jsx("span",{style:{fontSize:"13px",color:"var(--v3-ink)"},children:t}),U=`
  .v3-pricing-wrap{position:relative; z-index:1; padding:96px 0 80px}
  .v3-pricing-head{text-align:center; max-width:760px; margin:0 auto}
  .v3-pricing-head h1{font-size:clamp(36px, 5vw, 60px); font-weight:600; letter-spacing:-0.03em; line-height:1.05; margin:18px 0 14px; color:var(--v3-ink)}
  .v3-pricing-head h1 em{font-style:normal; color:var(--v3-accent)}
  .v3-pricing-head .sub{color:var(--v3-ink-3); font-size:16px; margin:0}

  .v3-bill-toggle{
    display:inline-flex; align-items:center; gap:2px;
    padding:4px; border-radius:999px; background:#0e0e10;
    border:1px solid var(--v3-line); margin-top:26px; position:relative;
  }
  .v3-bill-toggle button{
    background:transparent; border:0; color:var(--v3-ink-3);
    padding:9px 22px; border-radius:999px; font-size:13px; font-weight:500;
    cursor:pointer; font-family:inherit; transition:color .15s, background .15s;
  }
  .v3-bill-toggle button.on{background:#fff; color:#0b0b0c}
  .v3-bill-toggle .save{
    position:absolute; top:-10px; left:14px;
    background:var(--v3-accent); color:#0b0b0c;
    font-size:10px; font-weight:700; padding:2px 8px; border-radius:999px;
  }

  .v3-price-grid{
    display:grid; grid-template-columns:repeat(4,1fr); gap:14px;
    margin-top:48px;
  }
  @media (max-width: 980px){.v3-price-grid{grid-template-columns:repeat(2,1fr)}}
  @media (max-width: 580px){.v3-price-grid{grid-template-columns:1fr}}

  .v3-price-card{
    position:relative; background:#0e0e10; border:1px solid var(--v3-line);
    border-radius:20px; padding:24px 20px 20px;
    display:flex; flex-direction:column; gap:14px;
    transition:border-color .3s, transform .3s;
  }
  .v3-price-card.featured{
    transform:translateY(-14px);
    border-color:rgba(240,85,35,.55);
    box-shadow:0 20px 60px -20px rgba(240,85,35,.35), inset 0 0 0 1px rgba(240,85,35,.15);
  }
  @media (max-width: 980px){.v3-price-card.featured{transform:none}}
  .v3-price-card .pop-badge{
    position:absolute; top:-12px; left:50%; transform:translateX(-50%);
    background:var(--v3-accent); color:#0b0b0c;
    font-size:10px; font-weight:700; letter-spacing:.14em; text-transform:uppercase;
    padding:5px 12px; border-radius:999px;
    box-shadow:0 6px 20px -6px rgba(240,85,35,.6);
  }
  .v3-price-card .eyebrow-mini{
    font-size:9.5px; letter-spacing:.14em; text-transform:uppercase;
    color:var(--v3-ink-3); font-weight:500;
  }
  .v3-price-card.featured .eyebrow-mini{color:var(--v3-accent)}
  .v3-price-card h3{margin:0; font-size:22px; font-weight:500; letter-spacing:-.01em; color:var(--v3-ink)}
  .v3-price-card .price{display:flex; align-items:baseline; gap:4px; margin:2px 0}
  .v3-price-card .price .n{font-size:38px; font-weight:600; letter-spacing:-.03em; line-height:1; color:var(--v3-ink)}
  .v3-price-card .price .u{font-size:12px; color:var(--v3-ink-3)}

  .v3-scale-line{
    display:flex; align-items:baseline; gap:8px; flex-wrap:wrap;
    padding:10px 12px; margin:2px 0 4px;
    background:rgba(240,85,35,.08);
    border:1px solid rgba(240,85,35,.18);
    border-radius:10px;
  }
  .v3-scale-line .scale-num{font-size:15px; font-weight:600; color:#fff; letter-spacing:-.01em}
  .v3-scale-line .scale-sep{color:var(--v3-ink-3); font-weight:400}
  .v3-scale-line .scale-unit{font-size:11px; color:var(--v3-ink-3); letter-spacing:.04em; text-transform:uppercase}

  .v3-price-list{list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:10px; flex:1}
  .v3-price-list li{display:flex; align-items:flex-start; gap:8px; font-size:12.5px; color:var(--v3-ink-2); line-height:1.4}
  .v3-price-list .ck{
    width:14px; height:14px; border-radius:999px;
    display:grid; place-items:center; flex-shrink:0;
    background:var(--v3-accent); color:#0b0b0c; margin-top:2px;
  }
  .v3-price-list .ck svg{width:8px; height:8px}

  .v3-price-story{
    font-size:12.5px; color:var(--v3-ink-3); font-style:italic; line-height:1.5;
    padding-top:8px; border-top:1px dashed rgba(255,255,255,.06); margin:0;
  }

  .v3-price-cta{
    display:inline-flex; align-items:center; justify-content:center; gap:8px;
    background:#0b0b0c; color:#fff; border:1px solid var(--v3-line);
    padding:11px 14px; border-radius:999px; font-size:13px; font-weight:500;
    cursor:pointer; font-family:inherit; text-decoration:none;
    transition:background .2s, border-color .2s, opacity .2s;
    margin-top:4px; width:100%;
  }
  .v3-price-cta:hover{border-color:rgba(255,255,255,.18)}
  .v3-price-cta:disabled{opacity:.55; cursor:wait}
  .v3-price-card.featured .v3-price-cta{background:var(--v3-accent); color:#0b0b0c; border-color:transparent}
  .v3-price-card.featured .v3-price-cta:hover{filter:brightness(1.08)}

  .v3-risk-reversal{
    text-align:center; font-size:11.5px; color:var(--v3-ink-3);
    margin-top:-6px; line-height:1.4;
  }
  .v3-risk-reversal .rr-accent{color:var(--v3-accent); font-weight:500;}

  /* Enterprise strip */
  .v3-enterprise{
    margin-top:28px; padding:32px 36px; border-radius:22px;
    background:linear-gradient(135deg, rgba(240,85,35,.08), rgba(255,255,255,.02));
    border:1px solid rgba(240,85,35,.22);
    display:grid; grid-template-columns:1.4fr 1fr auto; gap:28px; align-items:center;
  }
  @media (max-width: 960px){.v3-enterprise{grid-template-columns:1fr; text-align:left}}
  .v3-enterprise h3{margin:0 0 6px; font-size:22px; font-weight:600; letter-spacing:-.01em; color:var(--v3-ink)}
  .v3-enterprise .ent-sub{font-size:13px; color:var(--v3-ink-3); margin:0}
  .v3-enterprise .ent-body{font-size:13.5px; color:var(--v3-ink-2); line-height:1.55; margin:0}
  .v3-enterprise .v3-price-cta{
    margin-top:0; background:var(--v3-accent); color:#0b0b0c;
    border-color:transparent; padding:13px 22px; font-weight:600; width:auto;
  }

  /* Compare section */
  .v3-compare-sec{padding:120px 0 60px; border-top:1px solid var(--v3-line); margin-top:80px}
  .v3-compare-head{text-align:center; max-width:720px; margin:0 auto 48px}
  .v3-compare-head h2{font-size:clamp(28px, 3.6vw, 42px); font-weight:500; letter-spacing:-.02em; margin:0 0 12px; color:var(--v3-ink)}
  .v3-compare-head h2 em{font-style:normal; color:var(--v3-accent)}
  .v3-compare-head p{color:var(--v3-ink-3); font-size:15px; margin:0}
  .v3-compare-wrap{
    background:#0b0b0c; border:1px solid var(--v3-line); border-radius:18px;
    overflow:hidden;
  }
  .v3-compare-scroll{overflow-x:auto}
  .v3-compare-table{width:100%; border-collapse:collapse; font-size:13.5px; min-width:720px}
  .v3-compare-table thead th{
    padding:20px 18px; text-align:left;
    background:#0e0e10; border-bottom:1px solid var(--v3-line);
    color:var(--v3-ink); font-weight:500; font-size:14px;
  }
  .v3-compare-table thead th.featured{color:var(--v3-accent)}
  .v3-compare-table thead .plan-tag{
    display:block; font-size:10.5px; color:var(--v3-ink-3);
    letter-spacing:.1em; text-transform:uppercase; margin-bottom:6px; font-weight:500;
  }
  .v3-compare-table thead th.featured .plan-tag{color:var(--v3-accent)}
  .v3-compare-table td{
    padding:14px 18px; border-bottom:1px solid var(--v3-line);
    color:var(--v3-ink-2); text-align:center;
  }
  .v3-compare-table td:first-child{text-align:left; color:var(--v3-ink); font-weight:500}
  .v3-compare-table td.featured{background:rgba(240,85,35,.04)}
  .v3-compare-table tbody tr:last-child td{border-bottom:0}

  /* FAQ */
  .v3-faq-sec{padding:80px 0 40px; max-width:760px; margin:0 auto}
  .v3-faq-sec h2{font-size:clamp(28px, 3.6vw, 42px); font-weight:500; letter-spacing:-.02em; margin:0 0 12px; color:var(--v3-ink); text-align:center}
  .v3-faq-sec .lede{color:var(--v3-ink-3); text-align:center; margin:0 0 36px; font-size:14.5px}
  .v3-faq-item{
    background:#0e0e10; border:1px solid var(--v3-line); border-radius:14px;
    margin-bottom:10px; padding:0 22px;
  }
  .v3-faq-trigger{font-size:14.5px; font-weight:500; color:var(--v3-ink); padding:18px 0}
  .v3-faq-content{font-size:13.5px; color:var(--v3-ink-2); line-height:1.6; padding-bottom:18px}

  .v3-foot-note{
    text-align:center; padding:48px 0 0;
    color:var(--v3-ink-3); font-size:13px; max-width:520px; margin:0 auto;
  }

  /* Trust banner */
  .v3-trust-banner{
    margin-top:36px;
    background:#0e0e10;
    border:1px solid var(--v3-line);
    border-radius:18px;
    padding:28px 32px;
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:24px;
    flex-wrap:wrap;
  }
  @media (max-width: 720px){.v3-trust-banner{flex-direction:column; text-align:center; padding:24px}}
  .v3-trust-banner .trust-text{flex:1; min-width:0}
  .v3-trust-banner .trust-text h3{
    margin:0 0 6px; font-size:18px; font-weight:600; letter-spacing:-.01em; color:var(--v3-ink);
  }
  .v3-trust-banner .trust-text p{
    margin:1px 1px; font-size:14.5px; color:var(--v3-ink-3); line-height:1.45;
  }
  .v3-trust-stats{display:flex; gap:28px; align-items:center; flex-wrap:wrap}
  @media (max-width: 720px){.v3-trust-stats{justify-content:center}}
  .v3-trust-stat{display:flex; align-items:center; gap:10px}
  .v3-trust-stat .stat-icon{
    width:34px; height:34px; border-radius:10px;
    background:rgba(240,85,35,.12);
    display:grid; place-items:center;
    color:var(--v3-accent); flex-shrink:0;
  }
  .v3-trust-stat .stat-icon svg{width:16px; height:16px}
  .v3-trust-stat .stat-label{font-size:11px; color:var(--v3-ink-3); letter-spacing:.08em; text-transform:uppercase; font-weight:500}
  .v3-trust-stat .stat-value{font-size:17px; font-weight:600; color:var(--v3-ink); letter-spacing:-.01em; line-height:1.1}
`,J=()=>{const[t,l]=u.useState(!1),[h,c]=u.useState(null),g=async a=>{if(!z()){window.location.href="/login?redirect=/pricing";return}c(a);try{const s=await I("/v1/billing/checkout",{method:"POST",body:JSON.stringify({plan:a,billing:t?"annual":"monthly"})});s.checkout_url?window.location.href=s.checkout_url:x.error("No checkout URL returned")}catch(s){x.error(s.message||"Failed to start checkout")}finally{c(null)}};return e.jsxs(b,{children:[e.jsx(y,{title:"Pricing — Octopoda AI Agent Memory | Free Forever Tier",description:j["/pricing"],path:"/pricing"}),e.jsx("style",{children:U}),e.jsx(k,{}),e.jsxs("main",{className:"v3-wrap v3-pricing-wrap",children:[e.jsxs(o.div,{className:"v3-pricing-head",initial:{opacity:0,y:16},animate:{opacity:1,y:0},transition:{duration:.4},children:[e.jsxs("span",{className:"v3-eyebrow",children:[e.jsx("span",{className:"v3-dot"})," Pricing"]}),e.jsxs("h1",{children:["Simple plans,",e.jsx("br",{}),e.jsx("em",{children:"no surprise lines"})," on the invoice."]}),e.jsx("p",{className:"sub",children:"Flexible monthly plans, cancel at any time."}),e.jsxs("div",{className:"v3-bill-toggle",role:"tablist","aria-label":"Billing period",children:[e.jsx("span",{className:"save",children:"−20%"}),e.jsx("button",{type:"button",className:t?"on":"",onClick:()=>l(!0),"aria-pressed":t,children:"Yearly"}),e.jsx("button",{type:"button",className:t?"":"on",onClick:()=>l(!1),"aria-pressed":!t,children:"Monthly"})]})]}),e.jsxs(o.div,{className:"v3-trust-banner",initial:{opacity:0,y:16},animate:{opacity:1,y:0},transition:{duration:.4,delay:.1},children:[e.jsxs("div",{className:"trust-text",children:[e.jsx("h3",{children:"Join hundreds of developers supercharging their agent stack"}),e.jsx("p",{children:"Trusted by indie hackers, startups, and AI-first teams shipping agents to production."})]}),e.jsxs("div",{className:"v3-trust-stats",children:[e.jsxs("div",{className:"v3-trust-stat",children:[e.jsx("span",{className:"stat-icon",children:e.jsx(F,{})}),e.jsxs("div",{children:[e.jsx("div",{className:"stat-label",children:"Developers"}),e.jsx("div",{className:"stat-value",children:"2,400+"})]})]}),e.jsxs("div",{className:"v3-trust-stat",children:[e.jsx("span",{className:"stat-icon",children:e.jsx(P,{})}),e.jsxs("div",{children:[e.jsx("div",{className:"stat-label",children:"Agents deployed"}),e.jsx("div",{className:"stat-value",children:"50k+"})]})]}),e.jsxs("div",{className:"v3-trust-stat",children:[e.jsx("span",{className:"stat-icon",children:e.jsx(R,{})}),e.jsxs("div",{children:[e.jsx("div",{className:"stat-label",children:"Uptime"}),e.jsx("div",{className:"stat-value",children:"99.9%"})]})]})]})]}),e.jsx("div",{style:{display:"flex",flexWrap:"wrap",justifyContent:"center",gap:10,margin:"32px auto 0",maxWidth:880},children:[v.memory,v.extractions].map(a=>e.jsx("span",{style:{fontSize:12,color:"var(--v3-ink-2)",background:"rgba(255,255,255,0.03)",border:"1px solid var(--v3-line)",borderRadius:999,padding:"6px 14px"},children:a},a))}),e.jsx("div",{className:"v3-price-grid",children:E.map((a,s)=>{const f=t?a.annual:a.monthly,p=h===a.planId,d=a.planId==="free";return e.jsxs(o.div,{className:`v3-price-card${a.featured?" featured":""}`,initial:{opacity:0,y:20},animate:{opacity:1,y:a.featured?-14:0},transition:{duration:.4,delay:s*.06},children:[a.badge&&e.jsx("span",{className:"pop-badge",children:a.badge}),e.jsx("div",{className:"eyebrow-mini",children:a.audience}),e.jsx("h3",{children:a.name}),e.jsxs("div",{className:"price",children:[e.jsxs("span",{className:"n",children:["$",f]}),e.jsx("span",{className:"u",children:"/mo"})]}),e.jsx("div",{className:"v3-scale-line",children:a.scale.map((i,m)=>e.jsxs("span",{style:{display:"inline-flex",alignItems:"baseline",gap:6},children:[m>0&&e.jsx("span",{className:"scale-sep",children:"·"}),e.jsx("span",{className:"scale-num",children:i.num}),e.jsx("span",{className:"scale-unit",children:i.unit})]},m))}),e.jsx("ul",{className:"v3-price-list",children:a.features.map(i=>e.jsxs("li",{children:[e.jsx("span",{className:"ck",children:e.jsx("svg",{viewBox:"0 0 24 24",fill:"none",stroke:"currentColor",strokeWidth:"3",strokeLinecap:"round",strokeLinejoin:"round",children:e.jsx("path",{d:"M5 13l4 4L19 7"})})}),i]},i))}),e.jsx("p",{className:"v3-price-story",children:a.story}),d?e.jsx(w,{to:"/signup",className:"v3-price-cta",children:a.cta}):e.jsx("button",{type:"button",className:"v3-price-cta",onClick:()=>g(a.planId),disabled:p,children:p?"Redirecting…":a.cta}),e.jsx("p",{className:"v3-risk-reversal",children:d?e.jsxs(e.Fragment,{children:[e.jsx("span",{className:"rr-accent",children:"No credit card required"})," • Free forever"]}):a.riskReversal})]},a.planId)})}),e.jsxs(o.div,{className:"v3-enterprise",id:"contact",initial:{opacity:0,y:20},whileInView:{opacity:1,y:0},viewport:{once:!0},transition:{duration:.4},children:[e.jsxs("div",{children:[e.jsx("h3",{children:"Enterprise — Custom"}),e.jsx("p",{className:"ent-sub",children:"For organizations with compliance, volume, or deployment needs"})]}),e.jsx("p",{className:"ent-body",children:"Unlimited everything. Deploy in your VPC or on-prem. Custom SLA. SOC 2 and HIPAA roadmap. Dedicated engineer on your account."}),e.jsx("a",{className:"v3-price-cta",href:"mailto:ryjoxtechnologies@gmail.com",children:"Contact sales →"})]}),e.jsxs("section",{className:"v3-compare-sec",children:[e.jsxs("div",{className:"v3-compare-head",children:[e.jsxs("h2",{children:["Every plan, ",e.jsx("em",{children:"side by side."})]}),e.jsx("p",{children:"Same product, every tier. Higher plans give you more capacity and faster human support."})]}),e.jsx("div",{className:"v3-compare-wrap",children:e.jsx("div",{className:"v3-compare-scroll",children:e.jsxs("table",{className:"v3-compare-table",children:[e.jsx("thead",{children:e.jsxs("tr",{children:[e.jsx("th",{children:"Feature"}),e.jsxs("th",{children:[e.jsx("span",{className:"plan-tag",children:"Side projects"}),"Free"]}),e.jsxs("th",{children:[e.jsx("span",{className:"plan-tag",children:"Individual"}),"Pro"]}),e.jsxs("th",{className:"featured",children:[e.jsx("span",{className:"plan-tag",children:"Most popular"}),"Business"]}),e.jsxs("th",{children:[e.jsx("span",{className:"plan-tag",children:"AI-first teams"}),"Scale"]}),e.jsxs("th",{children:[e.jsx("span",{className:"plan-tag",children:"Custom"}),"Enterprise"]})]})}),e.jsx("tbody",{children:T.map(a=>e.jsxs("tr",{children:[e.jsx("td",{children:a.name}),e.jsx("td",{children:e.jsx(n,{value:a.free})}),e.jsx("td",{children:e.jsx(n,{value:a.pro})}),e.jsx("td",{className:"featured",children:e.jsx(n,{value:a.business})}),e.jsx("td",{children:e.jsx(n,{value:a.scale})}),e.jsx("td",{children:e.jsx(n,{value:a.enterprise})})]},a.name))})]})})})]}),e.jsxs("section",{className:"v3-faq-sec",children:[e.jsx("h2",{children:"Frequently asked questions"}),e.jsx("p",{className:"lede",children:"Can't find what you're looking for? Email us at ryjoxtechnologies@gmail.com"}),e.jsx(L,{type:"single",collapsible:!0,children:O.map((a,s)=>e.jsxs(q,{value:`faq-${s}`,className:"v3-faq-item border-0",children:[e.jsx(M,{className:"v3-faq-trigger hover:no-underline",children:a.q}),e.jsx(C,{className:"v3-faq-content",children:a.a})]},s))})]}),e.jsx("p",{className:"v3-foot-note",children:"All plans include full data export. No credit card required for the free tier. Your data is yours — always."})]}),e.jsx(N,{})]})};export{J as default};
