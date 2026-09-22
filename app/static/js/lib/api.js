/**
 * Thin fetch wrapper. Every call resolves to { ok, status, data } and never
 * throws on HTTP errors or non-JSON bodies, so callers can branch on `ok`
 * and read `data.error` without try/catch around each request.
 */

async function request(method, url, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    return { ok: false, status: 0, data: { error: 'Network error — check your connection and try again.' } };
  }
  let data = {};
  try {
    data = await response.json();
  } catch {
    if (!response.ok) data = { error: `Request failed (${response.status})` };
  }
  return { ok: response.ok, status: response.status, data };
}

export const api = {
  get: url => request('GET', url),
  post: (url, body) => request('POST', url, body),
  put: (url, body) => request('PUT', url, body),
  delete: url => request('DELETE', url),
};
