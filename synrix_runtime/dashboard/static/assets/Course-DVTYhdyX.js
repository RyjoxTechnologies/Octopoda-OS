import{aN as e,a_ as p,aU as v,aV as m,a$ as x,by as u,aP as i,aQ as n,b1 as g}from"./index-RsFqQstg.js";import{c as t,a as h}from"./courseModules-COM931Z8.js";import{B as f}from"./book-open-BvWlqggq.js";import{C as l}from"./clock-Cv6ueR8h.js";import{Z as b}from"./zap-D4FUf74J.js";import{L as j}from"./lock-BByYiix8.js";import{G as w}from"./graduation-cap-CWqaQ3bM.js";const y=r=>r==="Beginner"?"v3-diff v3-diff-beg":r==="Intermediate"?"v3-diff v3-diff-int":r==="Advanced"?"v3-diff v3-diff-adv":"v3-diff v3-diff-all",N=t.filter(r=>!r.comingSoon).length,c=t.reduce((r,a)=>{const s=parseInt(a.readTime);return r+(Number.isFinite(s)?s:0)},0),O=()=>e.jsxs(p,{children:[e.jsx(v,{title:"Free AI Agents Course",description:m["/course"],path:"/course",jsonLd:{"@context":"https://schema.org","@type":"Course",name:"The Complete Guide to AI Agents: Beginner to Expert",description:"24 modules covering AI agent development from basics to production deployment. Free course by Octopoda.",provider:{"@type":"Organization",name:"Octopoda",url:"https://octopodas.com"},isAccessibleForFree:!0,numberOfCredits:24,educationalLevel:"Beginner to Advanced",url:"https://octopodas.com/course",hasCourseInstance:{"@type":"CourseInstance",courseMode:"online",courseWorkload:`PT${c}M`},syllabusSections:t.filter(r=>!r.comingSoon).map(r=>({"@type":"Syllabus",name:`Module ${r.number}: ${r.title}`,description:r.description,url:`https://octopodas.com/course/${r.slug}`}))}}),e.jsx(x,{}),e.jsx("main",{className:"v3-course-main",children:e.jsxs("div",{className:"v3-wrap",children:[e.jsxs("section",{className:"v3-course-hero",children:[e.jsxs("span",{className:"v3-eyebrow",children:[e.jsx("span",{className:"v3-dot"})," Free · 24-module course"]}),e.jsxs("h1",{children:["The complete guide to",e.jsx("br",{}),"building ",e.jsx("span",{className:"v3-hl",children:"AI Agents"})]}),e.jsx("p",{className:"v3-course-lede",children:`From "what's an agent?" to deploying production systems. Every module ends with code you'll write and run. No filler. No paywall.`}),e.jsxs("div",{className:"v3-course-stats",children:[e.jsxs("div",{className:"v3-course-stat",children:[e.jsx(f,{size:15}),e.jsxs("span",{children:[e.jsx("strong",{children:"24"})," modules"]})]}),e.jsxs("div",{className:"v3-course-stat",children:[e.jsx(u,{size:15}),e.jsxs("span",{children:[e.jsx("strong",{children:N})," available"]})]}),e.jsxs("div",{className:"v3-course-stat",children:[e.jsx(l,{size:15}),e.jsxs("span",{children:[e.jsxs("strong",{children:[Math.round(c/60),"h"]})," of reading"]})]}),e.jsxs("div",{className:"v3-course-stat",children:[e.jsx(b,{size:15}),e.jsx("span",{children:"Beginner → Expert"})]})]}),e.jsxs("div",{className:"v3-course-cta-row",children:[e.jsxs(i,{to:"/course/what-are-ai-agents",className:"v3-btn v3-btn-primary",children:["Start Module 1 ",e.jsx(n,{size:14})]}),e.jsx("a",{href:"/docs",className:"v3-btn v3-btn-ghost",children:"Browse the docs"})]})]}),e.jsx("section",{className:"v3-course-philosophy",children:e.jsxs("div",{className:"v3-philos-grid",children:[e.jsxs("div",{className:"v3-philos-card",children:[e.jsx("div",{className:"v3-philos-num",children:"01"}),e.jsx("h3",{children:"Build, don't just read"}),e.jsx("p",{children:"Every module ends with running code. Raw Python, LangChain, CrewAI, OpenAI Agents SDK — you'll write them all."})]}),e.jsxs("div",{className:"v3-philos-card",children:[e.jsx("div",{className:"v3-philos-num",children:"02"}),e.jsx("h3",{children:"Memory is the missing piece"}),e.jsx("p",{children:"Most courses skip persistence. We don't. You'll learn why agents forget and exactly how to fix it."})]}),e.jsxs("div",{className:"v3-philos-card",children:[e.jsx("div",{className:"v3-philos-num",children:"03"}),e.jsx("h3",{children:"Production-ready by module 18"}),e.jsx("p",{children:"Loop detection, recovery, deployment, monitoring — the things that break agents at 3am."})]})]})}),e.jsxs("section",{className:"v3-course-curriculum",children:[e.jsxs("div",{className:"v3-curr-head",children:[e.jsxs("span",{className:"v3-eyebrow",children:[e.jsx("span",{className:"v3-dot"})," Curriculum"]}),e.jsx("h2",{children:"The full 24 modules"}),e.jsx("p",{children:"Click any available module to start. No signup needed."})]}),e.jsx("div",{className:"v3-parts",children:h.map(({label:r,modules:a},s)=>e.jsxs("div",{className:"v3-part",children:[e.jsxs("div",{className:"v3-part-header",children:[e.jsxs("span",{className:"v3-part-num",children:["Part ",s+1]}),e.jsx("h3",{className:"v3-part-title",children:r}),e.jsxs("span",{className:"v3-part-count",children:[a.length," modules"]})]}),e.jsx("div",{className:"v3-part-modules",children:a.map(o=>{const d=e.jsxs(e.Fragment,{children:[e.jsx("div",{className:`v3-mod-num ${o.comingSoon?"v3-mod-num-locked":""}`,children:o.comingSoon?e.jsx(j,{size:13}):String(o.number).padStart(2,"0")}),e.jsxs("div",{className:"v3-mod-body",children:[e.jsxs("div",{className:"v3-mod-top",children:[e.jsx("h4",{children:o.title}),o.comingSoon?e.jsx("span",{className:"v3-diff v3-diff-soon",children:"Coming soon"}):e.jsx("span",{className:y(o.difficulty),children:o.difficulty})]}),e.jsx("p",{children:o.description})]}),e.jsxs("div",{className:"v3-mod-meta",children:[e.jsx(l,{size:12}),e.jsx("span",{children:o.readTime}),!o.comingSoon&&e.jsx(n,{size:14,className:"v3-mod-arrow"})]})]});return o.comingSoon?e.jsx("div",{className:"v3-mod-row v3-mod-row-locked",children:d},o.number):e.jsx(i,{to:`/course/${o.slug}`,className:"v3-mod-row",children:d},o.number)})})]},r))})]}),e.jsxs("section",{className:"v3-course-cta",children:[e.jsx(w,{className:"v3-course-cta-icon",size:32}),e.jsx("h2",{children:"Ready to build your first agent?"}),e.jsx("p",{children:"No signup. No paywall. Open Module 1 and start building."}),e.jsxs(i,{to:"/course/what-are-ai-agents",className:"v3-btn v3-btn-primary v3-course-cta-btn",children:["Start Module 1 ",e.jsx(n,{size:14})]})]})]})}),e.jsx(g,{}),e.jsx("style",{children:`
      .v3-course-main{padding:120px 0 80px;position:relative;z-index:1}

      /* HERO */
      .v3-course-hero{text-align:center;max-width:820px;margin:0 auto 80px}
      .v3-course-hero h1{margin-top:20px;font-size:clamp(42px,5.8vw,72px)}
      .v3-course-lede{
        margin:28px auto 0;font-size:17px;line-height:1.6;
        color:var(--v3-ink-2);max-width:720px;padding:0 16px;
      }
      .v3-course-stats{
        display:flex;flex-wrap:wrap;justify-content:center;gap:14px;
        margin:36px auto 0;max-width:680px;
      }
      .v3-course-stat{
        display:inline-flex;align-items:center;gap:8px;
        padding:9px 16px;border-radius:999px;
        background:rgba(255,255,255,0.02);
        border:1px solid var(--v3-line);
        font-size:13px;color:var(--v3-ink-2);
      }
      .v3-course-stat svg{color:var(--v3-accent)}
      .v3-course-stat strong{color:var(--v3-ink);font-weight:600}
      .v3-course-cta-row{
        display:inline-flex;gap:12px;margin-top:34px;flex-wrap:wrap;justify-content:center;
      }

      /* PHILOSOPHY */
      .v3-course-philosophy{margin:0 auto 100px;max-width:1100px}
      .v3-philos-grid{
        display:grid;grid-template-columns:repeat(3,1fr);gap:18px;
      }
      .v3-philos-card{
        background:var(--v3-panel);border:1px solid var(--v3-line);
        border-radius:var(--v3-radius-lg);padding:28px;
        transition:border-color .3s ease,transform .3s ease;
      }
      .v3-philos-card:hover{border-color:rgba(240,85,35,.35);transform:translateY(-2px)}
      .v3-philos-num{
        font-family:'Geist Mono',monospace;font-size:13px;
        color:var(--v3-accent);font-weight:600;letter-spacing:.06em;margin-bottom:14px;
      }
      .v3-philos-card h3{font-size:19px;font-weight:600;letter-spacing:-0.01em;margin-bottom:10px}
      .v3-philos-card p{font-size:13.5px;color:var(--v3-ink-3);line-height:1.55}
      @media (max-width:860px){.v3-philos-grid{grid-template-columns:1fr}}

      /* CURRICULUM */
      .v3-course-curriculum{margin-bottom:100px}
      .v3-curr-head{text-align:center;margin-bottom:48px}
      .v3-curr-head h2{margin-top:18px}
      .v3-curr-head p{margin-top:14px;color:var(--v3-ink-3);font-size:15px}

      .v3-parts{display:flex;flex-direction:column;gap:36px;max-width:980px;margin:0 auto}
      .v3-part{
        background:linear-gradient(180deg,rgba(255,255,255,0.02),transparent);
        border:1px solid var(--v3-line);
        border-radius:var(--v3-radius-lg);
        padding:24px;
      }
      .v3-part-header{
        display:flex;align-items:baseline;gap:14px;
        padding:0 4px 18px;margin-bottom:18px;
        border-bottom:1px solid var(--v3-line);
      }
      .v3-part-num{
        font-family:'Geist Mono',monospace;font-size:11px;
        color:var(--v3-accent);font-weight:600;
        letter-spacing:.14em;text-transform:uppercase;
      }
      .v3-part-title{
        font-size:20px;font-weight:600;letter-spacing:-0.01em;flex:1;
      }
      .v3-part-count{
        font-size:11px;color:var(--v3-ink-3);
        letter-spacing:.12em;text-transform:uppercase;
      }
      .v3-part-modules{display:flex;flex-direction:column;gap:6px}

      .v3-mod-row{
        display:grid;grid-template-columns:auto 1fr auto;gap:18px;align-items:center;
        padding:16px 18px;border-radius:12px;
        border:1px solid transparent;
        transition:all .2s ease;
      }
      .v3-mod-row:hover{
        background:rgba(255,255,255,0.025);
        border-color:var(--v3-line);
      }
      .v3-mod-row-locked{opacity:.45;cursor:default}
      .v3-mod-row-locked:hover{background:transparent;border-color:transparent}

      .v3-mod-num{
        width:38px;height:38px;border-radius:10px;
        display:grid;place-items:center;
        background:rgba(240,85,35,.08);
        border:1px solid rgba(240,85,35,.18);
        color:var(--v3-accent);
        font-family:'Geist Mono',monospace;font-size:13px;font-weight:600;
        flex-shrink:0;
      }
      .v3-mod-num-locked{
        background:rgba(255,255,255,.04);
        border-color:var(--v3-line);
        color:var(--v3-ink-3);
      }
      .v3-mod-row:hover .v3-mod-num{background:rgba(240,85,35,.16);border-color:rgba(240,85,35,.4)}
      .v3-mod-row-locked:hover .v3-mod-num{background:rgba(255,255,255,.04);border-color:var(--v3-line)}

      .v3-mod-body{min-width:0}
      .v3-mod-top{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:4px}
      .v3-mod-body h4{
        font-size:15px;font-weight:500;letter-spacing:-0.01em;
        color:var(--v3-ink);transition:color .2s ease;margin:0;
      }
      .v3-mod-row:hover .v3-mod-body h4{color:var(--v3-accent)}
      .v3-mod-body p{
        font-size:12.5px;color:var(--v3-ink-3);line-height:1.5;
        display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden;
      }
      .v3-mod-meta{
        display:inline-flex;align-items:center;gap:8px;
        font-size:12px;color:var(--v3-ink-3);font-variant-numeric:tabular-nums;
        flex-shrink:0;
      }
      .v3-mod-arrow{color:var(--v3-ink-3);transition:all .2s ease;margin-left:6px}
      .v3-mod-row:hover .v3-mod-arrow{color:var(--v3-accent);transform:translateX(3px)}

      .v3-diff{
        font-size:9.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
        padding:3px 8px;border-radius:999px;border:1px solid;
      }
      .v3-diff-beg{color:#22c55e;background:rgba(34,197,94,.08);border-color:rgba(34,197,94,.22)}
      .v3-diff-int{color:#fbbf24;background:rgba(251,191,36,.08);border-color:rgba(251,191,36,.22)}
      .v3-diff-adv{color:#f97316;background:rgba(249,115,22,.08);border-color:rgba(249,115,22,.22)}
      .v3-diff-all{color:#a78bfa;background:rgba(167,139,250,.08);border-color:rgba(167,139,250,.22)}
      .v3-diff-soon{color:var(--v3-ink-3);background:rgba(255,255,255,.04);border-color:var(--v3-line)}

      @media (max-width:760px){
        .v3-mod-row{grid-template-columns:auto 1fr;gap:14px}
        .v3-mod-meta{grid-column:2;justify-self:start;padding-left:0;margin-top:4px}
        .v3-mod-body p{-webkit-line-clamp:2}
      }

      /* CTA */
      .v3-course-cta{
        text-align:center;padding:60px 32px;
        background:linear-gradient(135deg,rgba(240,85,35,.08),rgba(255,255,255,.02));
        border:1px solid rgba(240,85,35,.22);
        border-radius:var(--v3-radius-lg);
        max-width:680px;margin:0 auto;
      }
      .v3-course-cta-icon{color:var(--v3-accent);margin-bottom:18px}
      .v3-course-cta h2{font-size:clamp(26px,3vw,38px);margin-bottom:14px}
      .v3-course-cta p{color:var(--v3-ink-3);font-size:15px;margin-bottom:26px}
      .v3-course-cta-btn{margin:0 auto}
    `})]});export{O as default};
