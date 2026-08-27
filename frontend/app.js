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

function fmtMoney(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return parsed.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPnl(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  const absolute = Math.abs(parsed).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (parsed > 0) return `+${absolute}`;
  if (parsed < 0) return `-${absolute}`;
  return "0.00";
}

function numberClass(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed === 0) return "number-zero";
  return parsed > 0 ? "number-positive" : "number-negative";
}

function setPnl(selector, value, fallback = "—") {
  const element = $(selector);
  if (!element) return;
  element.textContent = fmtPnl(value, fallback);
  element.title = value === null || value === undefined || value === "" ? fallback : String(value);
  element.classList.remove("pnl-positive", "pnl-negative", "pnl-zero");
  const parsed = Number(value);
  element.classList.add(!Number.isFinite(parsed) || parsed === 0 ? "pnl-zero" : parsed > 0 ? "pnl-positive" : "pnl-negative");
}

function firstValue(item, keys) {
  for (const key of keys) {
    if (item?.[key] !== null && item?.[key] !== undefined && item?.[key] !== "") return item[key];
  }
  return null;
}

function localTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
}

function relativeTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function compactSymbol(value) {
  const text = String(value || "—");
  return text.replace(/-USDT-SWAP$|-USD-SWAP$|-SWAP$/i, "");
}

function appendSymbolCell(row, value) {
  const cell = document.createElement("td");
  cell.className = "symbol-cell";
  const strong = document.createElement("strong");
  strong.textContent = compactSymbol(value);
  const small = document.createElement("small");
  small.textContent = String(value || "—").includes("SWAP") ? "SWAP" : "历史品种";
  cell.append(strong, small);
  row.append(cell);
}

function appendPnlCell(row, value) {
  appendCell(row, fmtPnl(value), numberClass(value));
}

