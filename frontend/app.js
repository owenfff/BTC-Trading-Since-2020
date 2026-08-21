const $ = (selector) => document.querySelector(selector);

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}

function render(payload) {
  const feed = payload.feed_status === "CONNECTED";
  const badge = $("#feed-badge");
  badge.classList.toggle("live", feed);
  badge.classList.toggle("waiting", !feed);
  badge.innerHTML = `<i></i>${feed ? "交易节点已连接" : "等待交易节点"}`;

  setText("#updated-at", feed ? `状态源 · ${payload.updated_at_utc}` : "等待状态源");
  setText("#model-version", payload.model?.version || "—");
  setText("#allowed-count", payload.mapping?.allowed_count ?? 0);
  setText("#reconciliation", payload.preflight?.reconciliation_ok ? "PASS" : "WAITING");

  const mapping = payload.mapping || {};
  const total = (mapping.allowed_count || 0) + (mapping.monitor_only_count || 0) + (mapping.unavailable_count || 0);
  setText("#mapping-total", total);
  setText("#scope-allowed", mapping.allowed_count || 0);
  setText("#scope-monitor", mapping.monitor_only_count || 0);
  setText("#scope-unavailable", mapping.unavailable_count || 0);
  const width = (number) => total ? `${Math.max(2, Math.round((number / total) * 100))}%` : "0%";
  $("#bar-allowed").style.width = width(mapping.allowed_count || 0);
  $("#bar-monitor").style.width = width(mapping.monitor_only_count || 0);
  $("#bar-unavailable").style.width = width(mapping.unavailable_count || 0);

  const symbols = $("#symbol-list");
  symbols.replaceChildren();
  if (!mapping.symbols?.length) {
    const empty = document.createElement("span");
    empty.className = "empty-state";
    empty.textContent = "等待交易节点同步品种清单";
    symbols.append(empty);
  } else {
    mapping.symbols.slice(0, 42).forEach((item) => {
      const chip = document.createElement("span");
      chip.className = `symbol-chip ${item.status === "ALLOW_DERIVATIVE_TRADING" ? "allowed" : item.status?.startsWith("UNAVAILABLE") ? "unavailable" : ""}`;
      chip.textContent = item.venue_symbol ? `${item.symbol} · ${item.venue_symbol}` : item.symbol;
      chip.title = item.status || "UNKNOWN";
      symbols.append(chip);
    });
  }
}

async function refresh() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    setText("#updated-at", "状态接口不可用");
    const badge = $("#feed-badge");
    badge.classList.remove("live");
    badge.classList.add("waiting");
    badge.innerHTML = "<i></i>前端服务异常";
    console.warn("dashboard refresh failed", error);
  }
}

refresh();
window.setInterval(refresh, 15000);
