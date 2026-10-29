import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { listClients } from '../../../services/clientService.js';
import { TABS } from './tabs.js';
import { inr, pct } from './format.js';
import { incomeTotal } from './tabs/IncomeTab.jsx';
import { expensesTotal } from './tabs/ExpensesTab.jsx';
import { familyCover } from './tabs/FamilyTab.jsx';
import { liabilitiesTotal } from './tabs/LiabilitiesTab.jsx';
import { assetsTotal, investibleAssetsTotal, personalAssetsTotal } from './tabs/AssetsTab.jsx';
import './ClientPlan.css';

const today = () => new Date().toISOString().slice(0, 10);
const titleCase = (v) => v.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
const initials = (name) => name.split(' ').slice(0, 2).map((w) => w[0]).join('').toUpperCase();

const ratio = (n, of) => (of > 0 ? Math.max(0, (n / of) * 100) : 0);

export default function ClientPlanPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [client, setClient] = useState(null);
  const [error, setError] = useState('');
  const [active, setActive] = useState(0);
  const [info, setInfo] = useState(null);
  const [income, setIncome] = useState({ salary: '', bonus: '', business: '', rental: '', investment: '' });
  const [expenses, setExpenses] = useState({});
  const [savings, setSavings] = useState({});
  const [liabilityData, setLiabilityData] = useState({});
  const [assetData, setAssetData] = useState({});
  const [goals, setGoals] = useState([]);
  const [family, setFamily] = useState([]);
  const [retirement, setRetirement] = useState({
    expense: '', corpus: '', age: '35', retireAge: '60', life: '85', inflation: '6', before: '12', after: '8',
  });
  const [insurance, setInsurance] = useState({ years: '40', lifeCover: '', healthCover: '', auto: false });

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
  const incomeAmount = incomeTotal(income);
  const expensesAmount = expensesTotal(expenses);
  const savingsAmount = incomeAmount - expensesAmount;
  const assets = assetsTotal(assetData);
  const personalAssets = personalAssetsTotal(assetData);
  const liabilities = liabilitiesTotal(liabilityData);
  const netWorth = assets - liabilities;

  const cards = [
    {
      label: 'INCOME / MO', color: '#2b3f86', value: incomeAmount,
      note: `₹${((incomeAmount * 12) / 100000).toFixed(1)} L per year`,
    },
    {
      label: 'EXPENSES / MO', color: '#b7791f', value: expensesAmount,
      bar: ratio(expensesAmount, incomeAmount), barClass: 'tone--yellow',
      note: <><b className="plan__pct plan__pct--amber">{pct(ratio(expensesAmount, incomeAmount))}</b> of income</>,
    },
    {
      label: 'SAVINGS / MO', color: '#2f9e6b', value: savingsAmount,
      bar: ratio(savingsAmount, incomeAmount), barClass: 'tone--green',
      note: <><b className="plan__pct plan__pct--green">{pct(ratio(savingsAmount, incomeAmount))}</b> savings rate</>,
    },
    { label: 'TOTAL ASSETS', color: '#c29035', value: assets, note: `Liabilities ${inr(liabilities)}` },
    {
      label: 'NET WORTH', color: '#997023', value: netWorth, dark: true,
      note: `≈ ₹${(netWorth / 10000000).toFixed(2)} Cr · ${pct(ratio(netWorth, assets))} of assets`,
    },
  ];

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
        {cards.map((c) => (
          <div key={c.label} className={`plan__stat${c.dark ? ' plan__stat--dark' : ''}`}>
            <span className="plan__stat-label"><i style={{ background: c.color }} />{c.label}</span>
            <strong>{inr(c.value)}</strong>
            {c.bar !== undefined && (
              <div className="plan__stat-bar"><b className={c.barClass} style={{ width: `${Math.min(c.bar, 100)}%` }} /></div>
            )}
            <small>{c.note}</small>
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
          expenses={expenses}
          onExpensesChange={setExpenses}
          displayName={name}
          retirement={retirement}
          onRetirementChange={setRetirement}
          goals={goals}
          onGoalsChange={setGoals}
          surplusAmount={savingsAmount}
          insurance={insurance}
          onInsuranceChange={setInsurance}
          liabilitiesAmount={liabilities}
          investibleAmount={investibleAssetsTotal(assetData)}
          members={1 + family.length}
          family={family}
          onFamilyChange={setFamily}
          familyLife={familyCover(family, 'lifeCover')}
          familyHealth={familyCover(family, 'healthCover')}
          assetData={assetData}
          onAssetsChange={setAssetData}
          liabilities={liabilityData}
          onLiabilitiesChange={setLiabilityData}
          assetsTotal={assets}
          personalAssets={personalAssets}
          savings={savings}
          onSavingsChange={setSavings}
          incomeTotal={incomeAmount}
          expensesAmount={expensesAmount}
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
