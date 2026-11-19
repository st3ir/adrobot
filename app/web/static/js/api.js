/**
 * Typed-ish client for the Adrobot JSON API.
 *
 * Carries the double-submit CSRF token on every state-changing request and
 * normalises server errors into `ApiError`.
 */

const CSRF_HEADER = "X-CSRF-Token";
const SAFE_METHODS = new Set(["GET", "HEAD"]);

let csrfToken = null;

export function setCsrfToken(token) {
  csrfToken = token || null;
}

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }

  get isUnauthorized() {
    return this.status === 401;
  }
}

async function request(method, path, body) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE_METHODS.has(method) && csrfToken) headers[CSRF_HEADER] = csrfToken;

  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    throw new ApiError(0, "network_error", "Сервер недоступен. Проверьте подключение.");
  }

  if (response.status === 204) return null;

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const code = payload?.code ?? `http_${response.status}`;
    const message = payload?.message ?? "Запрос не выполнен.";
    throw new ApiError(response.status, code, message);
  }
  return payload;
}

const query = (params) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
};

export const api = {
  // auth
  login: (email, password) => request("POST", "/api/v1/auth/login", { email, password }),
  logout: () => request("POST", "/api/v1/auth/logout"),
  session: () => request("GET", "/api/v1/auth/session"),

  // catalog
  offers: (q, limit = 20) => request("GET", `/api/v1/offers${query({ q, limit })}`),
  countries: () => request("GET", "/api/v1/countries"),
  groups: () => request("GET", "/api/v1/groups"),
  domains: () => request("GET", "/api/v1/domains"),
  sources: () => request("GET", "/api/v1/sources"),
  campaignDefaults: () => request("GET", "/api/v1/campaign-defaults"),

  // campaigns
  createCampaign: (payload) => request("POST", "/api/v1/campaigns", payload),
  listCampaigns: (q, limit = 50) => request("GET", `/api/v1/campaigns${query({ q, limit })}`),
  // editor draft
  draft: (id, days) => request("GET", `/api/v1/campaigns/${id}/draft${query({ days })}`),
  fetchCampaign: (id, days) =>
    request("POST", `/api/v1/campaigns/${id}/fetch${query({ days })}`),
  addOffer: (id, offerId, days) =>
    request("POST", `/api/v1/campaigns/${id}/offers${query({ days })}`, { offer_id: offerId }),
  removeOffer: (id, offerId, days) =>
    request("DELETE", `/api/v1/campaigns/${id}/offers/${offerId}${query({ days })}`),
  restoreOffer: (id, offerId, days) =>
    request("POST", `/api/v1/campaigns/${id}/offers/${offerId}/restore${query({ days })}`),
  pinOffer: (id, offerId, pinned, share, days) =>
    request("PUT", `/api/v1/campaigns/${id}/offers/${offerId}/pin${query({ days })}`, {
      pinned,
      share,
    }),
  publishDraft: (id, days) => request("POST", `/api/v1/campaigns/${id}/publish${query({ days })}`),
  discardDraft: (id, days) => request("POST", `/api/v1/campaigns/${id}/discard${query({ days })}`),
};
