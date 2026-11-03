from datetime import date
import unittest

from .analytics import cagr, max_drawdown, sharpe, volatility


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.nav = [
            {'date': date(2021, 1, 1).isoformat(), 'nav': 110},
            {'date': date(2022, 1, 1).isoformat(), 'nav': 100},
            {'date': date(2023, 1, 1).isoformat(), 'nav': 120},
            {'date': date(2024, 1, 1).isoformat(), 'nav': 90},
            {'date': date(2025, 1, 1).isoformat(), 'nav': 150},
            {'date': date(2026, 1, 1).isoformat(), 'nav': 180},
        ]

    def test_cagr(self):
        self.assertAlmostEqual(cagr(self.nav, 5), ((180 / 110) ** 0.2) - 1, places=8)

    def test_volatility_is_annualised(self):
        self.assertIsNotNone(volatility(self.nav, years=3))

    def test_sharpe_uses_configured_risk_free_rate(self):
        self.assertAlmostEqual(sharpe(self.nav, 0), cagr(self.nav, 3) / volatility(self.nav, 3), places=8)

    def test_drawdown(self):
        self.assertAlmostEqual(max_drawdown(self.nav, years=3), 90 / 120 - 1, places=8)
