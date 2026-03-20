let apiKey = sessionStorage.getItem('aethelgard_api_key') || '';

function setApiKey(nextKey) {
  apiKey = (nextKey || '').trim();
  if (apiKey) {
    sessionStorage.setItem('aethelgard_api_key', apiKey);
  } else {
    sessionStorage.removeItem('aethelgard_api_key');
  }
}

function buildApiHeaders(base = {}) {
  const headers = { ...base };
  if (apiKey) headers['X-API-Key'] = apiKey;
  return headers;
}

function logRequestId(response) {
  const requestId = response.headers.get('X-Request-ID');
  if (requestId) {
    console.log('request_id:', requestId);
  }
}

export function getApiKey() {
  return apiKey;
}

export async function ensureApiKey(message) {
  if (apiKey) return true;
  const entered = window.prompt(message || 'Enter X-API-Key:');
  if (!entered) return false;
  setApiKey(entered);
  return Boolean(apiKey);
}

export async function apiGet(path) {
  let response = await fetch(path, { headers: buildApiHeaders({ Accept: 'application/json' }) });
  logRequestId(response);

  if (response.status === 401) {
    const hasKey = await ensureApiKey('Enter X-API-Key to access pipeline telemetry:');
    if (hasKey) {
      response = await fetch(path, { headers: buildApiHeaders({ Accept: 'application/json' }) });
      logRequestId(response);
    }
  }

  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

export async function apiPost(path) {
  let response = await fetch(path, { method: 'POST', headers: buildApiHeaders() });
  logRequestId(response);

  if (response.status === 401) {
    const hasKey = await ensureApiKey('Enter X-API-Key to trigger pipeline:');
    if (hasKey) {
      response = await fetch(path, { method: 'POST', headers: buildApiHeaders() });
      logRequestId(response);
    }
  }

  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = { detail: text };
  }

  if (!response.ok) {
    if (response.status === 401) {
      setApiKey('');
    }
    throw new Error(payload.detail || `${response.status} ${response.statusText}`);
  }

  return payload;
}
