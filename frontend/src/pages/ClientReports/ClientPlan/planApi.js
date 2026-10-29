// Converts the plan page state to / from the API's table rows (see backend client_reports serializers).
import { SOURCES } from './tabs/IncomeTab.jsx';
import { CATEGORIES } from './tabs/ExpensesTab.jsx';
import { INVESTMENTS } from './tabs/SavingsTab.jsx';
import { CLASSES } from './tabs/AssetsTab.jsx';
import { LIABILITIES } from './tabs/LiabilitiesTab.jsx';

const amount = (v) => Number(v) || 0;
const text = (v) => (v == null ? '' : String(v));
// API decimal ("50000.00") -> the digit string the inputs hold; zero becomes an empty box.
const digits = (v) => (Number(v) ? String(Math.round(Number(v))) : '');

export const toPayload = ({ info, income, expenses, savings, assetData, liabilityData, insurance, family }) => ({
  info: {
    client_name: info.clientName,
    spouse_name: info.spouseName,
    phone: info.phone,
    email: info.email,
    address: info.address,
    plan_date: info.planDate || null,
    advisor_notes: info.advisorNotes,
  },
  income: SOURCES.map((s) => ({ key: s.key, label: s.label, amount: amount(income[s.key]) })).filter((r) => r.amount),
  expenses: CATEGORIES.flatMap((c) => c.items.map((label, i) => ({
    key: `${c.key}-${i}`, label, category: c.key, amount: amount(expenses[`${c.key}-${i}`]),
  }))).filter((r) => r.amount),
  investments: INVESTMENTS.map((s) => ({ key: s.key, label: s.label, amount: amount(savings[s.key]) })).filter((r) => r.amount),
  assets: CLASSES.flatMap((c) => c.items.map((label, i) => {
    const key = `${c.key}-${i}`;
    return { key, label, asset_class: c.key, amount: amount(assetData[key]), purpose: text(assetData[`${key}Goal`]) };
  })).filter((r) => r.amount || r.purpose),
  liabilities: LIABILITIES.map((l) => ({
    key: l.key, label: l.label, amount: amount(liabilityData[l.key]), purpose: text(liabilityData[`${l.key}Goal`]),
  })).filter((r) => r.amount || r.purpose),
  insurance: {
    income_replacement_years: amount(insurance.years),
    existing_life_cover: amount(insurance.lifeCover),
    existing_health_cover: amount(insurance.healthCover),
    auto_sum_from_family: Boolean(insurance.auto),
  },
  family: family.map((m) => ({
    name: m.name,
    relationship: m.relation,
    date_of_birth: m.dob || null,
    age: m.age === '' ? null : Number(m.age),
    gender: m.gender,
    occupation: m.occupation,
    annual_income: amount(m.income),
    life_policy: m.lifePolicy,
    life_cover: amount(m.lifeCover),
    health_policy: m.healthPolicy,
    health_cover: amount(m.healthCover),
    is_dependent: m.dependent,
    notes: m.notes,
  })),
});

// `defaults` fills whatever has never been saved (info, insurance).
export function fromPlan(plan, defaults) {
  const amounts = (rows) => Object.fromEntries(rows.map((r) => [r.key, digits(r.amount)]));
  const withPurpose = (rows) => ({
    ...amounts(rows),
    ...Object.fromEntries(rows.filter((r) => r.purpose).map((r) => [`${r.key}Goal`, r.purpose])),
  });
  const { info, insurance } = plan;

  return {
    info: info
      ? {
          clientName: info.client_name, spouseName: info.spouse_name, phone: info.phone, email: info.email,
          address: info.address, planDate: info.plan_date || '', advisorNotes: info.advisor_notes,
        }
      : defaults.info,
    income: amounts(plan.income),
    expenses: amounts(plan.expenses),
    savings: amounts(plan.investments),
    assetData: withPurpose(plan.assets),
    liabilityData: withPurpose(plan.liabilities),
    insurance: insurance
      ? {
          years: String(insurance.income_replacement_years), lifeCover: digits(insurance.existing_life_cover),
          healthCover: digits(insurance.existing_health_cover), auto: insurance.auto_sum_from_family,
        }
      : defaults.insurance,
    family: plan.family.map((m, i) => ({
      id: `${Date.now()}-${i}`, name: m.name, relation: m.relationship, dob: m.date_of_birth || '',
      age: m.age == null ? '' : String(m.age), gender: m.gender, occupation: m.occupation, income: digits(m.annual_income),
      lifePolicy: m.life_policy, lifeCover: digits(m.life_cover), healthPolicy: m.health_policy,
      healthCover: digits(m.health_cover), dependent: m.is_dependent, notes: m.notes,
    })),
  };
}
