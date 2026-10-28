export const inr = (n) => `${n < 0 ? '-' : ''}₹${Math.abs(n).toLocaleString('en-IN')}`;
export const pct = (n) => `${n.toFixed(1)}%`;
