'use strict';

// RAILWAY_URL is replaced at build time by Netlify env var, or uses proxy redirect
const API = typeof RAILWAY_BACKEND_URL !== 'undefined' ? RAILWAY_BACKEND_URL : '';
let statsData = null;
let predsData = null;
const charts = {};

// ─── Tabs ─────────────────────────────────────────────────
function switchTab(name, triggerEl) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`tab-${name}`).classList.add('active');
  if (triggerEl) triggerEl.classList.add('active');

  if (name === 'predictions' && !predsData) fetchPredictions();
  if (name === 'history') fetchHistory();
  if (name === 'wolfram') fetchWolframInsight();
}

// ─── Init ─────────────────────────────────────────────────
async function init() {
  await fetchStats();
  fetchPredictions();
  startCountdown();
  setInterval(pollHealth, 300000);
}

// ─── Stats ────────────────────────────────────────────────
async function fetchStats() {
  try {
    const res = await fetch(`${API}/api/stats`);
    if (!res.ok) {
      showToast('Aguardando dados... clique em Sincronizar', 'info');
      return;
    }
    statsData = await res.json();
    renderStats();
  } catch (e) {
    showToast('Erro ao buscar estatísticas', 'error');
  }
}

function renderStats() {
  if (!statsData) return;
  const s = statsData;

  setText('kpi-total', s.total_draws.toLocaleString('pt-BR'));
  setText('kpi-concurso', `#${s.last_concurso}`);
  setText('kpi-data', formatDate(s.last_data));
  setText('kpi-mean', s.sum_stats.mean);
  setText('kpi-mean-sub', `desvio ±${s.sum_stats.std}`);
  setText('kpi-even', `${s.even_odd_avg.even} pares`);
  setText('kpi-odd', `${s.even_odd_avg.odd} ímpares`);

  setText('status-text', `Concurso #${s.last_concurso} · ${s.total_draws} sorteios`);

  renderAllBalls();
  renderLastDraw();
  renderCharts();
  renderHeatmap();
  renderPairsList();
  renderTriosList();
}

// ─── Balls ────────────────────────────────────────────────
function getBallClass(num) {
  if (!statsData) return 'ball-neutral';
  const hot = statsData.hot_numbers || [];
  const cold = statsData.cold_numbers || [];
  const due = statsData.due_numbers || [];
  const rank = hot.indexOf(num);

  if (due.includes(num)) return 'ball-due';
  if (rank === 0 || rank === 1 || rank === 2) return 'ball-hot';
  if (rank >= 3 && rank <= 6) return 'ball-warm';
  if (cold.slice(-5).includes(num)) return 'ball-cold';
  return 'ball-neutral';
}

function renderAllBalls() {
  const container = document.getElementById('all-balls');
  container.innerHTML = '';
  for (let n = 1; n <= 25; n++) {
    const div = document.createElement('div');
    div.className = `ball ${getBallClass(n)}`;
    div.textContent = n;
    div.title = `Frequência: ${statsData.frequency[n]} (${statsData.frequency_pct[n]}%) | Atraso: ${statsData.recency[n]}`;
    container.appendChild(div);
  }
}

function renderLastDraw() {
  const container = document.getElementById('last-draw-balls');
  container.innerHTML = '';
  (statsData.last_draw || []).forEach(n => {
    const div = document.createElement('div');
    div.className = 'ball ball-selected';
    div.textContent = n;
    container.appendChild(div);
  });
}

// ─── Charts ───────────────────────────────────────────────
function destroyChart(id) {
  if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}

function renderCharts() {
  renderFrequencyChart();
  renderEvenOddChart();
  renderSumChart();
  renderDecadeChart();
  renderRecentChart();
}

