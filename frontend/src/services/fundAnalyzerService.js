import axiosClient from './axiosClient.js';

export async function searchFunds(query) {
  const { data } = await axiosClient.get('/search', { params: { q: query } });
  return data;
}

export async function compareFunds(schemeCodes) {
  const { data } = await axiosClient.post('/compare', { scheme_codes: schemeCodes });
  return data;
}

export async function getFund(schemeCode) {
  const { data } = await axiosClient.get(`/funds/${encodeURIComponent(schemeCode)}`);
  return data;
}