function appendDirectionCell(row, value) {
  const cell = document.createElement("td");
  const text = String(value || "").toUpperCase();
  const long = text === "BUY" || text === "LONG" || text === "多" || text === "1";
  const short = text === "SELL" || text === "SHORT" || text === "空" || text === "-1";
  const badge = document.createElement("span");
  badge.className = `direction-badge ${long ? "direction-long" : short ? "direction-short" : "direction-flat"}`;
  badge.textContent = long ? "多" : short ? "空" : text || "—";
  cell.append(badge);
  row.append(cell);
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

const riskReasonLabels = {
  LEVERAGE_LIMIT_OR_UNVERIFIED: "杠杆未核验",
  MARGIN_MODE_NOT_ALLOWED: "保证金模式受限",
  HISTORICAL_TOTAL_EXPOSURE_EXCEEDED: "历史总敞口超限",
  WEBSOCKET_NOT_CONNECTED: "实时连接未建立",
  ACCOUNT_RECONCILIATION_FAILED: "账户对账失败",
  MARKET_DATA_STALE: "行情已过期",
  CLOCK_DRIFT: "服务端时钟偏移",
  KILL_SWITCH_ENGAGED: "手动安全开关已触发",
  ORDERS_DISABLED: "下单未启用",
  TESTNET_CONFIRMATION_REQUIRED: "需要 Demo/Testnet 确认",
};

const strategyBasisLabels = {
  RSI14: "RSI14",
  MACD_HIST: "MACD柱",
  BB_PERCENT_B: "布林带位置",
  MOMENTUM_24H: "24小时动量",
  MA_DISTANCE_24H: "24小时均线距离",
  VOLATILITY_72H: "72小时波动率",
  VOLUME_PERCENTILE_72: "成交量分位数",
  FUNDING_RATE: "资金费率",
  MARK_INDEX_BASIS: "标记/指数基差",
  MERGED_DUPLICATE_SYMBOLS: "重复映射已合并",
};

function strategyBasisText(item) {
  const basis = Array.isArray(item.strategy_basis) ? item.strategy_basis : [];
  if (!basis.length || basis.includes("INDICATORS_INCOMPLETE")) {
    return "暂无完整指标依据，模型仅依据可用历史行为特征";
  }
  const values = basis.map((entry) => {
    const [code, rawValue] = String(entry).split("=");
    const label = strategyBasisLabels[code] || code;
    return rawValue === undefined ? label : `${label}=${rawValue}`;
  }).filter((entry, index, all) => entry && all.indexOf(entry) === index);
  return values.length ? `模型输入依据：${values.join("、")}` : "暂无完整指标依据，模型仅依据可用历史行为特征";
}

function strategyReasonParts(item) {
  const action = String(item.strategy_action || "").toUpperCase();
  const executionReason = String(item.strategy_reason || "").toUpperCase();
  const actionLabel = strategyActionLabels[action] || (action ? `策略动作：${action}` : "策略暂未给出明确动作");
  const executionLabel = executionReasonLabels[executionReason] || "根据策略目标仓位执行";
  const target = item.strategy_target_exposure ? `目标暴露 ${displayNumber(item.strategy_target_exposure)}` : "目标暴露未知";
  const confidence = item.strategy_confidence ? `置信度 ${displayNumber(item.strategy_confidence)}` : "置信度未知";
  const basis = strategyBasisText(item);
  const reasonZh = String(item.strategy_reason_zh || "");
  const sources = Array.isArray(item.strategy_source_symbols) && item.strategy_source_symbols.length > 1
    ? `合并来源：${item.strategy_source_symbols.join(" / ")}`
    : "";
  const tags = (Array.isArray(item.strategy_risk_tags) ? item.strategy_risk_tags : [])
    .map((tag) => riskTagLabels[String(tag).toUpperCase()] || String(tag))
    .filter((tag, index, all) => tag && all.indexOf(tag) === index);
  return { actionLabel, executionLabel, detail: [reasonZh, target, confidence, basis, sources, ...tags].filter(Boolean).join(" · ") };
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

function replayIndicator(value, digits = 4) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: digits });
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
  const indicators = bar.indicators || {};
  setText("#replay-time", replayTime(endTs));
  setText("#replay-price", replayShortNumber(Number(bar.close)));
  setText("#replay-position", lastOrder ? `${replayShortNumber(lastOrder.position_after)} contracts` : "0 contracts");
  setText("#replay-orders", `${orders.length}`);
  setText("#replay-pnl", pnl ? replayShortNumber(pnl.value) : "0");
  setText("#replay-rsi", replayIndicator(indicators.rsi14, 2));
  setText("#replay-macd", replayIndicator(indicators.macd_histogram, 6));
  setText("#replay-bollinger", replayIndicator(indicators.bollinger_percent_b, 4));
  setText("#replay-indicators", indicators.coverage === "COMPLETE" ? "完整" : indicators.coverage === "PARTIAL" ? "部分缺失" : "—");
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
    const venue = $("#replay-venue")?.value || "bitmex";
    const symbol = $("#replay-symbol")?.value || "XBTUSD";
    const response = await fetch(panelPath(`/api/replay?venue=${encodeURIComponent(venue)}&symbol=${encodeURIComponent(symbol)}&limit=1000`), { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    replayState.data = await response.json();
    replayState.cursor = 1000;
    setText("#replay-pnl-unit", replayState.data.pnl_unit || "分析值");
    setText("#replay-note", replayState.data.available ? `${replayState.data.source || "本地历史派生输出"}；指标只使用已关闭 K 线，不代表实时账户权益。` : "本地历史回放数据尚未生成。先完成数据节点同步后，这里会显示时间轴。 ");
    setText("#replay-status", replayState.data.available ? "LOCAL REPLAY READY" : "WAITING FOR DATA");
    drawReplay();
  } catch (error) {
    replayState.data = null;
    setText("#replay-status", "REPLAY UNAVAILABLE");
    setText("#replay-note", `历史回放接口不可用 · ${error.message}`);
  }
}

