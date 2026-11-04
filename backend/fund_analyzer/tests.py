from datetime import date
from io import BytesIO
import unittest
from unittest.mock import patch

from openpyxl import Workbook
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from .analytics import cagr, max_drawdown, sharpe, volatility
from .holdings import AMC_SOURCES, _monthly_files_for_fund, _read_equity_holdings, analyze_holdings_overlap, import_portfolio_holdings
from .providers import ProviderError


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


class HoldingsOverlapTests(unittest.TestCase):
    @staticmethod
    def _portfolio_file(fund_name, rows, reporting_date='2026-09-30'):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = fund_name[:31]
        sheet.append(['Scheme', fund_name])
        sheet.append([f"Monthly Portfolio Statement as on {date.fromisoformat(reporting_date).strftime('%B %d, %Y')}"])
        sheet.append(['Instrument', 'ISIN', '% to NAV'])
        sheet.append(['EQUITY & EQUITY RELATED'])
        sheet.append(['Equity Shares'])
        for isin, weight in rows:
            sheet.append(['Stock', isin, weight])
        payload = BytesIO()
        workbook.save(payload)
        return payload.getvalue()

    def test_equity_parser_aggregates_duplicate_isins_and_excludes_debt(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'SBI Contra Fund'
        sheet.append(['Scheme', 'SBI Contra Fund'])
        sheet.append(['Instrument', 'ISIN', 'Market value', '% to AUM'])
        sheet.append(['EQUITY & EQUITY RELATED'])
        sheet.append(['Equity Shares'])
        sheet.append(['HDFC Bank', 'INE040A01034', 100, 4.79])
        sheet.append(['HDFC Bank', 'INE040A01034', 20, 1.21])
        sheet.append(['(b) Units issued by ReIT'])
        sheet.append(['REIT unit', 'INE0REI01000', 20, 2.29])
        sheet.append(['DEBT INSTRUMENTS'])
        sheet.append(['Bond', 'INE001A01000', 100, 20])
        payload = BytesIO()
        workbook.save(payload)

        holdings = _read_equity_holdings(payload.getvalue(), 'contra.xlsx', 'SBI Contra Fund', 'sbi_monthly_excel')
        self.assertEqual(holdings, {'INE040A01034': 6.0})

    def test_hdfc_public_excel_host_is_used_when_listing_is_forbidden(self):
        with (
            patch('fund_analyzer.holdings._load_page_links', side_effect=ProviderError('403 Forbidden')),
            patch('fund_analyzer.holdings._recent_portfolio_months', return_value={'2026-10', '2026-09'}),
        ):
            links = _monthly_files_for_fund(AMC_SOURCES['HDFC Mutual Fund'], 'HDFC Flexi Cap Fund - Direct Plan - Growth Option')
        self.assertEqual([link['month'] for link in links], ['2026-10', '2026-09'])
        self.assertEqual(links[1]['url'], 'https://files.hdfcfund.com/s3fs-public/2026-10/Monthly%20HDFC%20Flexi%20Cap%20Fund%20-%2030%20September%202026.xlsx')
        self.assertEqual(links[1]['listing_error'], '403 Forbidden')

    def test_unverified_hdfc_file_name_does_not_create_download_urls(self):
        with patch('fund_analyzer.holdings._load_page_links', side_effect=ProviderError('403 Forbidden')):
            with self.assertRaisesRegex(ProviderError, '403 Forbidden'):
                _monthly_files_for_fund(AMC_SOURCES['HDFC Mutual Fund'], 'Unknown HDFC Fund')

    def test_csv_disclosure_excludes_non_equity_rows(self):
        payload = (
            'SBI Contra Fund,,\nInstrument,ISIN,% to NAV\nEQUITY & EQUITY RELATED,,\n'
            'HDFC Bank,INE040A01034,5\nDEBT INSTRUMENTS,,\nBond,INE001A01000,20\n'
        ).encode('utf-8')
        holdings = _read_equity_holdings(payload, 'contra.csv', 'SBI Contra Fund', 'import_by_code')
        self.assertEqual(holdings, {'INE040A01034': 5.0})

    def test_import_rejects_workbook_for_another_fund(self):
        payload = self._portfolio_file('Different Equity Fund', [('INE040A01034', 5.0)])
        with self.assertRaisesRegex(ProviderError, 'No sheet matched fund'):
            _read_equity_holdings(payload, 'wrong.xlsx', 'SBI Contra Fund', 'import_by_code')

    def test_ppfas_prefers_its_fund_file_over_consolidated_file(self):
        links = [
            {'url': 'https://amc.ppfas.com/PPFAS_Monthly_Portfolio_Report_September_30_2026.xls', 'text': 'Consolidated', 'month': '2026-09'},
            {'url': 'https://amc.ppfas.com/PPTSF_PPFAS_Monthly_Portfolio_Report_September_30_2026.xlsx', 'text': 'PPTSF', 'month': '2026-09'},
        ]
        with patch('fund_analyzer.holdings._load_page_links', return_value=links):
            selected = _monthly_files_for_fund(AMC_SOURCES['PPFAS Mutual Fund'], 'Parag Parikh ELSS Tax Saver Fund')
        self.assertEqual(selected, [links[1]])

    def test_xlsx_content_with_xls_filename_is_parsed(self):
        payload = self._portfolio_file('SBI Contra Fund', [('INE040A01034', 4.79)])
        holdings = _read_equity_holdings(payload, 'contra.xls', 'SBI Contra Fund', 'sbi_monthly_excel')
        self.assertEqual(holdings, {'INE040A01034': 4.79})

    def test_import_rejects_date_that_differs_from_workbook(self):
        record = {'scheme_code': '119835', 'scheme_name': 'SBI Contra Fund', 'amc': 'SBI Mutual Fund', 'category': 'Equity Scheme - Contra Fund'}
        payload = self._portfolio_file('SBI Contra Fund', [('INE040A01034', 4.79)])
        with patch('fund_analyzer.holdings.fetch_amfi_latest', return_value=[record]):
            with self.assertRaisesRegex(ProviderError, 'file reports 2026-09-30'):
                import_portfolio_holdings('119835', '2026-10-31', 'sbi.xlsx', payload)

    def test_failed_newer_file_falls_back_to_latest_valid_common_month(self):
        records = [
            {'scheme_code': '119835', 'scheme_name': 'SBI Contra Fund', 'amc': 'SBI Mutual Fund', 'category': 'Equity Scheme - Contra Fund'},
            {'scheme_code': '118955', 'scheme_name': 'HDFC Flexi Cap Fund', 'amc': 'HDFC Mutual Fund', 'category': 'Equity Scheme - Flexi Cap Fund'},
        ]
        files = {}
        for record in records:
            for month, reporting_date in [('2026-10', '2026-10-31'), ('2026-09', '2026-09-30')]:
                files[(record['scheme_name'], month)] = self._portfolio_file(
                    record['scheme_name'], [('INE040A01034', 5.0 if record['scheme_code'] == '119835' else 7.0)], reporting_date,
                )

        def links(_source, fund_name):
            return [
                {'url': f'https://example.test/{fund_name}/{month}.xlsx', 'text': fund_name, 'month': month}
                for month in ('2026-10', '2026-09')
            ]

        def download(_amc, month, url):
            fund_name = url.split('/')[-2]
            if fund_name == 'HDFC Flexi Cap Fund' and month == '2026-10':
                raise ProviderError('October file timed out')
            return files[(fund_name, month)]

        with (
            patch('fund_analyzer.holdings.fetch_amfi_latest', return_value=records),
            patch('fund_analyzer.holdings._recent_portfolio_months', return_value={'2026-10', '2026-09'}),
            patch('fund_analyzer.holdings._imported_links', return_value=[]),
            patch('fund_analyzer.holdings._parsed_links', return_value=[]),
            patch('fund_analyzer.holdings._monthly_files_for_fund', side_effect=links),
            patch('fund_analyzer.holdings._download_cached', side_effect=download),
            patch('fund_analyzer.holdings._cache_parsed_holdings'),
        ):
            result = analyze_holdings_overlap(['119835', '118955'])
        self.assertEqual(result['portfolio_month'], '2026-09')
        self.assertEqual(result['highest_overlap']['percentage'], 5.0)
        self.assertEqual(result['highest_overlap']['portfolio_date'], '2026-09-30')
        self.assertIn('October file timed out', result['debug'][1]['errors_by_month']['2026-10'])

    @override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'overlap-stale-tests'}})
    def test_cached_hdfc_holdings_survive_blocked_page(self):
        records = [
            {'scheme_code': '119835', 'scheme_name': 'SBI Contra Fund', 'amc': 'SBI Mutual Fund', 'category': 'Equity Scheme - Contra Fund'},
            {'scheme_code': '118955', 'scheme_name': 'HDFC Flexi Cap Fund', 'amc': 'HDFC Mutual Fund', 'category': 'Equity Scheme - Flexi Cap Fund'},
        ]
        cache.clear()
        cache_key = 'fund-analyzer:portfolio-parsed:118955:2026-09'
        cache.set(cache_key, {'holdings': {'INE040A01034': 7.0}, 'portfolio_date': '2026-09-30'})
        cached_link = {'url': 'https://files.hdfcfund.com/hdfc.xlsx', 'cache_key': cache_key, 'month': '2026-09', 'cached': True}

        def links(_source, fund_name):
            if fund_name == 'HDFC Flexi Cap Fund':
                raise ProviderError('403 Forbidden')
            return [{'url': 'https://www.sbimf.com/sbi.xlsx', 'month': '2026-09', 'text': fund_name}]

        with (
            patch('fund_analyzer.holdings.fetch_amfi_latest', return_value=records),
            patch('fund_analyzer.holdings._recent_portfolio_months', return_value={'2026-09'}),
            patch('fund_analyzer.holdings._imported_links', return_value=[]),
            patch('fund_analyzer.holdings._parsed_links', side_effect=lambda code: [cached_link] if code == '118955' else []),
            patch('fund_analyzer.holdings._monthly_files_for_fund', side_effect=links),
            patch('fund_analyzer.holdings._download_cached', return_value=self._portfolio_file('SBI Contra Fund', [('INE040A01034', 5.0)])),
        ):
            result = analyze_holdings_overlap(['119835', '118955'])
        self.assertEqual(result['highest_overlap']['percentage'], 5.0)
        self.assertEqual(result['portfolio_month'], '2026-09')
        self.assertEqual(result['debug'][1]['error'], '403 Forbidden')

    def _analyze_month_schedule(self, schedule, weights):
        records = [
            {'scheme_code': str(index), 'scheme_name': name, 'amc': 'HDFC Mutual Fund', 'category': 'Equity Scheme - Flexi Cap Fund'}
            for index, name in enumerate(schedule, start=1)
        ]

        def links(_source, name):
            return [{'url': f'https://example.test/{name}/{month}.xlsx', 'month': month, 'text': name} for month in schedule[name]]

        def parsed(_payload, url, name, _parser, diagnostics, _workbook):
            month = url.rsplit('/', 1)[-1][:7]
            diagnostics['reporting_date'] = f'{month}-30' if month == '2026-09' else f'{month}-31'
            return {'INE040A01034': weights[(name, month)]}

        with (
            patch('fund_analyzer.holdings.fetch_amfi_latest', return_value=records),
            patch('fund_analyzer.holdings._recent_portfolio_months', return_value={'2026-10', '2026-09'}),
            patch('fund_analyzer.holdings._imported_links', return_value=[]),
            patch('fund_analyzer.holdings._parsed_links', return_value=[]),
            patch('fund_analyzer.holdings._monthly_files_for_fund', side_effect=links),
            patch('fund_analyzer.holdings._download_cached', return_value=b'workbook'),
            patch('fund_analyzer.holdings._workbook_sheets', return_value=({}, {})),
            patch('fund_analyzer.holdings._read_equity_holdings', side_effect=parsed),
            patch('fund_analyzer.holdings._cache_parsed_holdings'),
        ):
            return analyze_holdings_overlap([record['scheme_code'] for record in records])

    def test_three_funds_prefer_one_common_month_for_all_pairs(self):
        schedule = {'Fund A': ['2026-10', '2026-09'], 'Fund B': ['2026-10', '2026-09'], 'Fund C': ['2026-09']}
        weights = {('Fund A', '2026-10'): 8, ('Fund B', '2026-10'): 9,
                   ('Fund A', '2026-09'): 2, ('Fund B', '2026-09'): 3, ('Fund C', '2026-09'): 4}
        result = self._analyze_month_schedule(schedule, weights)
        self.assertEqual(result['portfolio_month'], '2026-09')
        self.assertEqual(len(result['pairs']), 3)
        self.assertTrue(all(pair['portfolio_month'] == '2026-09' for pair in result['pairs']))
        self.assertEqual(result['highest_overlap']['percentage'], 3.0)

    def test_two_funds_use_october_when_both_monthly_files_work(self):
        schedule = {'Fund A': ['2026-10', '2026-09'], 'Fund B': ['2026-10', '2026-09']}
        weights = {('Fund A', '2026-10'): 8, ('Fund B', '2026-10'): 9,
                   ('Fund A', '2026-09'): 2, ('Fund B', '2026-09'): 3}
        result = self._analyze_month_schedule(schedule, weights)
        self.assertEqual(result['portfolio_month'], '2026-10')
        self.assertEqual(result['highest_overlap']['portfolio_date'], '2026-10-31')
        self.assertEqual(result['highest_overlap']['percentage'], 8.0)
        self.assertEqual(result['debug'][0]['attempted_months'], ['2026-10'])

    def test_partial_pairs_report_when_they_use_different_months(self):
        schedule = {'Fund A': ['2026-10', '2026-09'], 'Fund B': ['2026-10'], 'Fund C': ['2026-09']}
        weights = {('Fund A', '2026-10'): 8, ('Fund B', '2026-10'): 9,
                   ('Fund A', '2026-09'): 2, ('Fund C', '2026-09'): 4}
        result = self._analyze_month_schedule(schedule, weights)
        self.assertEqual({pair['portfolio_month'] for pair in result['pairs']}, {'2026-10', '2026-09'})
        self.assertTrue(result['pairs_different_months'])
        self.assertTrue(result['highest_overlap']['partial_coverage'])
        self.assertEqual(result['highest_overlap']['portfolio_month'], '2026-10')

    @override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'overlap-import-tests'}})
    def test_imported_monthly_files_feed_highest_overlap(self):
        records = [
            {'scheme_code': '119835', 'scheme_name': 'SBI Contra Fund', 'amc': 'SBI Mutual Fund', 'category': 'Equity Scheme - Contra Fund'},
            {'scheme_code': '118955', 'scheme_name': 'HDFC Flexi Cap Fund', 'amc': 'HDFC Mutual Fund', 'category': 'Equity Scheme - Flexi Cap Fund'},
        ]
        cache.clear()
        with (
            patch('fund_analyzer.holdings.fetch_amfi_latest', return_value=records),
            patch('fund_analyzer.holdings._monthly_files_for_fund', side_effect=ProviderError('403 Forbidden')),
            patch('fund_analyzer.holdings._recent_portfolio_months', return_value={'2026-09'}),
        ):
            import_portfolio_holdings('119835', '2026-09-30', 'sbi.xlsx', self._portfolio_file('SBI Contra Fund', [
                ('INE040A01034', 5.0), ('INE090A01021', 4.0), ('INE002A01018', 3.0),
            ]))
            import_portfolio_holdings('118955', '2026-09-30', 'hdfc.xlsx', self._portfolio_file('HDFC Flexi Cap Fund', [
                ('INE040A01034', 7.0), ('INE090A01021', 6.0), ('INE009A01021', 2.0),
            ]))
            result = analyze_holdings_overlap(['119835', '118955'])
            endpoint_response = APIClient().post('/api/overlap', {'scheme_codes': ['119835', '118955']}, format='json')
        self.assertEqual(result['highest_overlap']['percentage'], 9.0)
        self.assertEqual(result['highest_overlap']['portfolio_date'], '2026-09-30')
        self.assertFalse(result['highest_overlap']['partial_coverage'])
        self.assertEqual(endpoint_response.status_code, 200)
        self.assertEqual(endpoint_response.data['highest_overlap']['percentage'], 9.0)

    def _analyze(self, holdings_by_name, dates=None):
        records = [
            {'scheme_code': str(index), 'scheme_name': name, 'amc': 'HDFC Mutual Fund', 'category': 'Equity Scheme - Flexi Cap Fund'}
            for index, name in enumerate(holdings_by_name, start=1)
        ]
        dates = dates or {}

        def links_for_fund(_source, name):
            return [{
                'url': f'https://example.test/{name}.xlsx',
                'text': name,
                'month': '2026-09',
                'portfolio_date': dates.get(name, '2026-09-30'),
            }]

        def parsed_holdings(_payload, _url, name, *_args):
            value = holdings_by_name[name]
            if isinstance(value, Exception):
                raise value
            _args[1]['reporting_date'] = dates.get(name, '2026-09-30')
            return value

        with (
            patch('fund_analyzer.holdings.fetch_amfi_latest', return_value=records),
            patch('fund_analyzer.holdings._imported_links', return_value=[]),
            patch('fund_analyzer.holdings._parsed_links', return_value=[]),
            patch('fund_analyzer.holdings._recent_portfolio_months', return_value={'2026-09'}),
            patch('fund_analyzer.holdings._monthly_files_for_fund', side_effect=links_for_fund),
            patch('fund_analyzer.holdings._download_cached', return_value=b'workbook'),
            patch('fund_analyzer.holdings._workbook_sheets', return_value=({}, {})),
            patch('fund_analyzer.holdings._read_equity_holdings', side_effect=parsed_holdings),
        ):
            return analyze_holdings_overlap([row['scheme_code'] for row in records])

    def test_eight_funds_produce_twenty_eight_pairs(self):
        holdings = {f'Fund {index}': {'INE040A01034': float(index)} for index in range(1, 9)}
        result = self._analyze(holdings)
        self.assertEqual(len(result['pairs']), 28)
        self.assertEqual(result['highest_overlap']['percentage'], 7.0)
        self.assertFalse(result['highest_overlap']['partial_coverage'])

    def test_zero_overlap_is_available(self):
        result = self._analyze({'Fund A': {'INE040A01034': 5.0}, 'Fund B': {'INE002A01018': 7.0}})
        self.assertTrue(result['highest_overlap']['available'])
        self.assertEqual(result['highest_overlap']['percentage'], 0.0)

    def test_debt_fund_returns_not_applicable_message(self):
        records = [
            {'scheme_code': '1', 'scheme_name': 'Bond Fund', 'amc': 'SBI Mutual Fund', 'category': 'Debt Scheme - Corporate Bond Fund'},
            {'scheme_code': '2', 'scheme_name': 'Equity Fund', 'amc': 'HDFC Mutual Fund', 'category': 'Equity Scheme - Flexi Cap Fund'},
        ]
        with (
            patch('fund_analyzer.holdings.fetch_amfi_latest', return_value=records),
            patch('fund_analyzer.holdings._imported_links', return_value=[]),
            patch('fund_analyzer.holdings._monthly_files_for_fund', return_value=[]),
        ):
            result = analyze_holdings_overlap(['1', '2'])
        self.assertFalse(result['highest_overlap']['available'])
        self.assertEqual(result['highest_overlap']['message'], 'Overlap not applicable for debt funds')

    def test_missing_holdings_are_excluded_and_coverage_is_partial(self):
        result = self._analyze({
            'Fund A': {'INE040A01034': 5.0},
            'Fund B': {'INE040A01034': 3.0},
            'Fund C': ProviderError('Portfolio file unavailable'),
        })
        self.assertEqual(result['highest_overlap']['percentage'], 3.0)
        self.assertEqual(result['highest_overlap']['compared_pairs'], 1)
        self.assertTrue(result['highest_overlap']['partial_coverage'])

    def test_same_month_with_different_reporting_dates_has_no_exact_date(self):
        result = self._analyze(
            {'Fund A': {'INE040A01034': 5.0}, 'Fund B': {'INE040A01034': 3.0}},
            dates={'Fund A': '2026-09-29', 'Fund B': '2026-09-30'},
        )
        self.assertEqual(result['portfolio_month'], '2026-09')
        self.assertIsNone(result['highest_overlap']['portfolio_date'])
