// The 11 steps of a client plan, in order. Add each tab's component here as it is built.
import ClientInfoTab from './tabs/ClientInfoTab.jsx';
import IncomeTab from './tabs/IncomeTab.jsx';

export const TABS = [
  { key: 'client-info', label: 'Client Info', Component: ClientInfoTab },
  { key: 'income', label: 'Income', Component: IncomeTab },
  { key: 'expenses', label: 'Expenses' },
  { key: 'savings', label: 'Savings & Investments' },
  { key: 'assets', label: 'Assets' },
  { key: 'liabilities', label: 'Liabilities & Net Worth' },
  { key: 'insurance', label: 'Insurance' },
  { key: 'goals', label: 'Goals' },
  { key: 'retirement', label: 'Retirement' },
  { key: 'family', label: 'Family Members' },
  { key: 'summary', label: 'Summary' },
];