$("#replay-venue")?.addEventListener("change", () => {
  stopReplay();
  const venue = $("#replay-venue").value;
  const symbol = $("#replay-symbol");
  if (symbol) {
    symbol.replaceChildren();
    const option = document.createElement("option");
    option.value = venue === "hyperliquid" ? "HL-BTC-PERP" : "XBTUSD";
    option.textContent = venue === "hyperliquid" ? "BTC-PERP · Hyperliquid" : "XBTUSD · BitMEX";
    symbol.append(option);
  }
  loadReplay();
});
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
  const risk = runtime.risk || {};
  const hasAccount = account.source && account.source !== "NONE";

  const positionRealized = positions.reduce((total, item) => total + (Number(item.realized_pnl) || 0), 0);
  const unrealizedValues = positions.map((item) => firstValue(item, ["upl", "unrealized_pnl", "unrealizedPnl", "floating_pnl"])).filter((value) => value !== null);
  const unrealized = unrealizedValues.length ? unrealizedValues.reduce((total, value) => total + (Number(value) || 0), 0) : null;
  const fillPnlValues = fills.map((item) => firstValue(item, ["realized_pnl", "pnl", "profit", "closed_pnl"]));
  const hasFillPnl = fillPnlValues.some((value) => value !== null && Number.isFinite(Number(value)));
  const fillRealized = hasFillPnl ? fillPnlValues.reduce((total, value) => total + (Number(value) || 0), 0) : null;
  const accountRealized = firstValue(account, ["realized_pnl", "realizedPnl"]);
  const realized = !hasAccount ? null : accountRealized !== null ? accountRealized : fillRealized !== null ? fillRealized : positionRealized;
  const todayKey = new Date().toLocaleDateString("en-CA");
  const todayFillPnl = hasFillPnl ? fills.filter((item) => item.timestamp && new Date(item.timestamp).toLocaleDateString("en-CA") === todayKey).reduce((total, item) => total + (Number(firstValue(item, ["realized_pnl", "pnl", "profit", "closed_pnl"])) || 0), 0) : null;
  const todayPnl = !hasAccount ? null : todayFillPnl !== null ? todayFillPnl : unrealized !== null ? Number(realized || 0) + unrealized : null;

  setText("#account-source", hasAccount ? `${runtime.plans || 0} 个策略目标` : "等待快照");
  const equityElement = $("#equity-value");
  if (equityElement) {
    equityElement.textContent = hasAccount ? fmtMoney(account.equity) : "—";
    equityElement.title = account.equity === null || account.equity === undefined ? "—" : String(account.equity);
  }
  setText("#equity-unit", account.equity_unit === "USD_EQUIVALENT" ? "USD 估值" : (account.equity_unit || "账户单位"));
  setPnl("#today-pnl", todayPnl);
  setText("#today-pnl-note", todayFillPnl !== null ? "本地自然日 · 成交口径" : "会话已实现 + 未实现");
  setPnl("#unrealized-pnl", unrealized);
  setPnl("#realized-pnl", realized);
  const diagnostic = runtime.last_error || runtime.stop_reason;
  setText("#account-note", diagnostic ? `运行诊断 · ${diagnostic}` : hasAccount ? `${runtime.plans || 0} 个目标信号 · 对账 ${account.reconciliation_ok ? "PASS" : "WAITING"}` : "等待实时账户快照。");
  setText("#position-count", positions.length);
  setText("#order-count", orders.length);
  setText("#fill-count", fills.length);
  setText("#tab-position-count", positions.length);
  setText("#tab-order-count", orders.length);
  setText("#tab-fill-count", fills.length);
  const marginUsed = firstValue(risk, ["margin_used", "marginUsed"]);
  const equityNumber = Number(account.equity);
  const marginRatio = marginUsed !== null && Number.isFinite(equityNumber) && equityNumber !== 0 ? Number(marginUsed) / Math.abs(equityNumber) * 100 : null;
  setText("#margin-usage", marginRatio === null ? "—" : `${marginRatio.toFixed(1)}%`);
  const riskReasons = Array.isArray(risk.block_reasons) ? risk.block_reasons : [];
  const orderBlockReasons = Array.isArray(runtime.order_block_reasons) ? runtime.order_block_reasons : [];
  const allRiskReasons = [...new Set([...riskReasons, ...orderBlockReasons])];
  const feedback = runtime.latest_feedback_at ? ` · 最新成交反馈 ${relativeTime(runtime.latest_feedback_at)}` : "";
  const orderAge = runtime.oldest_active_order_age_seconds == null ? "" : ` · 最老活动订单 ${displayNumber(runtime.oldest_active_order_age_seconds, "0")} 秒`;
  const riskText = allRiskReasons.map((reason) => riskReasonLabels[String(reason).toUpperCase()] || String(reason)).join("、");
  const safety = $("#runtime-safety");
  if (safety) {
    safety.textContent = allRiskReasons.length ? `下单阻断：${riskText}${feedback}${orderAge}` : `风控正常 · 时钟偏移 ${displayNumber(runtime.clock_drift_seconds, "—")} 秒${feedback}${orderAge}`;
    safety.classList.toggle("safe", !allRiskReasons.length);
    safety.classList.toggle("warn", allRiskReasons.length > 0 && !risk.kill_switch_engaged);
    safety.classList.toggle("danger", Boolean(risk.kill_switch_engaged));
    safety.title = allRiskReasons.join(" · ") || "风险条件正常";
  }

  const balanceList = $("#balance-list");
  balanceList.replaceChildren();
  const nonZeroBalances = balances.filter((item) => item.total === null || item.total === undefined || Number(item.total) !== 0);
  if (!nonZeroBalances.length) {
    const empty = document.createElement("span");
    empty.className = "empty-state";
    empty.textContent = "预检或运行后显示余额明细";
    balanceList.append(empty);
  } else {
    nonZeroBalances.slice(0, 12).forEach((item) => {
      const chip = document.createElement("span");
      chip.className = "balance-chip";
      chip.innerHTML = `<b></b><span></span>`;
      chip.querySelector("b").textContent = item.currency || "?";
      chip.querySelector("span").textContent = displayNumber(item.total, "0");
      chip.title = `可用 ${displayNumber(item.available, "0")}`;
      balanceList.append(chip);
    });
  }

  renderRows("#positions-table", positions, "暂无持仓", (item) => {
    const row = document.createElement("tr");
    appendSymbolCell(row, item.symbol);
    const quantity = Number(item.quantity);
    appendDirectionCell(row, firstValue(item, ["posSide", "position_side"]) || (quantity > 0 ? "LONG" : quantity < 0 ? "SHORT" : ""));
    appendCell(row, displayNumber(Math.abs(quantity)));
    appendCell(row, displayNumber(item.average_entry_price));
    appendCell(row, displayNumber(firstValue(item, ["markPx", "mark_price", "markPrice", "last", "last_price", "current_price"])));
    appendPnlCell(row, unrealizedValues.length ? firstValue(item, ["upl", "unrealized_pnl", "unrealizedPnl", "floating_pnl"]) : null);
    appendPnlCell(row, item.realized_pnl);
    appendCell(row, item.leverage === null || item.leverage === undefined ? "—" : `${displayNumber(item.leverage)}x`);
    appendCell(row, displayNumber(firstValue(item, ["margin", "initial_margin", "occupied_margin", "margin_used"])));
    return row;
  }, 9);
  const latestFill = fills.slice().sort((a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0))[0];
  setText("#latest-fill-time", latestFill?.timestamp ? `${localTime(latestFill.timestamp)} · ${relativeTime(latestFill.timestamp)}` : "暂无成交");
  renderRows("#orders-table", orders, "当前无活动委托", (item) => {
    const row = document.createElement("tr");
    appendSymbolCell(row, item.symbol);
    appendDirectionCell(row, item.side);
    appendCell(row, displayNumber(item.quantity));
    appendCell(row, displayNumber(item.price, "市价"));
    appendCell(row, item.status || item.state || "活动", "order-status");
    appendCell(row, localTime(firstValue(item, ["timestamp", "created_at", "transactTime"])), "time-cell");
    appendStrategyReasonCell(row, item);
    return row;
  }, 7);
  renderRows("#fills-table", fills, "暂无成交记录", (item) => {
    const row = document.createElement("tr");
    appendCell(row, localTime(item.timestamp), "time-cell");
    appendSymbolCell(row, item.symbol);
    appendDirectionCell(row, item.side);
    appendCell(row, displayNumber(item.quantity));
    appendCell(row, displayNumber(item.price));
    appendCell(row, displayNumber(item.fee));
    appendPnlCell(row, firstValue(item, ["realized_pnl", "pnl", "profit", "closed_pnl"]));
    const orderId = String(firstValue(item, ["client_order_id", "order_id", "ordId", "clientOid"]) || "—");
    appendCell(row, orderId === "—" ? orderId : orderId.slice(-6));
    return row;
  }, 8);
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

