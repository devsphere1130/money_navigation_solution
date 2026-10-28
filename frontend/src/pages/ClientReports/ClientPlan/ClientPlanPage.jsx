import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { listClients } from '../../../services/clientService.js';
import { TABS } from './tabs.js';
import { incomeTotal } from './tabs/IncomeTab.jsx';
import './ClientPlan.css';

const today = () => new Date().toISOString().slice(0, 10);
const titleCase = (v) => v.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
const initials = (name) => name.split(' ').slice(0, 2).map((w) => w[0]).join('').toUpperCase();

const SUMMARY = ['INCOME / MO', 'EXPENSES / MO', 'SAVINGS / MO', 'TOTAL ASSETS', 'NET WORTH'];

export default function ClientPlanPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [client, setClient] = useState(null);
  const [error, setError] = useState('');
  const [active, setActive] = useState(0);
  const [info, setInfo] = useState(null);
  const [income, setIncome] = useState({ salary: '', bonus: '', business: '', rental: '', investment: '' });

  useEffect(() => {
    listClients()
      .then((rows) => {
        const c = rows.find((r) => String(r.id) === id);
        if (!c) throw new Error('Client plan not found.');
        setClient(c);
        setInfo({
          clientName: `${c.title.toUpperCase()} ${c.full_name.toUpperCase()}`,
          spouseName: '',
          phone: c.mobile || '',
          email: c.email || '',
          address: '',
          planDate: today(),
          advisorNotes: '',
        });
      })
      .catch((err) => setError(err.message));
  }, [id]);

  if (error) return <p className="plan-state plan-state--error" role="alert">{error}</p>;
  if (!client) return <p className="plan-state">Loading client plan…</p>;

  const tab = TABS[active];
  const prev = TABS[active - 1];
  const next = TABS[active + 1];
  const name = `${client.title}. ${titleCase(client.full_name)}`;
  const summaryValues = { 'INCOME / MO': incomeTotal(income) };

  return (
    <div className="plan">
      <header className="plan__header">
        <button type="button" className="plan__back" onClick={() => navigate('/client-reports')} aria-label="Back to client reports">
          <ArrowLeft size={16} />
        </button>
        <span className="plan__avatar">{initials(client.full_name)}</span>
        <div>
          <p className="plan__crumb">Client Reports / {client.plan_name}</p>
          <h1>{name}</h1>
        </div>
      </header>

      <section className="plan__summary">
        {SUMMARY.map((label) => (
          <div key={label} className={`plan__stat${label === 'NET WORTH' ? ' plan__stat--dark' : ''}`}>
            <span>{label}</span>
            <strong>₹{(summaryValues[label] || 0).toLocaleString('en-IN')}</strong>
          </div>
        ))}
      </section>

      <nav className="plan__tabs" aria-label="Plan sections">
        {TABS.map((t, i) => (
          <button
            key={t.key}
            type="button"
            className={`plan__tab${i === active ? ' plan__tab--active' : ''}`}
            onClick={() => setActive(i)}
          >
            <span>{i + 1}</span>{t.label}
          </button>
        ))}
      </nav>

      {tab.Component ? (
        <tab.Component
          info={info}
          onChange={setInfo}
          income={income}
          onIncomeChange={setIncome}
          onBack={() => prev && setActive(active - 1)}
          onNext={() => next && setActive(active + 1)}
          prevLabel={prev?.label}
          nextLabel={next?.label}
        />
      ) : (
        <section className="plan-card"><h2>{tab.label}</h2><p className="plan-card__sub">Coming soon.</p></section>
      )}
    </div>
  );
}