function renderFrequencyChart() {
  destroyChart('freq');
  const labels = Array.from({length: 25}, (_, i) => i + 1);
  const data = labels.map(n => statsData.frequency[n]);
  const hotSet = new Set(statsData.hot_numbers);
  const coldSet = new Set(statsData.cold_numbers);
  const colors = labels.map(n =>
    hotSet.has(n) ? '#ff5252' : coldSet.has(n) ? '#448aff' : '#00c853'
  );

  charts['freq'] = new Chart(document.getElementById('chart-freq'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Frequência',
        data,
        backgroundColor: colors,
        borderRadius: 4,
      }]
    },
    options: chartOptions('Dezena', 'Aparições', false)
  });
}

function renderEvenOddChart() {
  destroyChart('evenodd');
  const {even, odd} = statsData.even_odd_avg;
  charts['evenodd'] = new Chart(document.getElementById('chart-evenodd'), {
    type: 'doughnut',
    data: {
      labels: [`Pares (${even})`, `Ímpares (${odd})`],
      datasets: [{
        data: [even, odd],
        backgroundColor: ['#448aff', '#ff5252'],
        borderColor: '#161b22',
        borderWidth: 3,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#e6edf3', font: { size: 12 } } }
      }
    }
  });
}

function renderSumChart() {
  destroyChart('sum');
  charts['sum'] = new Chart(document.getElementById('chart-sum'), {
    type: 'bar',
    data: {
      labels: statsData.sum_buckets,
      datasets: [{
        label: 'Sorteios',
        data: statsData.sum_distribution,
        backgroundColor: 'rgba(0,200,83,0.6)',
        borderColor: '#00c853',
        borderWidth: 1,
        borderRadius: 3,
      }]
    },
    options: chartOptions('Faixa de Soma', 'Sorteios', false)
  });
}

function renderDecadeChart() {
  destroyChart('decade');
  const decade = statsData.decade_dist;
  charts['decade'] = new Chart(document.getElementById('chart-decade'), {
    type: 'radar',
    data: {
      labels: Object.keys(decade),
      datasets: [{
        label: 'Média por grupo',
        data: Object.values(decade),
        backgroundColor: 'rgba(0,200,83,0.2)',
        borderColor: '#00c853',
        pointBackgroundColor: '#00c853',
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        r: {
          ticks: { color: '#8b949e', backdropColor: 'transparent' },
          grid: { color: '#30363d' },
          pointLabels: { color: '#e6edf3' },
        }
      },
      plugins: { legend: { labels: { color: '#e6edf3' } } }
    }
  });
}

function renderRecentChart() {
  destroyChart('recent');
  const labels = Array.from({length: 25}, (_, i) => i + 1);
  const data = labels.map(n => statsData.frequency_recent[n] || 0);
  const colors = data.map(v => {
    const max = Math.max(...data);
    const ratio = v / max;
    if (ratio > 0.75) return '#ff5252';
    if (ratio > 0.5) return '#ff8a65';
    if (ratio < 0.25) return '#448aff';
    return '#00c853';
  });

  charts['recent'] = new Chart(document.getElementById('chart-recent'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Aparições (últ. 20)',
        data,
        backgroundColor: colors,
        borderRadius: 4,
      }]
    },
    options: chartOptions('Dezena', 'Aparições', false)
  });
}

function chartOptions(xLabel, yLabel, legend = true) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: legend, labels: { color: '#e6edf3' } },
      tooltip: {
        backgroundColor: '#21262d',
        titleColor: '#e6edf3',
        bodyColor: '#8b949e',
        borderColor: '#30363d',
        borderWidth: 1,
      }
    },
    scales: {
      x: {
        ticks: { color: '#8b949e', maxRotation: 0 },
        grid: { color: '#21262d' },
        title: { display: true, text: xLabel, color: '#8b949e' }
      },
      y: {
        ticks: { color: '#8b949e' },
        grid: { color: '#21262d' },
        title: { display: true, text: yLabel, color: '#8b949e' }
      }
    }
  };
}

