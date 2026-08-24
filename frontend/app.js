const $ = (selector) => document.querySelector(selector);

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}

function displayNumber(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return parsed.toLocaleString("en-US", { maximumFractionDigits: 8 });
}

function appendCell(row, value, className = "") {
  const cell = document.createElement("td");
  if (className) cell.className = className;
  cell.textContent = value ?? "—";
  row.append(cell);
}

function renderRows(selector, rows, emptyText, buildRow) {
  const body = $(selector);
  body.replaceChildren();
  if (!rows?.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "empty-cell";
    cell.colSpan = 4;
    cell.textContent = emptyText;
    row.append(cell);
    body.append(row);
    return;
  }
  rows.slice(0, 30).forEach((item) => body.append(buildRow(item)));
}

function renderAccount(payload) {
  const account = payload.account || {};
  const balances = account.balances || [];
  const positions = account.positions || [];
  const orders = account.open_orders || [];
  const fills = account.recent_fills || [];
  const runtime = payload.runtime || {};
  const hasAccount = account.source && account.source !== "NONE";

  setText("#account-source", hasAccount ? `${account.source} SNAPSHOT` : "等待快照");
  setText("#equity-value", hasAccount ? displayNumber(account.equity) : "—");
  setText("#equity-unit", account.equity_unit === "USD_EQUIVALENT" ? "USD 估值" : (account.equity_unit || "账户单位"));
  setText("#account-note", hasAccount ? `账户对账 · ${account.reconciliation_ok ? "PASS" : "WAITING"} · ${account.captured_at_utc || "时间未知"}` : "机器人尚未启动；当前没有实时账户快照。");
  setText("#position-count", positions.length);
  setText("#order-count", orders.length);
  setText("#fill-count", fills.length);
  setText("#runtime-status", (runtime.status || "NOT RUNNING").toUpperCase());

  const balanceList = $("#balance-list");
  balanceList.replaceChildren();
  if (!balances.length) {
    const empty = document.createElement("span");
    empty.className = "empty-state";
    empty.textContent = "预检或运行后显示余额明细";
    balanceList.append(empty);
  } else {
    balances.slice(0, 12).forEach((item) => {
      const chip = document.createElement("span");
      chip.className = "balance-chip";
      chip.textContent = `${item.currency || "?"}  ${displayNumber(item.total, "0")}`;
      chip.title = `可用 ${displayNumber(item.available, "0")}`;
      balanceList.append(chip);
    });
  }

  renderRows("#positions-table", positions, "暂无持仓", (item) => {
    const row = document.createElement("tr");
    appendCell(row, item.symbol);
    appendCell(row, displayNumber(item.quantity));
    appendCell(row, displayNumber(item.average_entry_price));
    appendCell(row, displayNumber(item.realized_pnl));
    return row;
  });
  renderRows("#orders-table", orders, "暂无活动订单", (item) => {
    const row = document.createElement("tr");
    appendCell(row, item.symbol);
    appendCell(row, item.side);
    appendCell(row, displayNumber(item.quantity));
    appendCell(row, displayNumber(item.price, "市价"));
    return row;
  });
  renderRows("#fills-table", fills, "暂无成交记录", (item) => {
    const row = document.createElement("tr");
    const time = item.timestamp ? new Date(item.timestamp).toLocaleString("zh-CN", { hour12: false }) : "—";
    appendCell(row, time);
    appendCell(row, item.symbol);
    appendCell(row, item.side);
    appendCell(row, `${displayNumber(item.quantity)} / ${displayNumber(item.price)}`);
    return row;
  });
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
  renderAccount(payload);

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
