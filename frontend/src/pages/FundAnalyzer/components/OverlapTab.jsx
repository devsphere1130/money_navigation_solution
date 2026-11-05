import { useState } from 'react';
import { Info } from 'lucide-react';

const SCALE_MAX = 60;
const TOP_PAIRS = 5;
const STOCK_CHIPS = 4;

const shortName = (name) => name.split(' - ')[0].replace(/ Fund$/i, '');
const pairKey = (pair) => `${pair.left.scheme_code}-${pair.right.scheme_code}`;
const cellColor = (value) => `rgba(194, 144, 53, ${0.12 + 0.88 * Math.min(value / SCALE_MAX, 1)})`;
const overlapLevel = (value) => (value < 25 ? 'Low overlap' : value <= 50 ? 'Moderate overlap' : 'High overlap');
const pct = (value) => (value == null ? '—' : `${value.toFixed(2)}%`);
const count = (value) => (value == null ? '—' : value);
const classLabel = { equity: 'Equity', debt: 'Debt' };
const monthLabel = (month) => (month
  ? new Date(`${month}-01T00:00:00Z`).toLocaleString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' })
  : null);

function Matrix({ funds, pairs, selected, onSelect }) {
  const pairFor = (a, b) => pairs.find((pair) => (pair.left.scheme_code === a && pair.right.scheme_code === b) || (pair.left.scheme_code === b && pair.right.scheme_code === a));
  return <section className="fa-card fa-matrix">
    <div className="fa-section-head fa-section-head--flush"><h2>Overlap matrix</h2><p>% of portfolio weight the two funds hold in common. Click any cell for details.</p></div>
    <div className="fa-matrix__scroll">
      <div className="fa-matrix__grid" style={{ gridTemplateColumns: `130px repeat(${funds.length}, minmax(76px, 1fr))` }}>
        <span />
        {funds.map((fund) => <span key={fund.scheme_code} className="fa-matrix__col" title={fund.scheme_name}><i style={{ background: fund.color }} />{shortName(fund.scheme_name)}</span>)}
        {funds.map((rowFund) => [
          <span key={`${rowFund.scheme_code}-label`} className="fa-matrix__row" title={rowFund.scheme_name}>{shortName(rowFund.scheme_name)} <i style={{ background: rowFund.color }} /></span>,
          ...funds.map((colFund) => {
            const key = `${rowFund.scheme_code}-${colFund.scheme_code}`;
            const pair = rowFund.scheme_code === colFund.scheme_code ? null : pairFor(rowFund.scheme_code, colFund.scheme_code);
            if (!pair) return <span key={key} className="fa-matrix__self">—</span>;
            const active = selected && pairKey(selected) === pairKey(pair);
            return <button key={key} type="button" className={`fa-matrix__cell${active ? ' fa-matrix__cell--active' : ''}`} style={{ background: cellColor(pair.overlap_pct) }} aria-pressed={active} onClick={() => onSelect(pairKey(pair))}>{pair.overlap_pct.toFixed(0)}%</button>;
          }),
        ])}
      </div>
    </div>
    <div className="fa-matrix__legend">0% <i /> {SCALE_MAX}%+</div>
  </section>;
}

function PairDetail({ pair, colorOf }) {
  const stocks = pair.common_holdings;
  const withUnits = pair.including_fund_units;
  const largest = Math.max(1, ...stocks.flatMap((stock) => [stock.left_weight, stock.right_weight]));
  const bar = (weight, code) => <span>
    <i style={{ width: `${Math.max(3, (weight / largest) * 46)}px`, background: colorOf(code) }} />{weight.toFixed(2)}%
  </span>;
  return <section className="fa-card fa-pair">
    <div className="fa-pair__head">
      <div>
        <p><i style={{ background: colorOf(pair.left.scheme_code) }} />{pair.left.scheme_name}</p>
        <p><i style={{ background: colorOf(pair.right.scheme_code) }} />{pair.right.scheme_name}</p>
        <span className="fa-pair__level">{overlapLevel(pair.overlap_pct)}</span>
      </div>
      <div className="fa-pair__total"><strong>{pair.overlap_pct.toFixed(2)}%</strong><span>OVERLAP</span><small>{monthLabel(pair.portfolio_month)}</small></div>
    </div>
    <dl className="fa-pair__split">
      <div><dt>EQUITY</dt><dd>{pct(pair.equity_overlap_pct)}</dd><small>{count(pair.common_equity_count)} common</small></div>
      <div><dt>DEBT</dt><dd>{pct(pair.debt_overlap_pct)}</dd><small>{count(pair.common_debt_count)} common</small></div>
      <div><dt>COMBINED</dt><dd>{pct(pair.overlap_pct)}</dd><small>{pair.common_count} common</small></div>
    </dl>
    {withUnits && <p className="fa-pair__units">Including fund units: <strong>{withUnits.overlap_pct.toFixed(2)}%</strong>. Adds {withUnits.fund_units.map((unit) => `${unit.name} (${unit.left_weight.toFixed(2)}% and ${unit.right_weight.toFixed(2)}%)`).join(', ')}. The overlap above covers direct debt securities only.</p>}
    {stocks.length === 0
      ? <p className="fa-pair__none">{pair.message || 'No common securities'}</p>
      : <>
        <div className="fa-pair__columns"><span>COMMON HOLDINGS ({stocks.length})</span><span>WEIGHT IN EACH</span></div>
        <div className="fa-pair__list">
          {stocks.map((stock) => <div key={stock.isin} className="fa-pair__row">
            <span title={stock.isin}>{stock.name}<small className="fa-pair__meta">{classLabel[stock.security_class]} · adds {stock.overlap_weight.toFixed(2)}%</small></span>
            <div className="fa-pair__bars">{bar(stock.left_weight, pair.left.scheme_code)}{bar(stock.right_weight, pair.right.scheme_code)}</div>
          </div>)}
        </div>
      </>}
  </section>;
}