// ─── Heatmap ──────────────────────────────────────────────
function renderHeatmap() {
  const container = document.getElementById('heatmap');
  container.innerHTML = '';
  const freqVals = Object.values(statsData.frequency).map(Number);
  const minF = Math.min(...freqVals), maxF = Math.max(...freqVals);

  for (let n = 1; n <= 25; n++) {
    const freq = statsData.frequency[n];
    const ratio = (freq - minF) / (maxF - minF);
    const r = Math.round(68 + ratio * (255 - 68));
    const g = Math.round(138 + (1 - ratio) * (200 - 138));
    const b = Math.round(255 * (1 - ratio));
    const bg = `rgb(${r},${g},${b})`;
    const textColor = ratio > 0.5 ? '#000' : '#fff';

    const cell = document.createElement('div');
    cell.className = 'heatmap-cell';
    cell.style.background = bg;
    cell.style.color = textColor;
    cell.innerHTML = `<span class="cell-num">${n}</span><span class="cell-pct">${statsData.frequency_pct[n]}%</span>`;
    cell.title = `Dezena ${n}: ${freq} aparições (${statsData.frequency_pct[n]}%)`;
    container.appendChild(cell);
  }
}

// ─── Pairs / Trios ────────────────────────────────────────
function renderPairsList() {
  const container = document.getElementById('pairs-list');
  container.innerHTML = '';
  const maxCount = statsData.top_pairs[0]?.count || 1;
  statsData.top_pairs.forEach(p => {
    const pct = Math.round((p.count / maxCount) * 100);
    const el = document.createElement('div');
    el.className = 'pair-item';
    el.innerHTML = `
      <div class="pair-balls">${p.pair.map(n => `<div class="pair-ball">${n}</div>`).join('')}</div>
      <div style="flex:1">
        <div class="pair-bar" style="width:${pct}%"></div>
      </div>
      <span class="pair-count">${p.count}x</span>`;
    container.appendChild(el);
  });
}

function renderTriosList() {
  const container = document.getElementById('trios-list');
  container.innerHTML = '';
  const maxCount = statsData.top_trios[0]?.count || 1;
  statsData.top_trios.forEach(t => {
    const pct = Math.round((t.count / maxCount) * 100);
    const el = document.createElement('div');
    el.className = 'pair-item';
    el.innerHTML = `
      <div class="pair-balls">${t.trio.map(n => `<div class="pair-ball">${n}</div>`).join('')}</div>
      <div style="flex:1">
        <div class="pair-bar" style="width:${pct}%"></div>
      </div>
      <span class="pair-count">${t.count}x</span>`;
    container.appendChild(el);
  });
}

// ─── Predictions ──────────────────────────────────────────
async function fetchPredictions() {
  document.getElementById('predictions-list').innerHTML =
    '<div class="loading-overlay"><span class="spinner"></span> Gerando apostas...</div>';
  try {
    const res = await fetch(`${API}/api/predictions`);
    if (!res.ok) throw new Error('API error');
    predsData = await res.json();
    renderPredictions();
  } catch (e) {
    document.getElementById('predictions-list').innerHTML =
      '<div class="loading-overlay" style="color:#ff5252">Erro ao gerar apostas. Sincronize primeiro.</div>';
  }
}

function renderPredictions() {
  if (!predsData) return;
  const {apostas, scores, generated_at, concurso_ref} = predsData;
  const hotSet = new Set(statsData?.hot_numbers || []);

  document.getElementById('pred-meta').textContent =
    `Concurso ref: #${concurso_ref} · ${formatDate(generated_at)}`;

  const container = document.getElementById('predictions-list');
  container.innerHTML = '';

  apostas.forEach((combo, idx) => {
    const score = scores[idx] || 0;
    const row = document.createElement('div');
    row.className = 'prediction-row';
    const ballsHtml = combo.map(n =>
      `<div class="pred-ball ${hotSet.has(n) ? 'highlight' : ''}" title="${n}">${n}</div>`
    ).join('');
    row.innerHTML = `
      <span class="pred-num">${idx + 1}</span>
      <div class="pred-balls">${ballsHtml}</div>
      <div class="score-bar"><div class="score-fill" style="width:${Math.round(score*100)}%"></div></div>
      <span class="pred-score">${Math.round(score * 100)}%</span>
    `;
    container.appendChild(row);
  });
}