function renderSignals(signals) {
  const list = $("#signal-list");
  if (!list) return;
  list.replaceChildren();
  const rows = Object.values(signals || {}).sort((a, b) => String(a.venue_symbol || a.historical_symbol || "").localeCompare(String(b.venue_symbol || b.historical_symbol || "")));
  if (!rows.length) {
    const empty = document.createElement("span");
    empty.className = "empty-state";
    empty.textContent = "等待策略信号";
    list.append(empty);
    return;
  }
  rows.slice(0, 12).forEach((item) => {
    const card = document.createElement("article");
    card.className = "signal-card";
    const symbol = document.createElement("strong");
    symbol.textContent = item.venue_symbol || item.historical_symbol || "—";
    const action = document.createElement("b");
    action.className = String(item.action || "").includes("LONG") ? "signal-long" : String(item.action || "").includes("SHORT") ? "signal-short" : "signal-neutral";
    action.textContent = item.action || "—";
    const detail = document.createElement("span");
    detail.textContent = `${item.reason_zh || "暂无完整指标依据"} · 目标 ${displayNumber(item.target_exposure)} · 置信度 ${displayNumber(Number(item.confidence) * 100)}%`;
    const basis = document.createElement("small");
    basis.textContent = Array.isArray(item.basis) ? item.basis.join(" · ") : "";
    card.append(symbol, action, detail, basis);
    list.append(card);
  });
}

