from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from .analytics import correlation, metrics
from .providers import (
    ProviderError,
    fetch_amfi_aum,
    fetch_amfi_history,
    fetch_amfi_latest,
    fetch_amfi_ter,
    fetch_amfi_ter_snapshot,
    fetch_mfapi_data,
    parse_amfi_latest_nav_excel,
    parse_amfi_history_text_data,
    parse_amfi_text_data,
    parse_mfapi,
)

logger = logging.getLogger(__name__)


def _iso_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    for pattern in ('%d-%b-%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(text[:11], pattern).date().isoformat()
        except ValueError:
            continue
    return text


def _is_direct_growth(record: dict[str, Any]) -> bool:
    plan = (record.get('plan') or '').lower()
    option = (record.get('option') or '').lower()
    name = (record.get('scheme_name') or '').lower()
    return ('direct' in plan or 'direct' in name) and ('growth' in option or 'growth' in name)


def _pick_latest(records: list[dict[str, Any]], scheme_code: str) -> dict[str, Any]:
    matches = [record for record in records if str(record.get('scheme_code')) == str(scheme_code)]
    if not matches:
        raise ProviderError(f'Scheme {scheme_code} was not found in AMFI NAV data')
    direct_growth = [record for record in matches if _is_direct_growth(record)]
    return (direct_growth or matches)[0]


def _base_detail(record: dict[str, Any], *, source: str, as_of: str | None) -> dict[str, Any]:
    return {
        'source': source, 'asOfDate': _iso_date(as_of), 'scheme_code': str(record.get('scheme_code')),
        'scheme_name': record.get('scheme_name'), 'amc': record.get('amc'), 'category': record.get('category'),
        'scheme_type': record.get('scheme_type'), 'plan': record.get('plan'), 'option': record.get('option'),
        'isin': record.get('isin'), 'nav': record.get('nav'), 'nav_date': record.get('date'),
    }


def _today_window() -> tuple[date, date]:
    end = date.today()
    return end - timedelta(days=365 * 5 + 7), end


def fetch_fund_data(scheme_code: str, *, risk_free_rate: float = 0.065, include_history: bool = True, latest_records: list[dict[str, Any]] | None = None, ter_snapshot: dict[str, tuple[float | None, str | None]] | None = None) -> dict[str, Any]:
    """Fetch a fund live, preferring AMFI and using MFAPI only on AMFI failure."""
    try:
        latest_records = latest_records or fetch_amfi_latest()
        latest = _pick_latest(latest_records, scheme_code)
        history = []
        if include_history:
            start, end = _today_window()
            history = fetch_amfi_history(scheme_code, start, end)
        ter, ter_as_of = fetch_amfi_ter(scheme_code, latest_records, ter_snapshot)
        aum, aum_as_of = fetch_amfi_aum(latest.get('scheme_name') or '')
        result = _base_detail(latest, source='AMFI', as_of=latest.get('date'))
        result.update({'ter': ter, 'ter_as_of': ter_as_of, 'aum': aum, 'aum_unit': 'lakhs' if aum is not None else None, 'aum_as_of': aum_as_of, 'history': history})
        result['metrics'] = metrics(history, risk_free_rate) if history else None
        return result
    except (ProviderError, ValueError, TypeError, KeyError) as exc:
        logger.warning('AMFI fallback for scheme %s: %s', scheme_code, exc)
        try:
            payload = fetch_mfapi_data(scheme_code)
            meta, history = parse_mfapi(payload, scheme_code)
            latest = history[-1]
            result = _base_detail({**meta, **latest}, source='MFAPI (backup)', as_of=latest.get('date'))
            result.update({'ter': None, 'ter_as_of': None, 'aum': None, 'aum_unit': None, 'aum_as_of': None, 'history': history})
            result['metrics'] = metrics(history, risk_free_rate) if history else None
            return result
        except (ProviderError, ValueError, TypeError, KeyError) as backup_exc:
            logger.error('AMFI and MFAPI failed for scheme %s: %s', scheme_code, backup_exc)
            raise ProviderError(f'Unable to load scheme {scheme_code} from AMFI or MFAPI') from backup_exc


def search_funds(query: str, limit: int = 25) -> dict[str, Any]:
    records = fetch_amfi_latest()
    needle = query.strip().lower()
    filtered = [record for record in records if needle in ' '.join(str(record.get(key) or '') for key in ('scheme_name', 'scheme_code', 'isin', 'amc', 'category')).lower()]
    filtered = [record for record in filtered if _is_direct_growth(record)] or filtered
    as_of = max((record.get('date') for record in filtered if record.get('date')), default=None)
    return {'source': 'AMFI', 'asOfDate': _iso_date(as_of), 'results': filtered[:limit]}


def compare_funds(scheme_codes: list[str], risk_free_rate: float = 0.065) -> dict[str, Any]:
    try:
        latest_records = fetch_amfi_latest()
    except ProviderError as exc:
        logger.warning('AMFI latest snapshot unavailable for comparison: %s', exc)
        latest_records = None
    ter_snapshot = fetch_amfi_ter_snapshot() if latest_records is not None else None
    funds = [fetch_fund_data(code, risk_free_rate=risk_free_rate, latest_records=latest_records, ter_snapshot=ter_snapshot) for code in scheme_codes]
    matrix = {fund['scheme_code']: {} for fund in funds}
    for left in funds:
        for right in funds:
            if left['scheme_code'] == right['scheme_code']:
                matrix[left['scheme_code']][right['scheme_code']] = 1.0
            else:
                matrix[left['scheme_code']][right['scheme_code']] = correlation(left['history'], right['history'])
    source = 'MFAPI (backup)' if any(fund['source'] == 'MFAPI (backup)' for fund in funds) else 'AMFI'
    as_of = max((fund.get('asOfDate') for fund in funds if fund.get('asOfDate')), default=None)
    valid = [fund for fund in funds if fund.get('metrics')]
    top_cagr = max(valid, key=lambda fund: fund['metrics'].get('r3y') if fund['metrics'].get('r3y') is not None else float('-inf'), default=None)
    best_sharpe = max(valid, key=lambda fund: fund['metrics'].get('sharpe') if fund['metrics'].get('sharpe') is not None else float('-inf'), default=None)
    lowest_vol = min(valid, key=lambda fund: fund['metrics'].get('volatility') if fund['metrics'].get('volatility') is not None else float('inf'), default=None)
    return {'source': source, 'asOfDate': as_of, 'funds': funds, 'correlation': matrix, 'summary': {
        'riskFreeRate': risk_free_rate,
        'top3yCagr': top_cagr['scheme_code'] if top_cagr else None,
        'bestSharpe': best_sharpe['scheme_code'] if best_sharpe else None,
        'lowestVolatility': lowest_vol['scheme_code'] if lowest_vol else None,
    }}
