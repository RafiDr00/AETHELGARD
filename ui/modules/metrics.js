export function createSparkHistory() {
  return { m1: [], m2: [], m3: [], m4: [], m5: [] };
}

export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export function updateMetric(id, barId, value, max, decimals = 1) {
  const el = document.getElementById(id);
  const bar = document.getElementById(barId);
  if (el) el.textContent = Number(value).toFixed(decimals);
  if (bar) bar.style.width = `${clamp((value / max) * 100, 0, 100)}%`;
}

export function pushHistory(history, key, value) {
  const arr = history[key] || [];
  arr.push(Number(value));
  while (arr.length > 24) arr.shift();
  history[key] = arr;
}

function makeSpark(values, color) {
  if (!values || values.length === 0) return '';
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values
    .map((v, i) => `${(i / (values.length - 1)) * 110},${14 - ((v - min) / range) * 10 - 2}`)
    .join(' ');
  return `<polygon points="0,14 ${points} 110,14" fill="${color}" opacity="0.1"/><polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>`;
}

export function renderSparks(history) {
  const seriesDefs = [
    ['s1', '#4cff9a', history.m1],
    ['s2', '#4cff9a', history.m2],
    ['s3', '#6cffb0', history.m3],
    ['s4', '#ffc857', history.m4],
    ['s5', '#ffc857', history.m5],
  ];
  seriesDefs.forEach(([id, color, series]) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = makeSpark(series, color);
  });
}