function render(payload) {
  const localControl = Boolean(payload.control?.enabled && payload.control?.local_only);
  document.body.classList.toggle("public-mode", !localControl);
  const feed = payload.feed_status === "CONNECTED" || payload.runtime?.market_connected === true;
  const badge = $("#feed-badge");
  if (badge) {
    badge.classList.toggle("live", feed);
    badge.classList.toggle("waiting", !feed);
    const activeVenue = (payload.venues || []).find((item) => item.venue === payload.active_venue);
    const venueLabel = activeVenue?.label || payload.active_venue || "DEMO";
    badge.replaceChildren();
    const indicator = document.createElement("i");
    badge.append(indicator, document.createTextNode(`${venueLabel} · ${feed ? "已连接" : "等待连接"}`));
  }

  const runtimeStatus = String(payload.runtime?.status || "WAITING").toUpperCase();
  const runtimeElement = $("#runtime-status");
  if (runtimeElement) {
    runtimeElement.textContent = runtimeStatus.includes("RUNNING") ? "RUNNING" : runtimeStatus.replaceAll("_", " ");
    runtimeElement.classList.toggle("waiting", !runtimeStatus.includes("RUNNING"));
    runtimeElement.classList.toggle("blocked", runtimeStatus.includes("BLOCK") || runtimeStatus.includes("STOP"));
  }

  const updatedAt = payload.updated_at_utc || payload.account?.captured_at_utc;
  const updatedElement = $("#updated-at");
  if (updatedElement) {
    updatedElement.textContent = updatedAt ? relativeTime(updatedAt) : "等待状态源";
    updatedElement.title = updatedAt ? localTime(updatedAt) : "等待状态源";
  }
  const ageSeconds = updatedAt ? Math.max(0, (Date.now() - new Date(updatedAt).getTime()) / 1000) : Infinity;
  const topbar = $("#topbar");
  const heartbeat = $(".heartbeat");
  if (topbar) {
    topbar.classList.toggle("is-stale", ageSeconds > 15 && ageSeconds <= 60);
    topbar.classList.toggle("is-dead", ageSeconds > 60 || !feed);
  }
  if (heartbeat) {
    heartbeat.classList.toggle("live", feed && ageSeconds <= 15);
    heartbeat.classList.toggle("stale", ageSeconds > 15 && ageSeconds <= 60);
    heartbeat.classList.toggle("dead", ageSeconds > 60 || !feed);
  }
  setText("#connection-heartbeat", !feed ? "未连接" : ageSeconds > 60 ? "已过期" : ageSeconds > 15 ? "延迟" : "心跳正常");
  setText("#model-version", payload.model?.version || "—");
  const modelSha = payload.model?.sha256 || "";
  const featureContract = payload.model?.feature_contract_version || "";
  setText("#model-meta", modelSha ? `${modelSha.slice(0, 12)}${featureContract ? ` · ${featureContract}` : ""}` : "—");
  renderVenues(payload.venues || []);
  renderSignals(payload.runtime?.signals || {});
  setText("#allowed-count", payload.mapping?.allowed_count ?? 0);
  const reconciliation = $("#reconciliation");
  if (reconciliation) {
    const reconciliationOk = Boolean(payload.preflight?.reconciliation_ok || payload.account?.reconciliation_ok);
    reconciliation.textContent = `对账 ${reconciliationOk ? "PASS" : "WAITING"}`;
    reconciliation.classList.toggle("state-positive", reconciliationOk);
    reconciliation.classList.toggle("state-warning", !reconciliationOk);
  }
  renderAccount(payload);
  renderControl(payload.control || {});

  const mapping = payload.mapping || {};
  const total = (mapping.allowed_count || 0) + (mapping.monitor_only_count || 0) + (mapping.unavailable_count || 0);
  setText("#mapping-total", total);
  setText("#scope-allowed", mapping.allowed_count || 0);
  setText("#scope-monitor", mapping.monitor_only_count || 0);
  setText("#scope-unavailable", mapping.unavailable_count || 0);
  const width = (number) => total ? `${Math.max(2, Math.round((number / total) * 100))}%` : "0%";
  $("#bar-allowed")?.style && ($("#bar-allowed").style.width = width(mapping.allowed_count || 0));
  $("#bar-monitor")?.style && ($("#bar-monitor").style.width = width(mapping.monitor_only_count || 0));
  $("#bar-unavailable")?.style && ($("#bar-unavailable").style.width = width(mapping.unavailable_count || 0));

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
  recordSessionEquity(payload.account?.equity, updatedAt);
  renderRuntimeLog(payload, allRuntimeLogEntries(payload));
  drawSessionEquity();
}

