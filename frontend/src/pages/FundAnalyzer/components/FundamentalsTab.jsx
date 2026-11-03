import { Info } from 'lucide-react';
import { amount, nav, signedPct } from '../fundAnalysis.js';

function FundCard({ fund }) {
  return <article className="fa-card fa-fund" style={{ borderTopColor: fund.color }}>
    <header className="fa-fund__head"><div><h3>{fund.scheme_name}</h3><p>{fund.amc || 'AMFI'} · {fund.category || 'Category unavailable'}</p></div><span className="fa-fund__risk">{fund.source}</span></header>
    <dl className="fa-fund__metrics"><div><dt>NAV</dt><dd>{nav(fund.nav)}</dd></div><div><dt>1Y</dt><dd className={fund.metrics?.r1y >= 0 ? 'fa-up' : 'fa-down'}>{signedPct(fund.metrics?.r1y)}</dd></div><div><dt>TER</dt><dd>{fund.ter == null ? '—' : `${fund.ter.toFixed(2)}%`}</dd></div><div><dt>AAUM</dt><dd>{amount(fund.aum, fund.aum_unit)}</dd></div></dl>
    <div className="fa-fund__details"><p className="fa-fund__details-head"><span>LIVE DATA</span><small>As of {fund.asOfDate || '—'}</small></p><p>Scheme code: {fund.scheme_code}<br />ISIN: {fund.isin || '—'}<br />Plan: {fund.plan || '—'} · Option: {fund.option || '—'}</p></div>
    <footer className="fa-fund__foot"><span>TER and AAUM are null when AMFI does not publish a matching record.</span></footer>
  </article>;
}

export default function FundamentalsTab({ funds, loading, error }) {
  return <>{loading && <p className="fa-notice" role="status"><Info size={14} /> <span>Loading TER and AUM from AMFI…</span></p>}{error && <p className="fa-notice" role="alert"><Info size={14} /> <span>{error}</span></p>}<p className="fa-notice"><Info size={14} /> <span>Only official AMFI metadata and NAV-derived metrics are shown.</span></p><div className="fa-funds">{funds.map((fund) => <FundCard key={fund.scheme_code} fund={fund} />)}</div></>;
}
