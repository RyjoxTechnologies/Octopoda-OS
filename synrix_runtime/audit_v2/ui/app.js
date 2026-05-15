// audit_v2 standalone viewer — vanilla JS client
//
// Responsible for:
//   - storing the API key in sessionStorage
//   - fetching from /v1/audit_v2/* (same origin)
//   - rendering the event timeline
//   - click-to-expand detail panel with context window
//   - integrity verify, cost rollup, CSV export
//
// No build step. No dependencies. ~350 lines.

(function() {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const API_BASE = "/v1/audit_v2";
  const PAGE_SIZE = 50;

  const state = {
    apiKey: sessionStorage.getItem("octopoda_audit_v2_key") || "",
    events: [],
    offset: 0,
    total: 0,
    selectedId: null,
  };

  // ===================================================================
  // api
  // ===================================================================

  async function api(path, opts = {}) {
    if (!state.apiKey) throw new Error("No API key set. Connect first.");
    const r = await fetch(API_BASE + path, {
      ...opts,
      headers: {
        "Authorization": "Bearer " + state.apiKey,
        ...(opts.headers || {}),
      },
    });
    if (!r.ok) {
      const text = await r.text().catch(() => r.statusText);
      throw new Error(`${r.status} ${r.statusText}: ${text.slice(0, 200)}`);
    }
    const ct = r.headers.get("content-type") || "";
    return ct.includes("application/json") ? r.json() : r.text();
  }

  // ===================================================================
  // fetch + render
  // ===================================================================

  async function loadEvents(append = false) {
    const agentId = $("#f-agent").value.trim();
    const eventType = $("#f-event-type").value;
    const rangeSec = parseInt($("#f-range").value, 10);
    const search = $("#f-search").value.trim().toLowerCase();

    const params = new URLSearchParams();
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(state.offset));
    if (agentId) params.set("agent_id", agentId);
    if (eventType) params.set("event_type", eventType);
    if (rangeSec > 0) {
      const from = (Date.now() / 1000) - rangeSec;
      params.set("from_ts", String(from));
    }

    try {
      const data = await api("/events?" + params.toString());
      let events = data.events || [];
      if (search) {
        events = events.filter((e) => {
          const blob = (e.key || "") + " " + (e.value_preview || "") +
                       " " + (e.agent_id || "") + " " + (e.event_type || "");
          return blob.toLowerCase().includes(search);
        });
      }
      if (append) state.events = state.events.concat(events);
      else state.events = events;
      state.total = data.total;
      render();
    } catch (e) {
      showError(e.message);
    }
  }

  function render() {
    const list = $("#event-list");
    const label = $("#count-label");

    if (state.events.length === 0) {
      list.innerHTML = `<div class="empty">No events match the current filter.</div>`;
      label.textContent = `0 of ${state.total} events`;
      $("#btn-more").classList.add("hidden");
      return;
    }
    label.textContent = `Showing ${state.events.length} of ${state.total} events`;
    list.innerHTML = state.events.map(renderRow).join("");
    $$(".event-row").forEach((row) => {
      row.addEventListener("click", () => {
        const id = parseInt(row.dataset.id, 10);
        showDetail(id);
        $$(".event-row").forEach((r) => r.classList.remove("selected"));
        row.classList.add("selected");
      });
    });
    $("#btn-more").classList.toggle("hidden", state.events.length >= state.total);
  }

  function renderRow(e) {
    const ts = e.timestamp ? new Date(e.timestamp * 1000) : null;
    const timeStr = ts ? relTime(ts) : "—";
    const pillCls = cssEscape(e.event_type || "");
    const cost = (e.cost_usd || 0) > 0
      ? "$" + (e.cost_usd).toFixed(6)
      : "—";
    const latency = (e.latency_ms || 0) > 0
      ? (e.latency_ms) + "ms"
      : "—";
    const content = renderContentLine(e);
    return `
      <div class="event-row" data-id="${e._row_id}">
        <span class="pill ${pillCls}">${escape(e.event_type || "unknown")}</span>
        <span class="agent-id" title="${escape(e.agent_id || "")}">${escape(e.agent_id || "")}</span>
        <span class="content">${content}</span>
        <span class="cost">${cost}</span>
        <span class="latency">${latency}</span>
        <span class="time" title="${ts ? ts.toISOString() : ""}">${timeStr}</span>
      </div>
    `;
  }

  function renderContentLine(e) {
    const key = e.key ? `<span class="key">${escape(e.key)}</span>` : "";
    const val = e.value_preview ? `<span class="val">${escape(e.value_preview)}</span>` : "";
    const outcome = e.outcome === "fail" || e.outcome === "timeout"
      ? ` <span class="val" style="color:var(--red)">[${e.outcome}]</span>`
      : "";
    return key + val + outcome;
  }

  function relTime(d) {
    const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (s < 60) return Math.floor(s) + "s ago";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
  }

  // ===================================================================
  // detail panel
  // ===================================================================

  async function showDetail(id) {
    state.selectedId = id;
    $("#detail-panel").classList.remove("hidden");
    $("#detail-body").innerHTML = `<div class="empty">Loading...</div>`;
    try {
      const [event, ctx] = await Promise.all([
        api(`/events/${id}`),
        api(`/events/${id}/context?window=5`),
      ]);
      renderDetail(event, ctx);
    } catch (e) {
      $("#detail-body").innerHTML = `<div class="error">Failed to load: ${escape(e.message)}</div>`;
    }
  }

  function renderDetail(event, ctx) {
    const body = $("#detail-body");
    const ts = event.timestamp ? new Date(event.timestamp * 1000) : null;
    const extraJson = event.extra
      ? JSON.stringify(event.extra, null, 2)
      : "{}";
    const prevHash = event.prev_hash
      ? event.prev_hash.slice(0, 16) + "…"
      : "(first event)";
    const thisHash = event._this_hash
      ? event._this_hash.slice(0, 16) + "…"
      : "-";

    body.innerHTML = `
      <div class="section">
        <h3>Summary</h3>
        <div class="kv">
          <div class="k">Type</div><div class="v"><span class="pill ${cssEscape(event.event_type||"")}">${escape(event.event_type||"unknown")}</span></div>
          <div class="k">Agent</div><div class="v">${escape(event.agent_id||"")}</div>
          <div class="k">Source</div><div class="v">${escape(event.source||"")}</div>
          <div class="k">Timestamp</div><div class="v">${ts ? ts.toISOString() : "—"}</div>
          <div class="k">Latency</div><div class="v">${event.latency_ms || 0} ms</div>
          <div class="k">Cost</div><div class="v">$${(event.cost_usd||0).toFixed(8)}</div>
          <div class="k">Outcome</div><div class="v">${escape(event.outcome||"-")}</div>
          ${event.error_message ? `<div class="k">Error</div><div class="v" style="color:var(--red)">${escape(event.error_message)}</div>` : ""}
        </div>
      </div>

      ${event.key ? `
      <div class="section">
        <h3>Key</h3>
        <pre>${escape(event.key)}</pre>
      </div>` : ""}

      ${event.value_preview ? `
      <div class="section">
        <h3>Value preview</h3>
        <pre>${escape(event.value_preview)}</pre>
      </div>` : ""}

      ${event.tags && event.tags.length ? `
      <div class="section">
        <h3>Tags</h3>
        <div class="v">${event.tags.map((t) => escape(t)).join(", ")}</div>
      </div>` : ""}

      <div class="section">
        <h3>Integrity</h3>
        <div class="kv">
          <div class="k">prev_hash</div><div class="v">${escape(prevHash)}</div>
          <div class="k">this_hash</div><div class="v">${escape(thisHash)}</div>
        </div>
      </div>

      <div class="section">
        <h3>Extra</h3>
        <pre>${escape(extraJson)}</pre>
      </div>

      <div class="section">
        <h3>Story around this event</h3>
        ${renderContext(ctx)}
      </div>
    `;
  }

  function renderContext(ctx) {
    if (!ctx) return "<div class='empty'>No context.</div>";
    const rows = [
      ...(ctx.before || []).map((e) => ({ ...e, _pos: "before" })),
      { ...(ctx.event || {}), _pos: "target" },
      ...(ctx.after || []).map((e) => ({ ...e, _pos: "after" })),
    ];
    return rows.map((e) => {
      const ts = e.timestamp ? new Date(e.timestamp * 1000).toISOString().slice(11, 19) : "—";
      const cls = e._pos === "target" ? "ctx-event is-target" : "ctx-event";
      return `
        <div class="${cls}">
          <span class="type">${escape(e.event_type || "")}</span>
          <span>${escape(e.key || "")}</span>
          <span style="color:var(--text-dim);margin-left:8px">${ts}</span>
        </div>
      `;
    }).join("");
  }

  // ===================================================================
  // integrity + cost + export
  // ===================================================================

  async function verifyIntegrity() {
    const agentId = $("#f-agent").value.trim();
    const params = new URLSearchParams();
    if (agentId) params.set("agent_id", agentId);
    try {
      const r = await api("/verify?" + params.toString());
      const panel = $("#integrity-panel");
      panel.classList.remove("hidden");
      if (r.ok) {
        panel.innerHTML = `
          <h4>Integrity</h4>
          <span class="ok">✓ chain intact</span>
          <span style="margin-left:8px;color:var(--text-dim)">(${r.checked} events)</span>
        `;
      } else {
        panel.innerHTML = `
          <h4>Integrity</h4>
          <span class="bad">✗ BROKEN at row ${r.first_broken_row_id}</span>
          <span style="margin-left:8px;color:var(--text-dim)">(checked ${r.checked})</span>
        `;
      }
    } catch (e) { showError(e.message); }
  }

  async function loadCostRollup() {
    try {
      const r = await api("/cost?group_by=agent");
      const panel = $("#cost-panel");
      const rows = (r.rows || []).slice(0, 5);
      if (rows.length === 0) {
        panel.innerHTML = `<h4>Cost</h4><div style="color:var(--text-dim)">No events yet.</div>`;
        return;
      }
      const total = rows.reduce((s, x) => s + (x.cost_usd || 0), 0);
      panel.innerHTML = `
        <h4>Top spenders</h4>
        ${rows.map((x) => `
          <div class="cost-row">
            <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escape(x.group)}</span>
            <span class="num">$${(x.cost_usd || 0).toFixed(4)}</span>
          </div>
        `).join("")}
        <div class="cost-row" style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border)">
          <span><strong>Total (top 5)</strong></span>
          <span class="num"><strong>$${total.toFixed(4)}</strong></span>
        </div>
      `;
    } catch (e) { /* silent */ }
  }

  async function exportCSV() {
    const agentId = $("#f-agent").value.trim();
    const eventType = $("#f-event-type").value;
    const rangeSec = parseInt($("#f-range").value, 10);
    const params = new URLSearchParams();
    if (agentId) params.set("agent_id", agentId);
    if (eventType) params.set("event_type", eventType);
    if (rangeSec > 0) {
      params.set("from_ts", String((Date.now()/1000) - rangeSec));
    }
    params.set("limit", "10000");
    const url = API_BASE + "/export?" + params.toString();
    try {
      const r = await fetch(url, {
        headers: { "Authorization": "Bearer " + state.apiKey },
      });
      if (!r.ok) throw new Error(r.status + " " + r.statusText);
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `audit-${Date.now()}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { showError("Export failed: " + e.message); }
  }

  // ===================================================================
  // utilities
  // ===================================================================

  function escape(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function cssEscape(s) {
    // classnames with dots need escaping for the . separator
    return (s || "").replace(/[^a-zA-Z0-9_-]/g, (c) => "\\" + c);
  }
  function showError(msg) {
    const el = document.createElement("div");
    el.className = "error";
    el.textContent = msg;
    $("#event-list").prepend(el);
    setTimeout(() => el.remove(), 6000);
  }

  // ===================================================================
  // wiring
  // ===================================================================

  document.addEventListener("DOMContentLoaded", () => {
    if (state.apiKey) $("#api-key").value = state.apiKey;

    $("#btn-connect").addEventListener("click", () => {
      state.apiKey = $("#api-key").value.trim();
      sessionStorage.setItem("octopoda_audit_v2_key", state.apiKey);
      state.offset = 0;
      loadEvents();
      loadCostRollup();
    });
    $("#btn-refresh").addEventListener("click", () => {
      state.offset = 0;
      loadEvents();
      loadCostRollup();
    });
    $("#btn-verify").addEventListener("click", verifyIntegrity);
    $("#btn-export").addEventListener("click", exportCSV);
    $("#btn-more").addEventListener("click", () => {
      state.offset += PAGE_SIZE;
      loadEvents(true);
    });
    $("#btn-close-detail").addEventListener("click", () => {
      $("#detail-panel").classList.add("hidden");
      $$(".event-row").forEach((r) => r.classList.remove("selected"));
    });

    // filters re-trigger load on change (slight debounce for search)
    ["f-agent", "f-event-type", "f-range"].forEach((id) => {
      $("#" + id).addEventListener("change", () => {
        state.offset = 0;
        loadEvents();
      });
    });
    let searchT = null;
    $("#f-search").addEventListener("input", () => {
      clearTimeout(searchT);
      searchT = setTimeout(() => {
        state.offset = 0;
        loadEvents();
      }, 300);
    });

    // auto-connect if we have a saved key
    if (state.apiKey) {
      loadEvents();
      loadCostRollup();
    }
  });
})();
