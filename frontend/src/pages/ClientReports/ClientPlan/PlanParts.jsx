import { ArrowLeft, ArrowRight, ChevronDown, ChevronRight } from 'lucide-react';
import { inr, pct } from './format.js';

// Small pieces shared by every table-style tab (Income, Expenses, Savings, ...).

// ₹ amount box. `value` is the raw digit string kept in the page state.
export function AmountInput({ label, value, onChange }) {
  return (
    <label className="plan-amount">
      <em>₹</em>
      <input
        type="text"
        inputMode="numeric"
        placeholder="0"
        aria-label={`${label} per month`}
        value={value || ''}
        onChange={(e) => onChange(e.target.value.replace(/\D/g, '').slice(0, 12))}
      />
    </label>
  );
}

// Small progress bar + percentage. `percent` is 0-100.
export function ShareCell({ percent, tone, strong = false }) {
  const Label = strong ? 'strong' : 'span';
  return (
    <div className="plan-share">
      <i><b className={`tone--${tone}`} style={{ width: `${Math.min(percent, 100)}%` }} /></i>
      <Label>{pct(percent)}</Label>
    </div>
  );
}

// "← Previous" / "Next: X →" buttons at the bottom of a tab.
export function TabFooter({ onBack, onNext, prevLabel, nextLabel }) {
  return (
    <footer className="plan-footer plan-footer--split">
      <button type="button" className="plan-next" onClick={onBack}>
        <ArrowLeft size={14} /> {prevLabel}
      </button>
      <button type="button" className="plan-next" onClick={onNext}>
        Next: {nextLabel} <ArrowRight size={14} />
      </button>
    </footer>
  );
}

// Expandable group header row (Expenses categories, Asset classes, ...).
// `extra` fills the third column (annual value, or an empty cell).
export function CategoryRow({
  icon: Icon, label, tone, isOpen, onToggle, filled, count, total, extra, percent, className = '',
}) {
  return (
    <button type="button" className={`plan-row exp__cat ${className}`} aria-expanded={isOpen} onClick={onToggle}>
      <span className="plan-source">
        <span className="exp__chevron">{isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</span>
        <span className={`plan-icon tone-bg--${tone}`}><Icon size={16} /></span>
        <span><strong>{label}</strong><small>{filled} of {count} items filled</small></span>
      </span>
      <strong className="exp__num">{inr(total)}</strong>
      {extra}
      <ShareCell percent={percent} tone={tone} strong />
    </button>
  );
}
