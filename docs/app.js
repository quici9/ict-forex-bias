/**
 * ICT Forex Bias Dashboard — app.js
 * Vanilla JS · No dependencies · Reads live_stats.json + live_performance.jsonl
 */

'use strict';

// ── Constants ──────────────────────────────────────────────────────────────

const BACKTEST_PER_SYMBOL = {
  'NZD/USD': 0.729,
  'USD/CAD': 0.667,
  'USD/JPY': 0.663,
  'EUR/USD': 0.662,
  'AUD/USD': 0.648,
  'USD/CHF': 0.643,
  'GBP/USD': 0.642,
  'GBP/JPY': 0.500,
};

const SYMBOL_ORDER = [
  'NZD/USD', 'USD/CAD', 'USD/JPY', 'EUR/USD',
  'AUD/USD', 'USD/CHF', 'GBP/USD', 'GBP/JPY',
];

const SYMBOL_TIERS = {
  'NZD/USD': 'HIGH',
  'USD/CAD': 'HIGH',
  'USD/JPY': 'HIGH',
  'EUR/USD': 'HIGH',
  'AUD/USD': 'NORMAL',
  'USD/CHF': 'NORMAL',
  'GBP/USD': 'NORMAL',
  'GBP/JPY': 'LOW',
};

const FIRST_LIVE_DATE = '2026-03-24';

// GitHub Pages serves only the docs/ directory.
// Data files are copied into docs/data/ by the CI workflow.
const DATA_STATS_URL   = './data/live_stats.json';
const DATA_SIGNALS_URL = './data/live_performance.jsonl';

const SIGNAL_EMOJI = { BULLISH: '🟢', BEARISH: '🔴', NEUTRAL: '⚪' };
const LOW_TIER_EMOJI = { BULLISH: '🟡', BEARISH: '🟠', NEUTRAL: '⚫' };

// ── Utility ────────────────────────────────────────────────────────────────

/**
 * Format a date string (YYYY-MM-DD or ISO) to "Mon 24 Mar 2026".
 */
function formatDate(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr.slice(0, 10) + 'T12:00:00');
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
}

/**
 * Format UTC ISO timestamp to local time string.
 */
function formatTimestamp(isoStr) {
  if (!isoStr) return '—';
  const d = new Date(isoStr);
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' });
}

/**
 * Return today's date as YYYY-MM-DD in UTC.
 */