const sessionEquityKey = "q01.session-equity.v1";
const runtimeLogState = { entries: [], signatures: new Set() };

function loadSessionEquity() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(sessionEquityKey) || "[]");
    return Array.isArray(parsed) ? parsed.filter((point) => Number.isFinite(Number(point.equity)) && point.ts) : [];
  } catch (_error) {
    return [];
  }
}

function recordSessionEquity(equity, timestamp) {
  const value = Number(equity);
  if (!Number.isFinite(value)) return;
  const points = loadSessionEquity();
  const now = timestamp || new Date().toISOString();
  const last = points.at(-1);
  if (!last || last.ts !== now) points.push({ ts: now, equity: value });
  while (points.length > 240) points.shift();
  try { window.localStorage.setItem(sessionEquityKey, JSON.stringify(points)); } catch (_error) { /* private browsing/storage limits */ }
}

function drawSessionEquity() {
  const canvas = $("#equity-session-chart");
  const points = loadSessionEquity();
  const empty = $("#curve-empty");
  if (!canvas || points.length < 2) {
    empty?.classList.remove("has-data");
    return;
  }
  empty?.classList.add("has-data");
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, Math.floor(rect.width));
  const height = Math.max(180, Math.floor(rect.height));
  const ratio = window.devicePixelRatio || 1;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const pad = { left: 66, right: 16, top: 16, bottom: 28 };
  const values = points.map((point) => Number(point.equity));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(0.01, max - min);
  const floor = min - span * .12;
  const ceiling = max + span * .12;
  const innerWidth = width - pad.left - pad.right;
  const innerHeight = height - pad.top - pad.bottom;
  const x = (index) => pad.left + (index / Math.max(1, points.length - 1)) * innerWidth;
  const y = (value) => pad.top + ((ceiling - value) / Math.max(.01, ceiling - floor)) * innerHeight;
  ctx.font = "10px IBM Plex Mono, SFMono-Regular, Consolas, monospace";
  ctx.lineWidth = 1;
  ctx.strokeStyle = "#1e2630";
  ctx.fillStyle = "#8b97a4";
  for (let row = 0; row <= 3; row += 1) {
    const yy = pad.top + innerHeight * row / 3;
    ctx.beginPath(); ctx.moveTo(pad.left, yy); ctx.lineTo(width - pad.right, yy); ctx.stroke();
    const label = fmtMoney(ceiling - (ceiling - floor) * row / 3);
    ctx.fillText(label, 8, yy + 3);
  }
  ctx.strokeStyle = "#3ee0c5";
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((point, index) => { const px = x(index); const py = y(Number(point.equity)); if (index === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py); });
  ctx.stroke();
  const last = points.at(-1);
  ctx.fillStyle = "#3ee0c5";
  ctx.beginPath(); ctx.arc(x(points.length - 1), y(Number(last.equity)), 3, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#8b97a4";
  ctx.fillText(localTime(points[0].ts), pad.left, height - 8);
  ctx.textAlign = "right";
  ctx.fillText(`${relativeTime(last.ts)} · ${fmtMoney(last.equity)}`, width - pad.right, height - 8);
  ctx.textAlign = "left";
}

