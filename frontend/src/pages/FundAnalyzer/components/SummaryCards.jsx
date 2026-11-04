import { CircleDot, Shield, Star, TrendingUp } from 'lucide-react';
import { signedPct } from '../fundAnalysis.js';

function Card({ icon: Icon, label, value, caption, dark }) {
  return <div className={`fa-stat${dark ? ' fa-stat--dark' : ''}`}><span className="fa-stat__label"><Icon size={13} /> {label}</span><strong className="fa-stat__value">{value}</strong><span className="fa-stat__caption">{caption}</span></div>;
}

export default function SummaryCards({ funds, overlap, overlapLoading }) {
  const valid = funds.filter((fund) => fund.metrics);
  const top = (key, direction) => valid.reduce((best, fund) => {
    if (!best) return fund;
    const a = fund.metrics?.[key]; const b = best.metrics?.[key];
    if (a == null) return best;
    if (b == null) return fund;
    return direction === 'low' ? (a < b ? fund : best) : (a > b ? fund : best);
  }, null);
  const topCagr = top('r3y', 'high'); const bestSharpe = top('sharpe', 'high'); const lowestVol = top('volatility', 'low');
  const highestPair = overlap?.highest_pair;
  const leftFund = funds.find((fund) => fund.scheme_code === highestPair?.left?.scheme_code);
  const rightFund = funds.find((fund) => fund.scheme_code === highestPair?.right?.scheme_code);
  const unavailableReason = overlap?.funds?.find((fund) => fund.reason === 'Overlap not applicable for debt funds')?.reason
    || overlap?.funds?.find((fund) => fund.reason === 'Overlap not available for this AMC')?.reason
    || overlap?.funds?.find((fund) => !fund.available)?.reason;
  const portfolioMonth = overlap?.portfolio_month
    ? new Date(`${overlap.portfolio_month}-01T00:00:00`).toLocaleString('en', { month: 'short', year: 'numeric' })
    : null;
  const overlapCaption = overlapLoading
    ? 'Loading monthly holdings...'
    : highestPair && leftFund && rightFund
      ? <><i style={{ background: leftFund.color }} /><i style={{ background: rightFund.color }} />{leftFund.scheme_name} / {rightFund.scheme_name}{portfolioMonth && <small>Portfolio: {portfolioMonth}</small>}</>
      : unavailableReason || 'Overlap data unavailable';
  return <section className="fa-stats">
    <Card dark icon={TrendingUp} label="TOP 3Y CAGR" value={signedPct(topCagr?.metrics?.r3y)} caption={topCagr?.scheme_name || 'Not enough history'} />
    <Card icon={Star} label="BEST RISK-ADJUSTED" value={bestSharpe?.metrics?.sharpe == null ? '—' : <>{bestSharpe.metrics.sharpe.toFixed(2)} <small>Sharpe</small></>} caption={bestSharpe?.scheme_name || 'Not enough history'} />
    <Card icon={Shield} label="LOWEST VOLATILITY" value={lowestVol?.metrics?.volatility == null ? '—' : `${(lowestVol.metrics.volatility * 100).toFixed(2)}%`} caption={lowestVol?.scheme_name || 'Not enough history'} />
    <Card icon={CircleDot} label="HIGHEST OVERLAP" value={overlapLoading ? '...' : highestPair ? `${highestPair.overlap_pct.toFixed(1)}%` : '—'} caption={overlapCaption} />
  </section>;
}
