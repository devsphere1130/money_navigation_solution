import { useEffect, useState } from 'react';
import CalcPanel from '../components/CalcPanel.jsx';
import ChartCard, { GOLD } from '../components/ChartCard.jsx';
import { Breakdown, ResultCard, ResultRow } from '../components/Results.jsx';
import { getInflation } from '../../../services/calculatorService.js';
import { inr, pct, times, yrs } from '../format.js';

export const defaults = { presentCost: '100000', rate: '6', years: '15' };

const SECTIONS = [{
  heading: 'INPUTS',
  fields: [
    { name: 'presentCost', label: 'Present cost', kind: 'money' },
    { name: 'rate', label: 'Inflation rate', kind: 'percent' },
    { name: 'years', label: 'Years', kind: 'years' },
  ],
}];

export default function InflationCalculator({ values, onChange }) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!values.presentCost || !values.rate || !values.years) {
      setError('Fill in all fields to calculate.');
      return undefined;
    }

    const controller = new AbortController();
    // Wait until the user stops typing before calling the API.
    const timer = setTimeout(() => {
      setLoading(true);
      getInflation(values, controller.signal)
        .then((data) => {
          setResult(data);
          setError('');
        })
        .catch((err) => {
          if (!controller.signal.aborted) setError(err.message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 400);

    // Runs when inputs change again or the tab closes: drop the pending timer and request.
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [values]);

  return (
    <div className="calc__grid">
      <CalcPanel
        title="Inflation calculator"
        description="What something that costs this much today will cost in the future."
        sections={SECTIONS}
        values={values}
        onChange={onChange}
      >
        {error && <p className="calc-error">{error}</p>}
        {!result && !error && <p className="calc-status">Calculating…</p>}
        {result && (
          <div className={`calc-panel__results-body${loading ? ' calc-loading' : ''}`}>
            <ResultCard
              tone="hero"
              label="FUTURE COST"
              value={inr(result.future_cost)}
              note={`after ${yrs(result.years)} at ${pct(result.rate, 2)} a year`}
            />
            <ResultRow>
              <ResultCard tone="accent" label="COST INCREASE" value={inr(result.cost_increase)} />
              <ResultCard label="TIMES TODAY'S COST" value={times(result.times_cost)} />
            </ResultRow>
            <Breakdown
              rows={[
                { label: 'Present cost', value: inr(result.present_cost) },
                { label: <>× (1 + {pct(result.rate, 2)})<sup>{result.years}</sup></>, value: result.factor.toFixed(4) },
              ]}
              total={{ label: 'Future cost', value: inr(result.future_cost) }}
            />
          </div>
        )}
      </CalcPanel>

      {result && (
        <ChartCard
          title="Cost growth due to inflation"
          subtitle={`From ${inr(result.present_cost)} today to ${inr(result.future_cost)} in ${yrs(result.years)}`}
          data={result.chart}
          series={[{ key: 'cost', label: 'Cost', color: GOLD, fill: true }]}
          stats={[
            { label: 'Today', value: inr(result.present_cost) },
            { label: `Half-way (yr ${result.half_way_year})`, value: inr(result.half_way_cost) },
            { label: 'Purchasing power of ₹1 lakh then', value: inr(result.purchasing_power_of_lakh) },
          ]}
        />
      )}
    </div>
  );
}