function allRuntimeLogEntries(payload) {
  const runtime = payload.runtime || {};
  const risk = runtime.risk || {};
  const updatedAt = payload.updated_at_utc || payload.account?.captured_at_utc || new Date().toISOString();
  const reasons = [...new Set([...(risk.block_reasons || []), ...(runtime.order_block_reasons || [])])];
  const entries = [
    { kind: "STATUS", text: `运行状态 · ${String(runtime.status || "WAITING").replaceAll("_", " ")}`, ts: updatedAt },
    { kind: "ACCOUNT", text: `账户对账 · ${payload.account?.reconciliation_ok ? "PASS" : "WAITING"}`, ts: payload.account?.captured_at_utc || updatedAt },
  ];
  if (reasons.length) entries.push({ kind: "RISK", text: `下单阻断 · ${reasons.map((reason) => riskReasonLabels[String(reason).toUpperCase()] || reason).join("、")}`, ts: updatedAt });
  if (runtime.latest_feedback_at) entries.push({ kind: "FILL", text: "收到最新成交反馈", ts: runtime.latest_feedback_at });
  return entries;
}

function renderRuntimeLog(_payload, entries) {
  const list = $("#runtime-log");
  if (!list) return;
  entries.forEach((entry) => {
    const signature = `${entry.kind}|${entry.ts}|${entry.text}`;
    if (runtimeLogState.signatures.has(signature)) return;
    runtimeLogState.signatures.add(signature);
    runtimeLogState.entries.unshift(entry);
  });
  runtimeLogState.entries = runtimeLogState.entries.slice(0, 40);
  list.replaceChildren();
  if (!runtimeLogState.entries.length) {
    const empty = document.createElement("li");
    empty.className = "log-empty";
    empty.textContent = "等待状态事件";
    list.append(empty);
    return;
  }
  runtimeLogState.entries.forEach((entry) => {
    const item = document.createElement("li");
    const time = document.createElement("time");
    time.textContent = `${localTime(entry.ts)} · ${relativeTime(entry.ts)}`;
    const text = document.createElement("span");
    text.className = "log-text";
    text.innerHTML = `<b class="log-kind"></b><span></span>`;
    text.querySelector(".log-kind").textContent = entry.kind;
    text.querySelector("span").textContent = entry.text;
    item.append(time, text);
    list.append(item);
  });
}

function selectTab(name) {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    const active = button.dataset.tab === name;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    const active = panel.id === `tab-${name}`;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });
  if (name === "curve") window.requestAnimationFrame(drawSessionEquity);
}

