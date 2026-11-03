import { useEffect, useState } from 'react';
import { CircleDot, List, PieChart, Printer } from 'lucide-react';
import FundPicker from './components/FundPicker.jsx';
import SummaryCards from './components/SummaryCards.jsx';
import CompareTab from './components/CompareTab.jsx';
import CorrelationTab from './components/CorrelationTab.jsx';
import FundamentalsTab from './components/FundamentalsTab.jsx';
import { FUND_COLORS } from './fundData.js';
import { compareFunds } from '../../services/fundAnalyzerService.js';
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

  const load = async () => {
    setLoading(true); setError('');
    try {
      const payload = await compareFunds(selectedFunds.map((fund) => fund.scheme_code));
      setFunds((payload.funds || []).map((fund, index) => ({ ...fund, color: FUND_COLORS[index] })));
      setCorrelation(payload.correlation || {}); setSource(payload.source || 'AMFI'); setAsOfDate(payload.asOfDate || null); setRiskFreeRate(payload.summary?.riskFreeRate ?? 0.065);
    } catch (err) { setError(err.message || 'Unable to load live fund data.'); }
    finally { setLoading(false); }
  };

  useEffect(() => { const handleKey = (event) => { if (event.key === '/' && !['INPUT', 'TEXTAREA'].includes(event.target.tagName)) { event.preventDefault(); document.querySelector('.fa-search__box input')?.focus(); } }; window.addEventListener('keydown', handleKey); return () => window.removeEventListener('keydown', handleKey); }, []);

  const { Component } = TABS.find((tab) => tab.key === activeTab);
  return <div className="fa">
    <header className="fa__header"><div><p className="fa__eyebrow"><i /> LIVE {source}</p><h1>Fund Analyzer</h1><p className="fa__sub">Compare live AMFI NAV history, returns, risk, correlation and published fund metadata for up to 8 schemes.</p></div><div className="fa__actions"><button type="button" className="fa__action" onClick={() => window.print()}><Printer size={15} /> Print report</button></div></header>
    <FundPicker selectedFunds={selectedFunds} onChange={setSelectedFunds} onClear={() => { setSelectedFunds([]); setFunds([]); }} onUpdate={load} loading={loading} />
    {error && <p className="fa-notice" role="alert">{error}</p>}
    {!funds.length && !loading ? <p className="fa-card fa__empty">Select AMFI schemes and press Update analysis to load live figures.</p> : <>{funds.length > 0 && <><SummaryCards funds={funds} /><div className="fa__tabbar"><nav className="fa__tabs" role="tablist">{TABS.map(({ key, label, icon: Icon }) => <button key={key} type="button" role="tab" aria-selected={activeTab === key} className={`fa__tab${activeTab === key ? ' fa__tab--active' : ''}`} onClick={() => setActiveTab(key)}><Icon size={15} /> {label}</button>)}</nav><span className="fa__navdate">{source} as of {asOfDate || '—'}</span></div><Component funds={funds} correlation={correlation} riskFreeRate={riskFreeRate} /></>}</>}
    <p className="fa__disclaimer">Mutual fund investments are subject to market risks; read all scheme-related documents carefully. Past performance may or may not be sustained in future.</p>
  </div>;
}
