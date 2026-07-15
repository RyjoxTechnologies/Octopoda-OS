import{aM as n,aN as e,a_ as j,aU as y,aV as w,a$ as k,b1 as N,aW as z,aP as b,aQ as A}from"./index-RsFqQstg.js";import{b as o}from"./blogPostsMeta-DtHSTODn.js";import{G as C,B as x}from"./BlogHeroArt-CO9kJr5T.js";import{S as m}from"./search-BJpC_HKc.js";import{L as S}from"./layout-grid-CKAiuHgw.js";import{F}from"./file-text-EK9y2p5Q.js";import{C as T}from"./cpu-KppxtVRJ.js";import{N as I}from"./newspaper-CrW3od4g.js";import{A as L}from"./arrow-up-right-CglJFmKT.js";import"./shield-C7FV8WCm.js";import"./dollar-sign-D9LmUwhy.js";import"./brain-mCjRcjUG.js";import"./refresh-cw-C5vu4VM7.js";import"./terminal-vRTWyx3G.js";import"./gauge-W8epu_nM.js";import"./network-CH2_Wt-s.js";import"./triangle-alert-ByMu44xx.js";import"./bot-DH_M4Xsn.js";const P=[{label:"All",icon:S},{label:"Tutorials",icon:F},{label:"Engineering",icon:T},{label:"AI Agents",icon:z},{label:"Comparisons",icon:C},{label:"Deep Dives",icon:m},{label:"News",icon:I}],B=({post:a})=>e.jsxs(b,{to:`/blog/${a.slug}`,className:"bl-feature group",children:[e.jsxs("div",{className:"bl-feature-media",children:[a.thumbnail?e.jsx("img",{src:a.thumbnail,alt:a.title,loading:"lazy"}):e.jsx(x,{title:a.title,category:a.category}),e.jsx("span",{className:"bl-cat",children:a.category})]}),e.jsxs("div",{className:"bl-feature-body",children:[e.jsx("span",{className:"bl-eyebrow-sm",children:"Featured"}),e.jsx("h2",{className:"bl-feature-title",children:a.title}),e.jsx("p",{className:"bl-feature-excerpt",children:a.excerpt}),e.jsxs("div",{className:"bl-feature-foot",children:[e.jsxs("span",{className:"bl-meta",children:[a.author," · ",a.date," · ",a.readTime]}),e.jsxs("span",{className:"bl-read",children:["Read article ",e.jsx(A,{size:15})]})]})]})]}),E=({post:a})=>e.jsxs(b,{to:`/blog/${a.slug}`,className:"bl-card group",children:[e.jsxs("div",{className:"bl-card-media",children:[a.thumbnail?e.jsx("img",{src:a.thumbnail,alt:a.title,loading:"lazy"}):e.jsx(x,{title:a.title,category:a.category,compact:!0}),e.jsx("span",{className:"bl-cat",children:a.category})]}),e.jsxs("div",{className:"bl-card-body",children:[e.jsxs("span",{className:"bl-meta",children:[a.date," · ",a.readTime]}),e.jsx("h3",{children:a.title}),e.jsx("p",{children:a.excerpt}),e.jsxs("div",{className:"bl-card-foot",children:[e.jsx("span",{children:a.author}),e.jsx(L,{size:15,className:"bl-arrow"})]})]})]}),ee=()=>{const[a,g]=n.useState("All"),[i,h]=n.useState(""),s=n.useMemo(()=>{const r=a==="All"?o:o.filter(l=>l.category===a),t=i.trim().toLowerCase();return t?r.filter(l=>l.title.toLowerCase().includes(t)||l.excerpt.toLowerCase().includes(t)||l.category.toLowerCase().includes(t)):r},[a,i]),c=a==="All"&&!i.trim(),[d,...f]=s,p=c?f:s;return e.jsxs(j,{children:[e.jsx(y,{title:"Blog — AI Agent Memory + Best Practices | Octopoda",description:w["/blog"],path:"/blog"}),e.jsx(k,{}),e.jsx("main",{className:"bl-main",children:e.jsxs("div",{className:"v3-wrap",children:[e.jsxs("header",{className:"bl-header",children:[e.jsxs("span",{className:"v3-eyebrow",children:[e.jsx("span",{className:"v3-dot"})," Blog"]}),e.jsxs("h1",{children:["Field notes from the",e.jsx("br",{}),e.jsx("span",{className:"v3-hl",children:"memory frontier"})]}),e.jsx("p",{className:"bl-lede",children:"Engineering deep-dives, agent post-mortems, and ideas from the team building the memory OS for AI agents."})]}),e.jsxs("div",{className:"bl-toolbar",children:[e.jsxs("div",{className:"bl-search",children:[e.jsx(m,{size:15}),e.jsx("input",{type:"search",value:i,onChange:r=>h(r.target.value),placeholder:"Search articles…","aria-label":"Search articles"})]}),e.jsx("div",{className:"bl-filter",children:P.map(r=>{const t=r.icon,l=r.label==="All"?o.length:o.filter(v=>v.category===r.label).length;if(l===0)return null;const u=a===r.label;return e.jsxs("button",{onClick:()=>g(r.label),className:`bl-pill ${u?"bl-pill-active":""}`,children:[e.jsx(t,{size:13}),e.jsx("span",{children:r.label}),e.jsx("span",{className:"bl-pill-count",children:l})]},r.label)})})]}),s.length===0?e.jsx("p",{className:"bl-empty",children:"No posts match your search yet."}):e.jsxs(e.Fragment,{children:[c&&d&&e.jsx(B,{post:d}),p.length>0&&e.jsx("div",{className:"bl-grid",children:p.map(r=>e.jsx(E,{post:r},r.slug))})]})]})}),e.jsx(N,{}),e.jsx("style",{children:`
        .bl-main{padding:132px 0 96px;position:relative;z-index:1}

        /* Header */
        .bl-header{text-align:center;max-width:720px;margin:0 auto 44px}
        .bl-header h1{margin-top:22px;font-size:clamp(38px,5.4vw,66px);line-height:1.04}
        .bl-lede{margin-top:22px;font-size:17.5px;line-height:1.6;color:var(--v3-ink-2);max-width:540px;margin-left:auto;margin-right:auto}

        /* Toolbar */
        .bl-toolbar{
          display:flex;flex-direction:column;align-items:center;gap:20px;
          margin:0 auto 60px;
        }
        .bl-search{
          display:flex;align-items:center;gap:10px;width:100%;max-width:440px;
          padding:12px 18px;border-radius:999px;
          background:rgba(245,242,237,0.02);border:1px solid var(--v3-line);
          color:var(--v3-ink-3);transition:border-color .2s ease,background .2s ease;
        }
        .bl-search:focus-within{border-color:var(--v3-line-strong);background:rgba(245,242,237,0.04)}
        .bl-search input{
          flex:1;background:transparent;border:0;outline:0;
          color:var(--v3-ink);font-family:inherit;font-size:14.5px;
        }
        .bl-search input::placeholder{color:var(--v3-ink-3)}

        .bl-filter{display:flex;flex-wrap:wrap;justify-content:center;gap:9px;max-width:860px}
        .bl-pill{
          display:inline-flex;align-items:center;gap:8px;
          padding:9px 15px;border-radius:999px;
          background:rgba(245,242,237,0.02);border:1px solid var(--v3-line);
          color:var(--v3-ink-2);font-size:13px;font-weight:500;
          cursor:pointer;font-family:inherit;transition:all .18s ease;
        }
        .bl-pill:hover{border-color:var(--v3-line-strong);color:var(--v3-ink);background:rgba(245,242,237,0.05)}
        .bl-pill-active{background:var(--v3-accent);color:var(--v3-accent-ink);border-color:var(--v3-accent)}
        .bl-pill-count{
          font-size:11px;opacity:.6;font-variant-numeric:tabular-nums;
          padding:1px 6px;border-radius:999px;background:rgba(245,242,237,.08);
        }
        .bl-pill-active .bl-pill-count{background:rgba(0,0,0,.2);opacity:.8}

        /* Shared bits */
        .bl-cat{
          position:absolute;top:14px;left:14px;
          display:inline-flex;align-items:center;
          padding:5px 11px;border-radius:999px;
          background:rgba(10,9,8,.62);backdrop-filter:blur(8px);
          color:var(--v3-ink);font-size:10px;font-weight:600;
          letter-spacing:.12em;text-transform:uppercase;
          border:1px solid rgba(245,242,237,.16);
        }
        .bl-meta{
          font-size:11.5px;color:var(--v3-ink-3);
          letter-spacing:.1em;text-transform:uppercase;font-weight:500;
        }
        .bl-eyebrow-sm{
          font-size:11px;color:var(--v3-accent);
          letter-spacing:.16em;text-transform:uppercase;font-weight:600;
        }
        .bl-fallback{
          width:100%;height:100%;display:grid;place-items:center;
          background:linear-gradient(135deg,rgba(222,140,66,.16),rgba(222,140,66,.03));
        }
        .bl-fallback span,.bl-fallback-lg{
          color:rgba(245,242,237,.4);font-weight:700;
          letter-spacing:.16em;text-transform:uppercase;font-size:12px;
        }

        /* Featured */
        .bl-feature{
          display:grid;grid-template-columns:1.08fr 1fr;gap:0;
          background:var(--v3-panel);border:1px solid var(--v3-line);
          border-radius:var(--v3-radius-lg);overflow:hidden;
          margin-bottom:60px;transition:border-color .3s ease,transform .3s ease;
        }
        .bl-feature:hover{border-color:rgba(222,140,66,.4);transform:translateY(-2px)}
        .bl-feature-media{position:relative;aspect-ratio:16/11;overflow:hidden;background:var(--v3-panel-2)}
        .bl-feature-media img{width:100%;height:100%;object-fit:cover;transition:transform .6s ease}
        .bl-feature:hover .bl-feature-media img{transform:scale(1.04)}
        .bl-feature-body{padding:48px 44px;display:flex;flex-direction:column;gap:18px;justify-content:center}
        .bl-feature-title{
          font-size:clamp(25px,2.5vw,36px);line-height:1.14;
          letter-spacing:-0.025em;font-weight:600;transition:color .25s ease;
        }
        .bl-feature:hover .bl-feature-title{color:var(--v3-accent)}
        .bl-feature-excerpt{font-size:15px;color:var(--v3-ink-2);line-height:1.65}
        .bl-feature-foot{
          display:flex;justify-content:space-between;align-items:center;
          gap:16px;flex-wrap:wrap;padding-top:8px;
          border-top:1px solid var(--v3-line);margin-top:4px;
        }
        .bl-feature-foot{padding-top:20px}
        .bl-read{
          display:inline-flex;align-items:center;gap:8px;
          font-size:14px;font-weight:500;color:var(--v3-accent);white-space:nowrap;
        }
        @media (max-width:820px){
          .bl-feature{grid-template-columns:1fr}
          .bl-feature-body{padding:30px 26px}
        }

        /* Grid */
        .bl-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:26px}
        .bl-card{
          display:flex;flex-direction:column;
          background:var(--v3-panel);border:1px solid var(--v3-line);
          border-radius:var(--v3-radius);overflow:hidden;
          transition:border-color .3s ease,transform .3s ease;
        }
        .bl-card:hover{border-color:rgba(222,140,66,.4);transform:translateY(-3px)}
        .bl-card-media{position:relative;aspect-ratio:16/9;overflow:hidden;background:var(--v3-panel-2)}
        .bl-card-media img{width:100%;height:100%;object-fit:cover;transition:transform .5s ease}
        .bl-card:hover .bl-card-media img{transform:scale(1.05)}
        .bl-card-body{padding:24px 22px;display:flex;flex-direction:column;gap:13px;flex:1}
        .bl-card h3{
          font-size:17.5px;line-height:1.32;font-weight:600;letter-spacing:-0.015em;
          transition:color .25s ease;
        }
        .bl-card:hover h3{color:var(--v3-accent)}
        .bl-card p{
          font-size:13.5px;color:var(--v3-ink-3);line-height:1.6;
          display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;flex:1;
        }
        .bl-card-foot{
          display:flex;justify-content:space-between;align-items:center;
          padding-top:16px;margin-top:auto;border-top:1px solid var(--v3-line);
          font-size:12px;color:var(--v3-ink-3);letter-spacing:.02em;
        }
        .bl-arrow{color:var(--v3-ink-3);transition:all .25s ease}
        .bl-card:hover .bl-arrow{color:var(--v3-accent);transform:translate(2px,-2px)}
        @media (max-width:960px){.bl-grid{grid-template-columns:repeat(2,1fr);gap:22px}}
        @media (max-width:600px){
          .bl-main{padding:112px 0 72px}
          .bl-grid{grid-template-columns:1fr;gap:20px}
        }

        .bl-empty{text-align:center;padding:100px 0;color:var(--v3-ink-3)}
      `})]})};export{ee as default};