async function regeneratePredictions() {
  const btn = document.getElementById('regen-btn');
  btn.disabled = true;
  btn.textContent = '...';
  document.getElementById('predictions-list').innerHTML =
    '<div class="loading-overlay"><span class="spinner"></span> Regenerando...</div>';
  try {
    const res = await fetch(`${API}/api/predictions/generate`, {method: 'POST'});
    if (!res.ok) throw new Error('API error');
    predsData = await res.json();
    renderPredictions();
    showToast('20 apostas geradas!', 'success');
  } catch (e) {
    showToast('Erro ao regenerar apostas', 'error');
  }
  btn.disabled = false;
  btn.textContent = '↻ Regenerar';
}

// ─── History ──────────────────────────────────────────────
async function fetchHistory() {
  const container = document.getElementById('history-list');
  container.innerHTML = '<div class="loading-overlay"><span class="spinner"></span> Carregando...</div>';
  try {
    const res = await fetch(`${API}/api/predictions/history`);
    const preds = await res.json();
    if (!preds.length) {
      container.innerHTML = '<div class="loading-overlay" style="color:var(--text2)">Nenhuma previsão salva ainda.</div>';
      return;
    }
    container.innerHTML = '';
    preds.forEach(p => {
      const card = document.createElement('div');
      card.className = 'card';
      card.style.marginBottom = '16px';
      card.innerHTML = `
        <div style="display:flex;justify-content:space-between;margin-bottom:12px">
          <strong>Concurso ref: #${p.concurso_ref}</strong>
          <span style="color:var(--text2);font-size:0.8rem">${formatDate(p.generated_at)}</span>
        </div>
        ${p.apostas.slice(0, 5).map((combo, i) => `
          <div style="display:flex;gap:5px;margin-bottom:6px;flex-wrap:wrap">
            <span style="color:var(--text2);font-size:0.8rem;width:20px">${i+1}</span>
            ${combo.map(n => `<div class="pred-ball">${n}</div>`).join('')}
          </div>`).join('')}
        ${p.apostas.length > 5 ? `<div style="color:var(--text2);font-size:0.8rem;margin-top:4px">+ ${p.apostas.length-5} apostas...</div>` : ''}
      `;
      container.appendChild(card);
    });
  } catch (e) {
    container.innerHTML = '<div class="loading-overlay" style="color:#ff5252">Erro ao carregar histórico.</div>';
  }
}

// ─── Wolfram ──────────────────────────────────────────────
async function fetchWolframInsight() {
  const container = document.getElementById('wolfram-container');
  container.innerHTML = '<div class="loading-overlay"><span class="spinner"></span> Consultando Wolfram Alpha...</div>';
  try {
    const res = await fetch(`${API}/api/wolfram/insight`);
    const data = await res.json();
    if (!data.hot_insight && !data.sum_insight) {
      container.innerHTML = `
        <div class="wolfram-card">
          <h3>🔬 Wolfram Alpha</h3>
          <div class="wolfram-text">
            Configure a variável de ambiente <code>WOLFRAM_API_KEY</code> para habilitar análises matemáticas avançadas.
          </div>
        </div>`;
      return;
    }
    container.innerHTML = `
      <div class="wolfram-card">
        <h3>🔬 Wolfram Alpha — Insights Matemáticos</h3>
        <div class="wolfram-text">
          ${data.hot_insight ? `
            <div class="insight-block">
              <div class="insight-label">Propriedades dos Números Quentes</div>
              <div>${data.hot_insight}</div>
            </div>` : ''}
          ${data.sum_insight ? `
            <div class="insight-block">
              <div class="insight-label">Distribuição Normal da Soma</div>
              <div>${data.sum_insight}</div>
            </div>` : ''}
        </div>
      </div>`;
  } catch (e) {
    container.innerHTML = '<div class="loading-overlay" style="color:#ff5252">Erro ao consultar Wolfram.</div>';
  }
}

