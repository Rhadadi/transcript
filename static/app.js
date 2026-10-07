const form = document.getElementById('form');
const fileInput = document.getElementById('file');
const progress = document.getElementById('progress');
const errorBox = document.getElementById('error');
const result = document.getElementById('result');
const segmentsEl = document.getElementById('segments');
const rawText = document.getElementById('rawText');
const player = document.getElementById('player');
const meta = document.getElementById('meta');
const health = document.getElementById('health');
const speakerNames = document.getElementById('speakerNames');
const submitBtn = document.getElementById('submit');

const backendInput = document.getElementById('backend');
const accessToken = document.getElementById('accessToken');
const isPages = location.hostname.endsWith('.github.io');
backendInput.value = localStorage.getItem('transcriberBackend') || (isPages ? '' : location.origin);
let audioUrl = null;
let playUntil = null;
player.addEventListener('timeupdate', () => {
  if (playUntil !== null && player.currentTime >= playUntil) { player.pause(); playUntil = null; }
});
function apiUrl(path) {
  if (!backendInput.value.trim()) throw new Error('Enter your backend URL and click Connect.');
  const url = new URL(backendInput.value.trim());
  if (url.username || url.password || url.search || url.hash) throw new Error('Use a plain backend URL without credentials or query parameters.');
  if (location.protocol === 'https:' && url.protocol !== 'https:') throw new Error('The backend must use HTTPS.');
  if (!['https:', 'http:'].includes(url.protocol)) throw new Error('Invalid backend URL.');
  return url.href.replace(/\/$/, '') + path;
}
document.getElementById('connect').addEventListener('click', () => {
  checkHealth();
});
let lastResult = null;
let speakerMap = {};

function formatTime(sec) {
  const s = Math.max(0, Number(sec || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = Math.floor(s % 60);
  const tenths = Math.floor((s - Math.floor(s)) * 10);
  if (h) return `${h}:${String(m).padStart(2,'0')}:${String(ss).padStart(2,'0')}.${tenths}`;
  return `${m}:${String(ss).padStart(2,'0')}.${tenths}`;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function renderSpeakerInputs(speakers) {
  speakerNames.innerHTML = '';
  speakerMap = {};
  speakers.forEach((sid, idx) => {
    speakerMap[sid] = `Speaker ${idx + 1}`;
    const wrap = document.createElement('label');
    wrap.className = 'speaker-input';
    wrap.innerHTML = `<span>${escapeHtml(sid)}</span><input data-speaker="${escapeHtml(sid)}" value="Speaker ${idx + 1}" />`;
    speakerNames.appendChild(wrap);
  });
  speakerNames.querySelectorAll('input').forEach(input => {
    input.addEventListener('input', () => {
      speakerMap[input.dataset.speaker] = input.value || input.dataset.speaker;
      renderSegments();
    });
  });
}

function renderSegments() {
  if (!lastResult) return;
  segmentsEl.innerHTML = '';
  lastResult.segments.forEach((seg, idx) => {
    const card = document.createElement('article');
    card.className = 'segment' + (seg.needs_review ? ' review' : '');
    const speaker = speakerMap[seg.speaker_id] || seg.speaker_id;
    card.innerHTML = `
      <div class="segment-top" dir="ltr">
        <button class="time" data-start="${seg.start}" data-end="${seg.end}">▶ ${formatTime(seg.start)} – ${formatTime(seg.end)}</button>
        <span class="speaker">${escapeHtml(speaker)}</span>
        ${seg.needs_review ? '<span class="flag">Review</span>' : ''}
      </div>
      <textarea class="segment-text" dir="auto" data-index="${idx}">${escapeHtml(seg.text)}</textarea>
    `;
    segmentsEl.appendChild(card);
  });

  segmentsEl.querySelectorAll('.time').forEach(btn => {
    btn.addEventListener('click', () => {
      player.currentTime = Number(btn.dataset.start || 0);
      playUntil = Number(btn.dataset.end);
      player.play().catch(err => { errorBox.textContent = err.message; errorBox.classList.remove("hidden"); });
    });
  });
  segmentsEl.querySelectorAll('.segment-text').forEach(area => {
    area.addEventListener('input', () => {
      const idx = Number(area.dataset.index);
      lastResult.segments[idx].text = area.value;
    });
  });
}

async function checkHealth() {
  try {
    health.classList.remove('good', 'bad');
    const res = await fetch(apiUrl('/api/health'), {signal: AbortSignal.timeout(15000)});
    if (!res.ok) throw new Error('Server health check failed.');
    localStorage.setItem('transcriberBackend', backendInput.value.trim());
    const data = await res.json();
    if (data.elevenlabs_configured) {
      health.textContent = 'API ready';
      health.classList.add('good');
    } else {
      health.textContent = 'API key not configured';
      health.classList.add('bad');
    }
  } catch (err) {
    health.textContent = err.message || 'Server unavailable';
    health.classList.add('bad');
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!fileInput.files[0]) return;
  errorBox.classList.add('hidden');
  result.classList.add('hidden');
  progress.classList.remove('hidden');
  submitBtn.disabled = true;

  const file = fileInput.files[0];
  if (!file) return;
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl = URL.createObjectURL(file);
  player.src = audioUrl;
  playUntil = null;

  const fd = new FormData(form);
  if (!document.getElementById('tag_audio_events').checked) {
    fd.set('tag_audio_events', 'false');
  }

  try {
    const res = await fetch(apiUrl('/api/transcribe'), { method: 'POST', body: fd, headers: {Authorization: 'Bearer ' + accessToken.value} });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
    }
    lastResult = data;
    renderSpeakerInputs(data.speakers || []);
    renderSegments();
    rawText.textContent = data.text || '';
    const prob = typeof data.language_probability === 'number'
      ? ` · language score ${(data.language_probability * 100).toFixed(1)}%`
      : '';
    meta.textContent = `${data.model} · ${data.language_code || 'unknown language'} · ${(data.segments || []).length} segments${prob}`;
    result.classList.remove('hidden');
    result.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    errorBox.textContent = err.message || String(err);
    errorBox.classList.remove('hidden');
  } finally {
    progress.classList.add('hidden');
    submitBtn.disabled = false;
  }
});

document.getElementById('copyBtn').addEventListener('click', async () => {
  if (!lastResult) return;
  const text = lastResult.segments.map(seg => {
    const name = speakerMap[seg.speaker_id] || seg.speaker_id;
    return `[${formatTime(seg.start)}–${formatTime(seg.end)}] ${name}\n${seg.text}`;
  }).join('\n\n');
  await navigator.clipboard.writeText(text);
});

document.getElementById('jsonBtn').addEventListener('click', () => {
  if (!lastResult) return;
  const payload = JSON.stringify({ ...lastResult, speaker_names: speakerMap }, null, 2);
  const blob = new Blob([payload], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'medical-transcript.json';
  a.click();
  URL.revokeObjectURL(url);
});

checkHealth();