function todayUTC() {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Return the most recent trading date to display signals for.
 * Uses today if today >= FIRST_LIVE_DATE, else uses FIRST_LIVE_DATE (preview mode).
 */
function getSignalDisplayDate(signals) {
  if (!signals.length) return null;
  // Group by date and return the latest date
  const dates = [...new Set(signals.map(s => s.date))].sort();
  return dates[dates.length - 1] || null;
}

/**
 * Format close_pct_beyond as "+27% beyond High(T-2)".
 */
function formatClosePct(signal) {
  if (!signal.close_pct || signal.close_pct === 0) return '';
  const pct  = Math.round(signal.close_pct * 100);
  const side = signal.predicted === 'BULLISH' ? 'High(T-2)' : 'Low(T-2)';
  const sign = signal.predicted === 'BULLISH' ? '+' : '−';
  return `${sign}${pct}% beyond ${side}`;
}

/**
 * Clamp a value 0–1 to a CSS percentage.
 */
function toPercent(value) {
  if (value === null || value === undefined || isNaN(value)) return null;
  return (value * 100).toFixed(1) + '%';
}

/**
 * Return CSS class for a precision value.
 */
function precisionClass(value) {
  if (value === null || value === undefined) return 'muted';
  if (value >= 0.65) return 'bullish-color';
  if (value >= 0.55) return 'blue-color';
  if (value >= 0.50) return 'warn-color';
  return 'bearish-color';
}

/**
 * Return bar class based on precision.
 */
function barClass(value) {
  if (value === null || value === undefined) return '';
  if (value >= 0.65) return 'high';
  if (value >= 0.55) return 'medium';
  if (value >= 0.50) return 'low';
  return 'very-low';
}

// ── Data Layer ─────────────────────────────────────────────────────────────

async function fetchLiveStats() {
  const res = await fetch(DATA_STATS_URL, { cache: 'no-store' });
  if (!res.ok) throw new Error(`live_stats.json fetch failed: ${res.status}`);
  return res.json();
}

async function fetchSignalLog() {
  const res = await fetch(DATA_SIGNALS_URL, { cache: 'no-store' });
  if (!res.ok) throw new Error(`live_performance.jsonl fetch failed: ${res.status}`);
  const text = await res.text();
  return text
    .split('\n')
    .filter(line => line.trim())
    .map(line => {
      try { return JSON.parse(line); }
      catch { return null; }
    })
    .filter(Boolean);
}

// ── Rendering ─────────────────────────────────────────────────────────────

/**
 * Render the header last-updated meta and status dot.
 */
function renderHeaderMeta(stats) {
  const lastUpdatedEl = document.getElementById('meta-last-updated');
  if (lastUpdatedEl && stats.last_updated) {
    lastUpdatedEl.textContent = formatTimestamp(stats.last_updated);
  }
}

/**
 * Render alert banner if precision alert is active.
 */
function renderAlertBanner(stats) {
  const banner = document.getElementById('alert-banner');
  if (!banner) return;
  if (stats.alert) {
    banner.classList.add('visible');
    const roll = stats.rolling_20d_precision;
    const rollStr = roll !== null ? `(${toPercent(roll)})` : '';
    document.getElementById('alert-message').textContent =
      `⚠️  Rolling 20-day precision ${rollStr} is below 50% threshold — review required.`;
  }
}

/**
 * Render Today's Signals section.
 */
function renderTodaySignals(signals) {
  const container = document.getElementById('signals-container');
  const dateHeading = document.getElementById('signals-date');
  if (!container) return;

  const displayDate = getSignalDisplayDate(signals);
  const todaySignals = displayDate
    ? signals.filter(s => s.date === displayDate)
    : [];

  if (displayDate && dateHeading) {
    dateHeading.textContent = `Daily Bias — ${formatDate(displayDate)}`;
  } else if (dateHeading) {
    dateHeading.textContent = 'Daily Bias — Awaiting First Signal';
  }

  // Separate: NORMAL active signals, LOW tier signals, NEUTRALs
  const normalActive  = todaySignals.filter(s => s.predicted !== 'NEUTRAL' && s.confidence !== 'LOW');
  const lowTierActive = todaySignals.filter(s => s.predicted !== 'NEUTRAL' && s.confidence === 'LOW');
  const neutrals      = todaySignals.filter(s => s.predicted === 'NEUTRAL');

  // Sort by close_pct descending within each group
  const sortByPct = arr => arr.sort((a, b) => (b.close_pct || 0) - (a.close_pct || 0));

  const allOrdered = [
    ...sortByPct(normalActive),
    ...sortByPct(lowTierActive),
    ...neutrals,
  ];

  if (!allOrdered.length) {
    container.innerHTML = `
      <div class="signals-empty">
        <div class="signals-empty-icon">📡</div>
        <div class="signals-empty-title">No signals yet</div>
        <div class="signals-empty-sub">
          First live signal: ${formatDate(FIRST_LIVE_DATE)} · 
          GitHub Actions runs daily at 08:45 VN time (Mon–Fri)
        </div>
      </div>`;
    return;
  }

  const cards = allOrdered.map((s, i) => {
    const isLow     = s.confidence === 'LOW';
    const isNeutral = s.predicted === 'NEUTRAL';
    const emoji     = isLow ? LOW_TIER_EMOJI[s.predicted] : SIGNAL_EMOJI[s.predicted];
    const biasClass = s.predicted.toLowerCase();
    const cardClass = [
      'signal-card',
      isNeutral ? 'neutral' : biasClass,
      isLow ? 'low-tier' : '',
    ].join(' ').trim();

    const pctText   = isNeutral ? '—' : formatClosePct(s);
    const warnBadge = isLow
      ? `<span class="signal-warn-badge">⚠️ LOW TIER · 50% precision</span>`
      : '';

    const patternLabel = s.pattern === 'CONTINUATION' ? 'Continuation' : s.pattern || '—';

    return `
      <div class="${cardClass}" style="animation-delay: ${i * 0.05}s">
        <span class="signal-emoji" aria-label="${s.predicted}">${emoji}</span>
        <div class="signal-main">
          <span class="signal-symbol">${s.symbol}</span>
          <span class="signal-desc">${isNeutral ? 'No signal today' : patternLabel} ${warnBadge}</span>
        </div>
        <div class="signal-meta">
          <span class="signal-bias ${biasClass}">${s.predicted}</span>
          <span class="signal-pct">${pctText}</span>
        </div>
      </div>`;
  }).join('');

  // If there were no active signals (all neutral or empty date)
  const activeCount = normalActive.length + lowTierActive.length;
  const neutralInfo = neutrals.length
    ? `<div class="signal-card neutral" style="animation-delay:${allOrdered.length * 0.05}s;opacity:0.4;font-size:0.78rem;color:var(--text-muted);display:flex;align-items:center;gap:0.5rem;padding:0.625rem 1.125rem;">
        <span>⚪</span>
        <span>NEUTRAL: ${neutrals.map(s => s.symbol).join(' · ')}</span>
       </div>`
    : '';

  if (activeCount === 0 && neutrals.length > 0) {
    container.innerHTML = `
      <div class="signals-empty">
        <div class="signals-empty-icon">😴</div>
        <div class="signals-empty-title">No actionable signals today</div>
        <div class="signals-empty-sub">All 8 pairs are NEUTRAL · No continuation pattern detected</div>
      </div>`;
    return;
  }

  container.innerHTML = cards + neutralInfo;
}

/**
 * Render KPI cards.
 */
function renderKPICards(stats) {
  const base     = stats.baseline_backtest || {};
  const live     = stats.overall_precision;
  const roll20   = stats.rolling_20d_precision;
  const total    = stats.total_signals || 0;
  const correct  = stats.total_correct || 0;
  const alert    = stats.alert;

  // Baseline Precision
  const baselineEl = document.getElementById('kpi-baseline');
  if (baselineEl) {
    baselineEl.innerHTML = `
      <div class="kpi-label">Baseline Precision</div>
      <div class="kpi-value bullish-color">${toPercent(base.precision || 0.648)}</div>
      <div class="kpi-sub">Backtest test set · ${base.test_period || '2025–2026'}</div>`;
    baselineEl.style.setProperty('--accent-color', 'var(--bullish)');
  }

  // Live Precision
  const liveEl = document.getElementById('kpi-live');
  if (liveEl) {
    const liveStr   = live !== null && live !== undefined ? toPercent(live) : '—';
    const liveClass = live !== null ? precisionClass(live) : 'muted';
    const sigStr    = total ? `${correct}/${total} correct` : 'No signals yet';
    liveEl.innerHTML = `
      <div class="kpi-label">Live Precision</div>
      <div class="kpi-value ${liveClass}">${liveStr}</div>
      <div class="kpi-sub">${sigStr}</div>`;
    liveEl.style.setProperty('--accent-color', live !== null ? 'var(--accent-blue)' : 'var(--border-subtle)');
  }

  // Rolling 20d
  const rollEl = document.getElementById('kpi-rolling');
  if (rollEl) {
    const rollStr   = roll20 !== null && roll20 !== undefined ? toPercent(roll20) : '—';
    const rollClass = roll20 !== null ? precisionClass(roll20) : 'muted';
    const rollNote  = total < 20
      ? `Need ${20 - total} more signals`
      : (alert ? '⚠️ Below threshold' : 'Healthy range');
    rollEl.innerHTML = `
      <div class="kpi-label">Rolling 20-Day</div>
      <div class="kpi-value ${rollClass}">${rollStr}</div>
      <div class="kpi-sub">${rollNote}</div>`;
    rollEl.style.setProperty('--accent-color', roll20 !== null && alert ? 'var(--bearish)' : 'var(--accent-blue)');
    if (alert) rollEl.classList.add('alert-active');
  }

  // Walk-Forward
  const wfEl = document.getElementById('kpi-walkforward');
  if (wfEl) {
    const wf = base.walk_forward || '7/7 windows passed';
    wfEl.innerHTML = `
      <div class="kpi-label">Walk-Forward</div>
      <div class="kpi-value bullish-color">7/7</div>
      <div class="kpi-sub">Sharpe 4.94 · Min 57.8%</div>`;
    wfEl.style.setProperty('--accent-color', 'var(--bullish)');
  }
}

/**
 * Render per-symbol performance table.
 */
function renderSymbolTable(stats, signals) {
  const tbody = document.getElementById('symbol-table-body');
  if (!tbody) return;

  // Count live signals per symbol
  const liveMap = {};
  for (const s of signals) {
    if (s.predicted === 'NEUTRAL' || !s.correct !== undefined) continue;
    if (!liveMap[s.symbol]) liveMap[s.symbol] = { total: 0, correct: 0 };
    if (s.correct !== null && s.correct !== undefined) {
      liveMap[s.symbol].total++;
      if (s.correct) liveMap[s.symbol].correct++;
    }
  }

  // Live per_symbol from stats
  const livePerSymbol = stats.per_symbol || {};

  const rows = SYMBOL_ORDER.map(symbol => {
    const tier         = SYMBOL_TIERS[symbol];
    const backtest     = BACKTEST_PER_SYMBOL[symbol];
    const liveData     = livePerSymbol[symbol];
    const livePrec     = liveData ? liveData.precision : null;
    const liveSigs     = liveData ? liveData.total : 0;

    const backtestPct  = toPercent(backtest);
    const livePct      = livePrec !== null ? toPercent(livePrec) : '—';
    const livePctClass = livePrec !== null ? precisionClass(livePrec) : 'muted';

    const barFill      = (backtest * 100).toFixed(0);
    const bClass       = barClass(backtest);

    const tierFlags = { HIGH: '●', NORMAL: '●', LOW: '⚠' };

    return `
      <tr>
        <td class="text-mono" style="font-weight:600">${symbol}</td>
        <td>
          <span class="tier-badge ${tier}">${tierFlags[tier]} ${tier}</span>
        </td>
        <td>
          <div class="precision-bar-wrap">
            <div class="precision-bar-track">
              <div class="precision-bar-fill ${bClass}" style="width:${barFill}%"></div>
            </div>
            <span class="precision-pct text-mono ${precisionClass(backtest)}">${backtestPct}</span>
          </div>
        </td>
        <td class="text-mono ${livePctClass}">${livePct}</td>
        <td class="text-center text-mono" style="color:var(--text-muted)">${liveSigs || '—'}</td>
      </tr>`;
  });

  tbody.innerHTML = rows.join('');
}

/**
 * Render signal history table (last 20 records).
 */
function renderSignalHistory(signals) {
  const tbody = document.getElementById('history-table-body');
  const countEl = document.getElementById('history-count');
  if (!tbody) return;

  // Show only signals with actual recorded (or all, newest first)
  const sorted = [...signals]
    .sort((a, b) => new Date(b.logged_at || b.date) - new Date(a.logged_at || a.date))
    .slice(0, 20);

  if (countEl) {
    countEl.textContent = signals.length ? `(${signals.length} total)` : '';
  }

  if (!sorted.length) {
    tbody.innerHTML = `
      <tr class="table-empty-row">
        <td colspan="6">No signals recorded yet · Go-live: ${formatDate(FIRST_LIVE_DATE)}</td>
      </tr>`;
    return;
  }

  const rows = sorted.map(s => {
    let resultBadge = '<span class="result-badge pending" title="Pending">·</span>';
    if (s.correct === true)  resultBadge = '<span class="result-badge correct" title="Correct">✓</span>';
    if (s.correct === false) resultBadge = '<span class="result-badge incorrect" title="Incorrect">✗</span>';

    const biasColor = s.predicted === 'BULLISH' ? 'bullish-color'
                    : s.predicted === 'BEARISH' ? 'bearish-color' : '';
    const actualColor = s.actual === 'BULLISH' ? 'style="color:var(--bullish)"'
                      : s.actual === 'BEARISH' ? 'style="color:var(--bearish)"' : '';

    const pctFormatted = s.close_pct
      ? `${(s.close_pct * 100).toFixed(0)}%`
      : '—';

    const isLowTierSymbol = SYMBOL_TIERS[s.symbol] === 'LOW';
    const tierMarker = isLowTierSymbol ? ' ⚠️' : '';

    return `
      <tr>
        <td class="text-mono" style="color:var(--text-secondary)">${formatDate(s.date)}</td>
        <td class="text-mono" style="font-weight:600">${s.symbol}${tierMarker}</td>
        <td class="text-mono ${biasColor}">${s.predicted}</td>
        <td class="text-mono" ${actualColor}>${s.actual || '—'}</td>
        <td class="text-center">${resultBadge}</td>
        <td class="text-mono" style="color:var(--text-muted)">${pctFormatted}</td>
      </tr>`;
  }).join('');

  tbody.innerHTML = rows;
}

// ── Bootstrap ──────────────────────────────────────────────────────────────

async function bootstrap() {
  // Show loading state
  document.getElementById('signals-container').innerHTML = `
    <div class="loading-state">
      <span class="loading-spinner"></span>
      <span>Loading signals…</span>
    </div>`;

  const kpiIds = ['kpi-baseline', 'kpi-live', 'kpi-rolling', 'kpi-walkforward'];
  kpiIds.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = `<div class="kpi-label">&nbsp;</div><div class="kpi-value muted">…</div>`;
  });

  try {
    const [stats, signals] = await Promise.all([fetchLiveStats(), fetchSignalLog()]);

    renderHeaderMeta(stats);
    renderAlertBanner(stats);
    renderKPICards(stats);
    renderTodaySignals(signals);
    renderSymbolTable(stats, signals);
    renderSignalHistory(signals);

    // Update last-updated in footer
    const footerUpdated = document.getElementById('footer-updated');
    if (footerUpdated && stats.last_updated) {
      footerUpdated.textContent = `Data: ${new Date(stats.last_updated).toLocaleString('en-GB', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
      })}`;
    }
  } catch (err) {
    console.error('[ICT Dashboard] Data load error:', err);
    const errMsg = `
      <div class="signals-empty">
        <div class="signals-empty-icon">⚠️</div>
        <div class="signals-empty-title">Could not load data</div>
        <div class="signals-empty-sub">
          ${err.message}<br>
          If running locally, use <code>python -m http.server 8080 --directory .</code> from repo root.
        </div>
      </div>`;
    const container = document.getElementById('signals-container');
    if (container) container.innerHTML = errMsg;
  }
}

document.addEventListener('DOMContentLoaded', bootstrap);
