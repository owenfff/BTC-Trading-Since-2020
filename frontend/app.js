const $ = (selector) => document.querySelector(selector);
const PANEL_BASE = window.location.pathname === "/quant" || window.location.pathname.startsWith("/quant/") ? "/quant" : "";
const panelPath = (path) => `${PANEL_BASE}${path}`;

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

const strategyActionLabels = {
  OPEN_LONG: "开多：策略预期上行，建立多仓",
  OPEN_SHORT: "开空：策略预期下行，建立空仓",
  ADD_LONG: "加多：策略目标多仓高于当前仓位",
  ADD_SHORT: "加空：策略目标空仓高于当前仓位",
  REDUCE_LONG: "减多：策略目标多仓低于当前仓位",
  REDUCE_SHORT: "减空：策略目标空仓低于当前仓位",
  CLOSE_LONG: "平多：策略目标回到空仓/无仓",
  CLOSE_SHORT: "平空：策略目标回到多仓/无仓",
  HOLD_LONG: "持有多仓：策略暂不改变目标",
  HOLD_SHORT: "持有空仓：策略暂不改变目标",
  NO_TRADE: "不交易：策略没有明确方向",
};

const executionReasonLabels = {
  TARGET_DELTA: "当前仓位与策略目标不一致，执行差额调整",
  FLIP_REDUCE_FIRST: "策略方向反转，先减掉原方向再开新方向",
};

const riskTagLabels = {
  TRAIN_NUMPY_LOGISTIC: "历史行为模型判断",
  MARK_INDEX_MISSING: "缺少标记价格，需谨慎解读",
  LOW_ACCOUNTING_CONFIDENCE: "会计数据置信度较低",
  HIGH_VOLATILITY: "当前波动较高",
  UNKNOWN_MARKET_REGIME: "市场状态不明确",
  INSUFFICIENT_HISTORY: "历史行情不足",
  MISSING_MARKET_DATA: "行情数据不完整",
};

function strategyReasonParts(item) {
  const action = String(item.strategy_action || "").toUpperCase();
  const executionReason = String(item.strategy_reason || "").toUpperCase();
  const actionLabel = strategyActionLabels[action] || (action ? `策略动作：${action}` : "策略暂未给出明确动作");
  const executionLabel = executionReasonLabels[executionReason] || "根据策略目标仓位执行";
  const target = item.strategy_target_exposure ? `目标暴露 ${displayNumber(item.strategy_target_exposure)}` : "目标暴露未知";
  const confidence = item.strategy_confidence ? `置信度 ${displayNumber(item.strategy_confidence)}` : "置信度未知";
  const tags = (Array.isArray(item.strategy_risk_tags) ? item.strategy_risk_tags : [])
    .map((tag) => riskTagLabels[String(tag).toUpperCase()] || String(tag))
    .filter((tag, index, all) => tag && all.indexOf(tag) === index);
  return { actionLabel, executionLabel, detail: [target, confidence, ...tags].join(" · ") };
}

function appendStrategyReasonCell(row, item) {
  const cell = document.createElement("td");
  cell.className = "strategy-reason";
  const parts = strategyReasonParts(item);
  const action = document.createElement("strong");
  action.textContent = parts.actionLabel;
  const execution = document.createElement("span");
  execution.textContent = parts.executionLabel;
  const detail = document.createElement("small");
  detail.textContent = parts.detail;
  cell.append(action, execution, detail);
  row.append(cell);
}

function renderRows(selector, rows, emptyText, buildRow, columnCount = 4) {
  const body = $(selector);
  body.replaceChildren();
  if (!rows?.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "empty-cell";
    cell.colSpan = columnCount;
    cell.textContent = emptyText;
    row.append(cell);
    body.append(row);
    return;
  }
  rows.slice(0, 30).forEach((item) => body.append(buildRow(item)));
}

const replayState = { data: null, cursor: 1000, playing: false, timer: null };
const replayColors = { teal: "#17a6a0", copper: "#c6664d", amber: "#b9842b", ink: "#101b1c", muted: "#6d7a73", grid: "rgba(147,163,155,.36)" };

