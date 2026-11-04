import { useEffect, useRef, useState } from 'react';
import { CircleDot, List, PieChart, Printer } from 'lucide-react';
import FundPicker from './components/FundPicker.jsx';
import SummaryCards from './components/SummaryCards.jsx';
import CompareTab from './components/CompareTab.jsx';
import CorrelationTab from './components/CorrelationTab.jsx';
import FundamentalsTab from './components/FundamentalsTab.jsx';
import { FUND_COLORS } from './fundData.js';
import { compareFunds, getFundamentals, getHoldingsOverlap } from '../../services/fundAnalyzerService.js';
import './FundAnalyzerPage.css';

const TABS = [
  { key: 'compare', label: 'Compare', icon: List, Component: CompareTab },
  { key: 'correlation', label: 'Correlation', icon: CircleDot, Component: CorrelationTab },
  { key: 'fundamentals', label: 'Fundamentals', icon: PieChart, Component: FundamentalsTab },
];

export default function FundAnalyzerPage() {
  const [selectedFunds, setSelectedFunds] = useState([]);
  const [funds, setFunds] = useState([]);
  const [correlation, setCorrelation] = useState({});
  const [activeTab, setActiveTab] = useState('compare');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [source, setSource] = useState('AMFI');
  const [asOfDate, setAsOfDate] = useState(null);
  const [riskFreeRate, setRiskFreeRate] = useState(0.065);
  const [fundMetadata, setFundMetadata] = useState({});
  const [fundamentalsLoading, setFundamentalsLoading] = useState(false);
  const [fundamentalsError, setFundamentalsError] = useState('');
  const [overlap, setOverlap] = useState(null);
  const [overlapLoading, setOverlapLoading] = useState(false);
  const overlapRequest = useRef(0);

  const load = async () => {
    setLoading(true); setError('');
    const schemeCodes = selectedFunds.map((fund) => fund.scheme_code);
    const requestId = ++overlapRequest.current;
    setOverlap(null);
    setOverlapLoading(true);
    getHoldingsOverlap(schemeCodes)
      .then((payload) => { if (overlapRequest.current === requestId) setOverlap(payload); })
      .catch(() => { if (overlapRequest.current === requestId) setOverlap({ available: false, funds: [], highest_pair: null }); })
      .finally(() => { if (overlapRequest.current === requestId) setOverlapLoading(false); });
    try {
      const payload = await compareFunds(schemeCodes);
      setFunds((payload.funds || []).map((fund, index) => ({ ...fund, color: FUND_COLORS[index] })));
      setCorrelation(payload.correlation || {}); setSource(payload.source || 'AMFI'); setAsOfDate(payload.asOfDate || null); setRiskFreeRate(payload.summary?.riskFreeRate ?? 0.065);
    } catch (err) { setError(err.message || 'Unable to load live fund data.'); }
    finally { setLoading(false); }
  };

  useEffect(() => {
    if (activeTab !== 'fundamentals') { setFundamentalsLoading(false); return undefined; }
    if (!funds.length) return undefined;
    const missing = funds.filter((fund) => !fundMetadata[fund.scheme_code]);
    if (!missing.length) return undefined;
    let cancelled = false;
    setFundamentalsLoading(true);
    setFundamentalsError('');
    getFundamentals(missing.map((fund) => fund.scheme_code))
      .then((payload) => {
        if (cancelled) return;
        setFundMetadata((current) => ({
          ...current,
          ...Object.fromEntries((payload.funds || []).map((fund) => [fund.scheme_code, fund])),
        }));
      })
      .catch((err) => { if (!cancelled) setFundamentalsError(err.message || 'Unable to load fund metadata.'); })
      .finally(() => { if (!cancelled) setFundamentalsLoading(false); });
    return () => { cancelled = true; };
  }, [activeTab, funds, fundMetadata]);

  useEffect(() => { const handleKey = (event) => { if (event.key === '/' && !['INPUT', 'TEXTAREA'].includes(event.target.tagName)) { event.preventDefault(); document.querySelector('.fa-search__box input')?.focus(); } }; window.addEventListener('keydown', handleKey); return () => window.removeEventListener('keydown', handleKey); }, []);

  const { Component } = TABS.find((tab) => tab.key === activeTab);
  const displayedFunds = activeTab === 'fundamentals'
    ? funds.map((fund) => {
      const metadata = fundMetadata[fund.scheme_code] || {};
      return { ...fund, ...metadata, metrics: fund.metrics ?? metadata.metrics };
    })
    : funds;
  return <div className="fa">
    <header className="fa__header"><div><p className="fa__eyebrow"><i /> LIVE {source}</p><h1>Fund Analyzer</h1><p className="fa__sub">Compare live AMFI NAV history, returns, risk, correlation and published fund metadata for up to 8 schemes.</p></div><div className="fa__actions"><button type="button" className="fa__action" onClick={() => window.print()}><Printer size={15} /> Print report</button></div></header>
    <FundPicker selectedFunds={selectedFunds} onChange={setSelectedFunds} onClear={() => { overlapRequest.current += 1; setSelectedFunds([]); setFunds([]); setFundMetadata({}); setOverlap(null); setOverlapLoading(false); }} onUpdate={load} loading={loading} />
    {error && <p className="fa-notice" role="alert">{error}</p>}
    {!funds.length && !loading ? <p className="fa-card fa__empty">Select AMFI schemes and press Update analysis to load live figures.</p> : <>{funds.length > 0 && <><SummaryCards funds={funds} overlap={overlap} overlapLoading={overlapLoading} /><div className="fa__tabbar"><nav className="fa__tabs" role="tablist">{TABS.map(({ key, label, icon: Icon }) => <button key={key} type="button" role="tab" aria-selected={activeTab === key} className={`fa__tab${activeTab === key ? ' fa__tab--active' : ''}`} onClick={() => setActiveTab(key)}><Icon size={15} /> {label}</button>)}</nav><span className="fa__navdate">{source} as of {asOfDate || '—'}</span></div><Component funds={displayedFunds} correlation={correlation} riskFreeRate={riskFreeRate} loading={fundamentalsLoading} error={fundamentalsError} /></>}</>}
    <p className="fa__disclaimer">Mutual fund investments are subject to market risks; read all scheme-related documents carefully. Past performance may or may not be sustained in future.</p>
  </div>;
}