document.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => selectTab(button.dataset.tab)));
$("#refresh-button")?.addEventListener("click", () => refresh());
$("#control-open")?.addEventListener("click", () => {
  const drawer = $("#control-drawer");
  if (!drawer) return;
  drawer.hidden = !drawer.hidden;
  $("#control-open").setAttribute("aria-expanded", String(!drawer.hidden));
  if (!drawer.hidden) drawer.scrollIntoView({ behavior: "smooth", block: "nearest" });
});
window.addEventListener("resize", () => { if (!$("#tab-curve")?.hidden) drawSessionEquity(); });

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
  const kill = $("#control-kill");
  const clearKill = $("#control-clear-kill");
  const form = $("#credential-form");
  const credentialStatus = $("#credential-status");
  if (!status || !note || !start || !stop) return;
  updateCredentialFields();
  const selectedVenue = $("#control-venue")?.value || "okx-demo";
  const testnetMode = $("#control-mode")?.value === "testnet";
  const credentialSetupAvailable = control.credential_setup_available !== false;
  const configured = !credentialSetupAvailable || control.credential_statuses?.[selectedVenue] === "CONFIGURED";
  const killEngaged = Boolean(control.kill_switch_engaged);
  status.textContent = !enabled ? "公开只读" : killEngaged ? "安全停机已触发" : running ? `运行中 · ${control.venue}` : "本机控制已就绪";
  if (form) form.hidden = !enabled || !credentialSetupAvailable;
  if (credentialStatus) credentialStatus.textContent = configured ? "已配置" : "未配置";
  start.disabled = !enabled || running || (testnetMode && !configured);
  stop.disabled = !enabled || !running;
  if (preflight) preflight.disabled = !enabled || running || !configured;
  if (kill) kill.disabled = !enabled || killEngaged;
  if (clearKill) clearKill.disabled = !enabled || !killEngaged;
  if (!enabled) {
    note.textContent = "公开页只显示控制入口，按钮不可操作；请通过 SSH 隧道打开交易节点本机控制页后使用。";
  } else if (!credentialSetupAvailable) {
    note.textContent = "Windows 节点请使用启动器的 DPAPI 凭证流程；Linux 交易节点可在本区配置凭证。";
  } else if (running) {
    note.textContent = `本机节点已启动：${control.venue} · ${control.mode}。凭证不会进入网页。`;
  } else if (killEngaged) {
    note.textContent = "安全停机已触发：停止新增订单并撤销机器人活动订单，现有持仓保留；解除后需重新预检。";
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

$("#control-kill")?.addEventListener("click", async () => {
  if (!(controlState.enabled && controlState.local_only)) {
    setText("#control-note", "安全停机仅允许在交易节点本机的 loopback 面板中使用。");
    return;
  }
  if (!window.confirm("确认安全停机？将停止新增订单并撤销机器人活动订单，但保留现有持仓。")) return;
  try {
    await controlRequest("/api/control/kill-switch");
    await refresh();
  } catch (error) {
    setText("#control-note", `安全停机失败 · ${error.message}`);
  }
});

$("#control-clear-kill")?.addEventListener("click", async () => {
  if (!(controlState.enabled && controlState.local_only)) {
    setText("#control-note", "解除安全停机仅允许在交易节点本机的 loopback 面板中使用。");
    return;
  }
  if (!window.confirm("确认解除安全停机？解除后仍需重新预检，才会恢复 Demo 运行。")) return;
  try {
    await controlRequest("/api/control/kill-switch/clear");
    await refresh();
  } catch (error) {
    setText("#control-note", `解除安全停机失败 · ${error.message}`);
  }
});

async function refresh() {
  try {
    const response = await fetch(panelPath("/api/status"), { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    setText("#updated-at", "状态接口不可用");
    setText("#connection-heartbeat", "接口异常");
    const badge = $("#feed-badge");
    if (badge) {
      badge.classList.remove("live");
      badge.classList.add("waiting");
      badge.innerHTML = "<i></i>OKX DEMO · 接口异常";
    }
    $("#topbar")?.classList.add("is-dead");
    console.warn("dashboard refresh failed", error);
  }
}

loadReplay();
refresh();
window.setInterval(refresh, 5000);