function replayTime(value) {
  if (value === null || value === undefined) return "—";
  return new Date(value).toLocaleString("zh-CN", { hour12: false, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function replayShortNumber(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: 6 });
}

function chartSurface(canvas) {
  if (!canvas) return null;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, Math.floor(rect.width));
  const height = Math.max(80, Math.floor(rect.height));
  const ratio = window.devicePixelRatio || 1;
  if (canvas.width !== width * ratio || canvas.height !== height * ratio) {
    canvas.width = width * ratio;
    canvas.height = height * ratio;
  }
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);
  return { context, width, height, plot: { left: 40, right: 12, top: 8, bottom: 21 } };
}

function chartFrame(surface, minValue, maxValue, formatValue) {
  const { context: ctx, width, height, plot } = surface;
  const innerWidth = width - plot.left - plot.right;
  const innerHeight = height - plot.top - plot.bottom;
  ctx.strokeStyle = replayColors.grid;
  ctx.lineWidth = 1;
  ctx.fillStyle = replayColors.muted;
  ctx.font = "9px SFMono-Regular, Consolas, monospace";
  for (let row = 0; row <= 3; row += 1) {
    const y = plot.top + innerHeight * row / 3;
    ctx.beginPath(); ctx.moveTo(plot.left, y); ctx.lineTo(width - plot.right, y); ctx.stroke();
    const value = maxValue - (maxValue - minValue) * row / 3;
    ctx.fillText(formatValue(value), 2, y + 3);
  }
  return { innerWidth, innerHeight, x: (timestamp, start, end) => plot.left + ((timestamp - start) / Math.max(1, end - start)) * innerWidth, y: (value) => plot.top + ((maxValue - value) / Math.max(1e-12, maxValue - minValue)) * innerHeight };
}

function replayVisible() {
  const data = replayState.data;
  if (!data?.bars?.length) return null;
  const index = Math.max(1, Math.min(data.bars.length - 1, Math.round((replayState.cursor / 1000) * (data.bars.length - 1))));
  const bars = data.bars.slice(0, index + 1);
  const endTs = bars[bars.length - 1].ts;
  return { data, bars, endTs, index };
}