// ─── Sync ─────────────────────────────────────────────────
async function triggerSync() {
  const btn = document.getElementById('sync-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Sincronizando...';
  showToast('Sincronizando com a Caixa...', 'info');
  try {
    const res = await fetch(`${API}/api/sync`, {method: 'POST'});
    const data = await res.json();
    showToast(`✓ ${data.new_draws} novos sorteios! Total: ${data.total_draws}`, 'success');
    await fetchStats();
    predsData = null;
    fetchPredictions();
  } catch (e) {
    showToast('Erro ao sincronizar', 'error');
  }
  btn.disabled = false;
  btn.innerHTML = '⟳ Sincronizar';
}

// ─── Poll health ──────────────────────────────────────────
let lastKnownConcurso = 0;
async function pollHealth() {
  try {
    const res = await fetch(`${API}/api/health`);
    const data = await res.json();
    if (lastKnownConcurso && data.latest_concurso > lastKnownConcurso) {
      showToast(`Novo sorteio #${data.latest_concurso} disponível! Sincronize.`, 'info');
    }
    lastKnownConcurso = data.latest_concurso;
  } catch (_) {}
}

// ─── Countdown ────────────────────────────────────────────
function startCountdown() {
  updateCountdown();
  setInterval(updateCountdown, 1000);
}

function getNextDraw() {
  const now = new Date();
  const days = [1, 3, 5]; // Mon=1, Wed=3, Fri=5
  let next = new Date(now);
  for (let i = 0; i <= 7; i++) {
    const d = new Date(now);
    d.setDate(now.getDate() + i);
    d.setHours(20, 0, 0, 0);
    if (days.includes(d.getDay()) && d > now) {
      return d;
    }
  }
  return null;
}

function updateCountdown() {
  const next = getNextDraw();
  if (!next) return;
  const diff = next - new Date();
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  const s = Math.floor((diff % 60000) / 1000);
  setText('kpi-countdown', `${pad(h)}:${pad(m)}:${pad(s)}`);
  setText('kpi-next-date', next.toLocaleDateString('pt-BR', {weekday:'short', day:'2-digit', month:'short'}));
}

function pad(n) { return String(n).padStart(2, '0'); }

// ─── Export CSV ───────────────────────────────────────────
function exportCSV() {
  if (!predsData) return;
  const rows = [['Jogo', ...Array.from({length:15}, (_,i)=>`D${i+1}`), 'Score']];
  predsData.apostas.forEach((combo, i) => {
    rows.push([i + 1, ...combo, (predsData.scores[i] * 100).toFixed(1) + '%']);
  });
  const csv = rows.map(r => r.join(',')).join('\n');
  const blob = new Blob([csv], {type: 'text/csv'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `lotofacil_apostas_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
}

// ─── Helpers ──────────────────────────────────────────────
function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso.includes('T') ? iso : iso + 'T00:00:00');
    return d.toLocaleDateString('pt-BR', {day:'2-digit', month:'2-digit', year:'numeric'});
  } catch { return iso; }
}

function showToast(msg, type = 'info') {
  const container = document.getElementById('toasts');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ─── Disclaimer ───────────────────────────────────────────
function closeDisclaimer() {
  document.getElementById('disclaimer-modal').style.display = 'none';
  try { localStorage.setItem('disclaimer_accepted', '1'); } catch (_) {}
}

function maybeShowDisclaimer() {
  try {
    if (!localStorage.getItem('disclaimer_accepted')) {
      document.getElementById('disclaimer-modal').style.display = 'flex';
    }
  } catch (_) {
    document.getElementById('disclaimer-modal').style.display = 'flex';
  }
}

// ─── Start ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  maybeShowDisclaimer();
  init();
});
