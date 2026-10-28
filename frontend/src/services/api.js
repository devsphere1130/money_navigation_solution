const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

export async function apiRequest(path, { method = 'GET', body, token } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error('Unable to reach the server. Please try again.');
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const fieldError = Object.values(data).flat().find((v) => typeof v === 'string');
    throw new Error(data.detail || data.message || fieldError || 'Something went wrong.');
  }
  return data;
}