function TopPairs({ pairs, selected, onSelect, colorOf }) {
  return <section className="fa-card fa-pairs">
    <div className="fa-section-head fa-section-head--flush"><h2>Highest overlapping pairs</h2><p>Funds that share the most portfolio weight, with the securities they hold in common.</p></div>
    {pairs.slice(0, TOP_PAIRS).map((pair, index) => {
      const hidden = pair.common_holdings.length - STOCK_CHIPS;
      return <button key={pairKey(pair)} type="button" className={`fa-pairs__row${selected && pairKey(selected) === pairKey(pair) ? ' fa-pairs__row--active' : ''}`} onClick={() => onSelect(pairKey(pair))}>
        <span className="fa-pairs__rank">{index + 1}</span>
        <span className="fa-pairs__body">
          <span className="fa-pairs__names"><i style={{ background: colorOf(pair.left.scheme_code) }} />{pair.left.scheme_name}<em>×</em><i style={{ background: colorOf(pair.right.scheme_code) }} />{pair.right.scheme_name}</span>
          <span className="fa-pairs__stocks">
            {pair.common_holdings.slice(0, STOCK_CHIPS).map((stock) => <small key={stock.isin}>{stock.name}</small>)}
            {hidden > 0 && <small>+{hidden} more</small>}
          </span>
        </span>
        <span className="fa-pairs__badge">{pair.overlap_pct.toFixed(2)}% overlap</span>
      </button>;
    })}
  </section>;
}

export default function OverlapTab({ funds, overlap, overlapLoading }) {
  const [activeKey, setActiveKey] = useState(null);
  if (funds.length < 2) return <p className="fa-card fa__empty">Add at least two funds to compare their holdings.</p>;
  if (overlapLoading) return <p className="fa-card fa__empty">Loading monthly holdings...</p>;

  const pairs = [...(overlap?.pairs || [])].sort((a, b) => b.overlap_pct - a.overlap_pct);
  if (!pairs.length) return <p className="fa-card fa__empty">{overlap?.highest_overlap?.message || 'Portfolio holdings unavailable'}</p>;

  const selected = pairs.find((pair) => pairKey(pair) === activeKey) || pairs[0];
  const colorOf = (code) => funds.find((fund) => fund.scheme_code === code)?.color;
  const skipped = (overlap.funds || []).filter((fund) => !fund.available);
  const month = monthLabel(overlap.portfolio_month);
  const unclassified = (overlap.funds || []).filter((fund) => fund.unclassified_pct);
  const notEquityOnly = (overlap.funds || []).some((fund) => fund.asset_class && fund.asset_class !== 'equity');

  return <>
    <p className="fa-notice">
      <Info size={15} />
      <span>
        <strong>Official AMC holdings.</strong> Overlap uses each fund's disclosed {notEquityOnly ? 'securities' : 'equity portfolio'}, matched by ISIN{month ? `, as of ${month}` : ''}.
        {overlap.pairs_different_months && ' Pairs use different reporting months, so compare them with care.'}
        {overlap.unavailable_pairs?.length > 0 && ` ${overlap.unavailable_pairs.length} pair(s) could not be compared because the holdings could not be fully read.`}
        {unclassified.length > 0 && ` Incomplete coverage: ${unclassified.map((fund) => `${fund.scheme_name} has ${fund.unclassified_pct.toFixed(2)}% of NAV we could not classify`).join('; ')}.`}
        {skipped.length > 0 && ` Not compared: ${skipped.map((fund) => `${fund.scheme_name || fund.scheme_code} (${fund.reason})`).join('; ')}.`}
      </span>
    </p>
    <div className="fa-overlap">
      <Matrix funds={funds} pairs={pairs} selected={selected} onSelect={setActiveKey} />
      <PairDetail pair={selected} colorOf={colorOf} />
    </div>
    <TopPairs pairs={pairs} selected={selected} onSelect={setActiveKey} colorOf={colorOf} />
  </>;
}
