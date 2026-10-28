import { ArrowLeft, ArrowRight, Briefcase, Building2, Gift, House, Info, TrendingUp } from 'lucide-react';

const SOURCES = [
  { key: 'salary', label: 'Salary income', hint: 'Husband + wife, net of tax', icon: Briefcase, tone: 'blue' },
  { key: 'bonus', label: 'Annual bonus', hint: 'Husband + wife, monthly equivalent', icon: Gift, tone: 'yellow' },
  { key: 'business', label: 'Business income', hint: 'Profession or business', icon: Building2, tone: 'purple' },
  { key: 'rental', label: 'Rental income', hint: 'Property rentals received', icon: House, tone: 'green' },
  { key: 'investment', label: 'Investment income', hint: 'Interest, dividends, SWP', icon: TrendingUp, tone: 'red' },
];

const inr = (n) => `₹${n.toLocaleString('en-IN')}`;
const pct = (n) => `${n.toFixed(1)}%`;

export const incomeTotal = (income) =>
  SOURCES.reduce((sum, s) => sum + (Number(income[s.key]) || 0), 0);

export default function IncomeTab({ income, onIncomeChange, onBack, onNext, nextLabel, prevLabel }) {
  const amount = (key) => Number(income[key]) || 0;
  const total = incomeTotal(income);
  const share = (key) => (total ? (amount(key) / total) * 100 : 0);

  const setAmount = (key) => (e) =>
    onIncomeChange({ ...income, [key]: e.target.value.replace(/\D/g, '').slice(0, 12) });

  return (
    <section className="plan-card plan-card--flush">
      <div className="plan-card__pad">
        <div className="income__head">
          <div>
            <h2>Income</h2>
            <p className="plan-card__sub">Monthly take-home income of the household.</p>
          </div>
          <div className="income__totals">
            <div><span>MONTHLY</span><strong>{inr(total)}</strong></div>
            <div><span>ANNUAL</span><strong>{inr(total * 12)}</strong></div>
          </div>
        </div>

        <div className="income__bar" aria-hidden="true">
          {SOURCES.map((s) => (
            <i key={s.key} className={`tone--${s.tone}`} style={{ width: `${share(s.key)}%` }} />
          ))}
        </div>
        <p className="income__bar-note">{total ? 'Share of total monthly income by source' : 'No income entered yet'}</p>
      </div>

      <div className="income__table">
        <div className="income__row income__row--head">
          <span>SOURCE</span><span>MONTHLY</span><span>ANNUAL</span><span>SHARE</span>
        </div>

        {SOURCES.map(({ key, label, hint, icon: Icon, tone }) => (
          <div key={key} className="income__row">
            <div className="income__source">
              <span className={`income__icon tone-bg--${tone}`}><Icon size={16} /></span>
              <div><strong>{label}</strong><small>{hint}</small></div>
            </div>
            <label className="income__amount">
              <em>₹</em>
              <input
                type="text"
                inputMode="numeric"
                placeholder="0"
                aria-label={`${label} per month`}
                value={income[key]}
                onChange={setAmount(key)}
              />
            </label>
            <span className="income__annual">{inr(amount(key) * 12)}</span>
            <div className="income__share">
              <i><b className={`tone--${tone}`} style={{ width: `${share(key)}%` }} /></i>
              <span>{pct(share(key))}</span>
            </div>
          </div>
        ))}

        <div className="income__row income__row--total">
          <strong>Total income</strong>
          <strong>{inr(total)}</strong>
          <span>{inr(total * 12)}</span>
          <strong>100%</strong>
        </div>
      </div>

      <p className="income__note">
        <Info size={14} /> Enter amounts net of income tax. Include both husband's and wife's income where applicable.
      </p>

      <footer className="plan-footer plan-footer--split">
        <button type="button" className="plan-next" onClick={onBack}>
          <ArrowLeft size={14} /> {prevLabel}
        </button>
        <button type="button" className="plan-next" onClick={onNext}>
          Next: {nextLabel} <ArrowRight size={14} />
        </button>
      </footer>
    </section>
  );
}