function drawPriceChart(snapshot) {
  const surface = chartSurface($("#price-chart"));
  if (!surface) return;
  const { context: ctx, width, plot } = surface;
  if (!snapshot) return;
  const bars = snapshot.bars;
  const startTs = bars[0].ts;
  const endTs = bars[bars.length - 1].ts;
  const values = bars.map((row) => Number(row.close)).filter(Number.isFinite);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const padding = Math.max((maximum - minimum) * .08, maximum * .002);
  const frame = chartFrame(surface, minimum - padding, maximum + padding, (value) => replayShortNumber(value));
  ctx.strokeStyle = replayColors.teal;
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  bars.forEach((bar, index) => {
    const px = frame.x(bar.ts, startTs, endTs);
    const py = frame.y(Number(bar.close));
    if (index === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  });
  ctx.stroke();

  const visibleOrders = snapshot.data.orders.filter((order) => order.start_ts <= snapshot.endTs && order.end_ts >= startTs);
  visibleOrders.forEach((order) => {
    if (!Number.isFinite(order.price)) return;
    const from = Math.max(startTs, order.start_ts);
    const to = Math.min(snapshot.endTs, order.end_ts);
    const px1 = frame.x(from, startTs, endTs);
    const px2 = frame.x(to, startTs, endTs);
    const py = frame.y(order.price);
    ctx.strokeStyle = order.side === "Buy" ? replayColors.teal : replayColors.copper;
    ctx.globalAlpha = order.is_filled ? .68 : .38;
    ctx.setLineDash(order.is_filled ? [] : [4, 4]);
    ctx.lineWidth = order.is_filled ? 1.4 : 1;
    ctx.beginPath(); ctx.moveTo(px1, py); ctx.lineTo(Math.max(px1 + 2, px2), py); ctx.stroke();
    ctx.setLineDash([]); ctx.globalAlpha = 1;
    const marker = order.is_filled ? replayColors.copper : replayColors.amber;
    ctx.fillStyle = marker;
    ctx.beginPath(); ctx.arc(frame.x(order.end_ts, startTs, endTs), py, 2.4, 0, Math.PI * 2); ctx.fill();
  });
  ctx.strokeStyle = replayColors.amber;
  ctx.globalAlpha = .9;
  ctx.lineWidth = 1;
  const pointerX = frame.x(snapshot.endTs, startTs, endTs);
  ctx.beginPath(); ctx.moveTo(pointerX, plot.top); ctx.lineTo(pointerX, surface.height - plot.bottom); ctx.stroke();
  ctx.globalAlpha = 1;
}

function drawPositionChart(snapshot) {
  const surface = chartSurface($("#position-chart"));
  if (!surface || !snapshot) return;
  const { context: ctx, width, plot } = surface;
  const bars = snapshot.bars;
  const startTs = bars[0].ts;
  const endTs = bars[bars.length - 1].ts;
  const events = snapshot.data.orders.filter((order) => order.end_ts >= startTs && order.end_ts <= snapshot.endTs && Number.isFinite(order.position_after));
  const positions = [0, ...events.map((order) => Number(order.position_after))];
  const absolute = Math.max(1, ...positions.map((value) => Math.abs(value)));
  const frame = chartFrame(surface, -absolute, absolute, (value) => replayShortNumber(value));
  const zero = frame.y(0);
  ctx.strokeStyle = replayColors.grid; ctx.beginPath(); ctx.moveTo(plot.left, zero); ctx.lineTo(width - plot.right, zero); ctx.stroke();
  events.forEach((order) => {
    const x = frame.x(order.end_ts, startTs, endTs);
    const y = frame.y(Number(order.position_after));
    ctx.fillStyle = Number(order.position_after) >= 0 ? replayColors.teal : replayColors.copper;
    ctx.globalAlpha = .78;
    ctx.fillRect(x - 2, Math.min(zero, y), 4, Math.max(1, Math.abs(y - zero)));
    ctx.globalAlpha = 1;
  });
  let prior = 0;
  ctx.strokeStyle = replayColors.ink; ctx.lineWidth = 1.2; ctx.beginPath();
  events.forEach((order, index) => {
    const x = frame.x(order.end_ts, startTs, endTs);
    const y = frame.y(Number(order.position_after));
    if (index === 0) ctx.moveTo(plot.left, frame.y(prior));
    ctx.lineTo(x, frame.y(prior)); ctx.lineTo(x, y); prior = Number(order.position_after);
  });
  ctx.lineTo(width - plot.right, frame.y(prior)); ctx.stroke();
}

function drawPnlChart(snapshot) {
  const surface = chartSurface($("#pnl-chart"));
  if (!surface || !snapshot) return;
  const { context: ctx, width, plot } = surface;
  const bars = snapshot.bars;
  const startTs = bars[0].ts;
  const endTs = bars[bars.length - 1].ts;
  const points = snapshot.data.pnl.filter((point) => point.ts >= startTs && point.ts <= snapshot.endTs);
  const values = [0, ...points.map((point) => Number(point.value))];
  const minimum = Math.min(...values); const maximum = Math.max(...values);
  const padding = Math.max((maximum - minimum) * .12, 1);
  const frame = chartFrame(surface, minimum - padding, maximum + padding, (value) => replayShortNumber(value));
  const zero = frame.y(0);
  ctx.strokeStyle = replayColors.grid; ctx.beginPath(); ctx.moveTo(plot.left, zero); ctx.lineTo(width - plot.right, zero); ctx.stroke();
  if (!points.length) return;
  ctx.strokeStyle = replayColors.teal; ctx.lineWidth = 1.7; ctx.beginPath();
  points.forEach((point, index) => {
    const px = frame.x(point.ts, startTs, endTs); const py = frame.y(Number(point.value));
    if (index === 0) { ctx.moveTo(plot.left, zero); ctx.lineTo(px, py); } else ctx.lineTo(px, py);
  });
  ctx.stroke();
  ctx.fillStyle = replayColors.amber;
  const last = points[points.length - 1];
  ctx.beginPath(); ctx.arc(frame.x(last.ts, startTs, endTs), frame.y(Number(last.value)), 2.8, 0, Math.PI * 2); ctx.fill();
}

function updateReplayInspector(snapshot) {
  if (!snapshot) return;
  const { data, bars, endTs } = snapshot;
  const bar = bars[bars.length - 1];
  const orders = data.orders.filter((order) => order.start_ts <= endTs && order.end_ts >= endTs);
  const lastOrder = data.orders.filter((order) => order.end_ts <= endTs && Number.isFinite(order.position_after)).at(-1);
  const pnl = data.pnl.filter((point) => point.ts <= endTs).at(-1);
  setText("#replay-time", replayTime(endTs));
  setText("#replay-price", replayShortNumber(Number(bar.close)));
  setText("#replay-position", lastOrder ? `${replayShortNumber(lastOrder.position_after)} contracts` : "0 contracts");
  setText("#replay-orders", `${orders.length}`);
  setText("#replay-pnl", pnl ? replayShortNumber(pnl.value) : "0");
  setText("#replay-inspector-title", `${data.symbol} · ${lastOrder?.action || "NO ACTION"}`);
  setText("#replay-range", `${replayTime(data.full_start_ts)} → ${replayTime(data.full_end_ts)}`);
}

function drawReplay() {
  const snapshot = replayVisible();
  if (!snapshot) return;
  drawPriceChart(snapshot); drawPositionChart(snapshot); drawPnlChart(snapshot); updateReplayInspector(snapshot);
}

function stopReplay() {
  replayState.playing = false;
  if (replayState.timer) window.clearInterval(replayState.timer);
  replayState.timer = null;
  setText("#replay-play", "▶ 播放");
}

function startReplay() {
  if (!replayState.data?.bars?.length) return;
  if (replayState.playing) { stopReplay(); return; }
  replayState.playing = true;
  setText("#replay-play", "Ⅱ 暂停");
  replayState.timer = window.setInterval(() => {
    const speed = Number($("#replay-speed")?.value || 450);
    replayState.cursor += speed <= 200 ? 8 : speed <= 500 ? 4 : 2;
    if (replayState.cursor >= 1000) { replayState.cursor = 1000; stopReplay(); }
    const slider = $("#replay-slider"); if (slider) slider.value = String(replayState.cursor);
    drawReplay();
  }, Number($("#replay-speed")?.value || 450));
}

async function loadReplay() {
  const status = $("#replay-status");
  try {
    const symbol = $("#replay-symbol")?.value || "XBTUSD";
    const response = await fetch(panelPath(`/api/replay?symbol=${encodeURIComponent(symbol)}&limit=1000`), { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    replayState.data = await response.json();
    replayState.cursor = 1000;
    setText("#replay-pnl-unit", replayState.data.pnl_unit || "分析值");
    setText("#replay-note", replayState.data.available ? "数据来自仓库内已审计的历史派生输出；下层为分析性已实现结果，不代表实时账户权益。" : "本地历史回放数据尚未生成。先完成数据节点同步后，这里会显示时间轴。 ");
    setText("#replay-status", replayState.data.available ? "LOCAL REPLAY READY" : "WAITING FOR DATA");
    drawReplay();
  } catch (error) {
    replayState.data = null;
    setText("#replay-status", "REPLAY UNAVAILABLE");
    setText("#replay-note", `历史回放接口不可用 · ${error.message}`);
  }
}

$("#replay-play")?.addEventListener("click", startReplay);
$("#replay-latest")?.addEventListener("click", () => { stopReplay(); replayState.cursor = 1000; const slider = $("#replay-slider"); if (slider) slider.value = "1000"; drawReplay(); });
$("#replay-slider")?.addEventListener("input", (event) => { stopReplay(); replayState.cursor = Number(event.target.value); drawReplay(); });
$("#replay-symbol")?.addEventListener("change", () => { stopReplay(); loadReplay(); });
document.querySelector("[data-advanced='replay']")?.addEventListener("toggle", (event) => {
  if (event.target.open) window.requestAnimationFrame(drawReplay);
});
window.addEventListener("resize", () => { if (replayState.data) drawReplay(); });

function renderAccount(payload) {
  const account = payload.account || {};
  const balances = account.balances || [];
  const positions = account.positions || [];
  const orders = account.open_orders || [];
  const fills = account.recent_fills || [];
  const runtime = payload.runtime || {};
  const hasAccount = account.source && account.source !== "NONE";

  setText("#account-source", hasAccount ? `${runtime.plans || 0} 个信号` : "等待快照");
  setText("#equity-value", hasAccount ? displayNumber(account.equity) : "—");
  setText("#equity-unit", account.equity_unit === "USD_EQUIVALENT" ? "USD 估值" : (account.equity_unit || "账户单位"));
  const diagnostic = runtime.last_error || runtime.stop_reason;
  setText("#account-note", diagnostic ? `运行诊断 · ${diagnostic}` : hasAccount ? `${runtime.plans || 0} 个目标信号 · 对账 ${account.reconciliation_ok ? "PASS" : "WAITING"}` : "等待实时账户快照。");
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
  renderRows("#orders-table", orders, "暂无订单", (item) => {
    const row = document.createElement("tr");
    appendCell(row, item.symbol);
    appendCell(row, item.side);
    appendCell(row, displayNumber(item.quantity));
    appendCell(row, displayNumber(item.price, "市价"));
    appendStrategyReasonCell(row, item);
    return row;
  }, 5);
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

function renderVenues(venues) {
  const list = $("#venue-list");
  list.replaceChildren();
  if (!venues?.length) {
    const empty = document.createElement("span");
    empty.className = "empty-state";
    empty.textContent = "等待交易节点状态";
    list.append(empty);
    return;
  }
  venues.forEach((venue) => {
    const card = document.createElement("article");
    const live = venue.runtime_status === "RUNNING" || venue.runtime_status === "RUNNING_READ_ONLY";
    const connected = venue.market_connected;
    card.className = `venue-card ${live ? "live" : ""}`;
    const title = document.createElement("div");
    title.className = "venue-title";
    title.innerHTML = `<strong></strong><span class="venue-dot"></span>`;
    title.querySelector("strong").textContent = venue.label || venue.venue;
    const status = document.createElement("p");
    status.className = "venue-status";
    status.textContent = `${venue.runtime_status || "NOT_RUNNING"} · ${venue.market_connection || "NONE"}`;
    const metrics = document.createElement("div");
    metrics.className = "venue-metrics";
    metrics.innerHTML = `<span><b></b><small>权益</small></span><span><b></b><small>仓位 / 订单</small></span><span><b></b><small>成交</small></span>`;
    const values = metrics.querySelectorAll("b");
    values[0].textContent = displayNumber(venue.equity);
    values[1].textContent = `${venue.position_count || 0} / ${venue.open_order_count || 0}`;
    values[2].textContent = venue.fill_count || 0;
    const note = document.createElement("small");
    note.className = "venue-note";
    note.textContent = venue.order_submission_enabled ? "下单通道已确认（非生产环境）" : connected ? "私有流已连接 · 只读/等待确认" : "等待凭证或交易节点";
    card.append(title, status, metrics, note);
    list.append(card);
  });
}

function render(payload) {
  const localControl = Boolean(payload.control?.enabled && payload.control?.local_only);
  document.body.classList.toggle("public-mode", !localControl);
  document.querySelector(".control-panel")?.toggleAttribute("hidden", !localControl);
  document.querySelectorAll("details.advanced").forEach((item) => item.toggleAttribute("hidden", !localControl));
  const feed = payload.feed_status === "CONNECTED";
  const badge = $("#feed-badge");
  badge.classList.toggle("live", feed);
  badge.classList.toggle("waiting", !feed);
  badge.innerHTML = `<i></i>${feed ? "交易节点已连接" : "等待交易节点"}`;

  setText("#updated-at", feed ? `状态源 · ${payload.updated_at_utc}` : "等待状态源");
  setText("#model-version", payload.model?.version || "—");
  renderVenues(payload.venues || []);
  setText("#allowed-count", payload.mapping?.allowed_count ?? 0);
  setText("#reconciliation", payload.preflight?.reconciliation_ok ? "PASS" : "WAITING");
  renderAccount(payload);
  renderControl(payload.control || {});

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

let controlState = {};

function updateCredentialFields() {
  const venue = $("#control-venue")?.value;
  const passphraseField = $("#credential-passphrase-field");
  if (passphraseField) passphraseField.hidden = venue !== "okx-demo";
}

function renderControl(control) {
  control = control || {};
  controlState = control;
  const enabled = control.enabled && control.local_only;
  const running = Boolean(control.running);
  const status = $("#control-status");
  const note = $("#control-note");
  const start = $("#control-start");
  const stop = $("#control-stop");
  const preflight = $("#control-preflight");
  const form = $("#credential-form");
  const credentialStatus = $("#credential-status");
  if (!status || !note || !start || !stop) return;
  updateCredentialFields();
  const selectedVenue = $("#control-venue")?.value || "okx-demo";
  const testnetMode = $("#control-mode")?.value === "testnet";
  const credentialSetupAvailable = control.credential_setup_available !== false;
  const configured = !credentialSetupAvailable || control.credential_statuses?.[selectedVenue] === "CONFIGURED";
  status.textContent = !enabled ? "只读面板" : running ? `运行中 · ${control.venue}` : "本机控制已就绪";
  if (form) form.hidden = !enabled || !credentialSetupAvailable;
  if (credentialStatus) credentialStatus.textContent = configured ? "已配置" : "未配置";
  start.disabled = !enabled || running || (testnetMode && !configured);
  stop.disabled = !enabled || !running;
  if (preflight) preflight.disabled = !enabled || running || !configured;
  if (!enabled) {
    note.textContent = "当前是远程/只读面板。请在交易节点本机启动 start-local-control-panel.ps1 或 start-local-control-panel.sh 后使用控制按钮。";
  } else if (!credentialSetupAvailable) {
    note.textContent = "Windows 节点请使用启动器的 DPAPI 凭证流程；Linux 交易节点可在本区配置凭证。";
  } else if (running) {
    note.textContent = `本机节点已启动：${control.venue} · ${control.mode}。凭证不会进入网页。`;
  } else if (testnetMode && !configured) {
    note.textContent = "先在上方本机凭证区保存当前交易所凭证，再运行预检。";
  } else {
    note.textContent = "凭证只保存到本机权限 600 文件；网页不会回显或保存密钥。";
  }
}

async function controlRequest(path, body = {}) {
  const response = await fetch(panelPath(path), {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Local-Control": "1" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || payload.status || `HTTP ${response.status}`);
  return payload;
}

$("#control-venue")?.addEventListener("change", () => {
  updateCredentialFields();
  renderControl(controlState);
});

$("#control-mode")?.addEventListener("change", () => renderControl(controlState));

$("#credential-save")?.addEventListener("click", async () => {
  if (!(controlState.enabled && controlState.local_only)) {
    setText("#control-note", "凭证配置仅允许在交易节点本机的 loopback 面板中使用。" );
    return;
  }
  const venue = $("#control-venue").value;
  const apiKey = $("#credential-key").value;
  const apiSecret = $("#credential-secret").value;
  const passphrase = $("#credential-passphrase").value;
  if (!apiKey || !apiSecret || (venue === "okx-demo" && !passphrase)) {
    setText("#control-note", "请填写当前交易所要求的全部凭证字段。" );
    return;
  }
  if (!window.confirm("凭证只会保存到本机 Demo/Testnet 配置文件，确认保存吗？")) return;
  const button = $("#credential-save");
  button.disabled = true;
  try {
    await controlRequest("/api/control/credentials", { venue, api_key: apiKey, api_secret: apiSecret, passphrase });
    $("#credential-key").value = "";
    $("#credential-secret").value = "";
    $("#credential-passphrase").value = "";
    setText("#control-note", "凭证已保存到本机。现在可以启动只读监控或 Demo/Testnet 模拟下单。" );
    await refresh();
  } catch (error) {
    setText("#control-note", `凭证保存失败 · ${error.message}`);
  } finally {
    button.disabled = false;
  }
});

$("#control-preflight")?.addEventListener("click", async () => {
  if (!(controlState.enabled && controlState.local_only)) {
    setText("#control-note", "预检仅允许在交易节点本机的 loopback 面板中使用。" );
    return;
  }
  const button = $("#control-preflight");
  button.disabled = true;
  setText("#control-note", "预检中 · 只读取账户、品种和对账状态，不提交订单…");
  try {
    const result = await controlRequest("/api/control/preflight", { venue: $("#control-venue").value });
    setText("#control-note", `预检通过 · ${result.instrument_count || 0} 个品种 · 对账 ${result.reconciliation_ok ? "PASS" : "WAITING"} · 未提交订单`);
    await refresh();
  } catch (error) {
    setText("#control-note", `预检失败 · ${error.message}`);
  } finally {
    renderControl(controlState);
  }
});

$("#control-start")?.addEventListener("click", async () => {
  const venue = $("#control-venue").value;
  const mode = $("#control-mode").value;
  const confirmed = $("#control-confirm").checked;
  if (mode === "testnet" && !confirmed) {
    setText("#control-note", "请先确认只使用 Demo/Testnet。" );
    return;
  }
  try {
    await controlRequest("/api/control/start", { venue, mode, confirm_testnet: confirmed });
    await refresh();
  } catch (error) {
    setText("#control-note", `启动失败 · ${error.message}`);
  }
});

$("#control-stop")?.addEventListener("click", async () => {
  try {
    await controlRequest("/api/control/stop");
    await refresh();
  } catch (error) {
    setText("#control-note", `停止失败 · ${error.message}`);
  }
});

async function refresh() {
  try {
    const response = await fetch(panelPath("/api/status"), { cache: "no-store" });
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

loadReplay();
refresh();
window.setInterval(refresh, 15000);
