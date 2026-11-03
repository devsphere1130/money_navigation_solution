from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

import requests

logger = logging.getLogger(__name__)

AMFI_NAV_URL = 'https://portal.amfiindia.com/spages/NAVAll.txt'
AMFI_HISTORY_DOWNLOAD_URL = 'https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx'
AMFI_HISTORY_URL = 'https://www.amfiindia.com/api/nav-history'
AMFI_TER_URL = 'https://www.amfiindia.com/api/populate-ter-rdata-revised'
AMFI_AUM_URL = 'https://portal.amfiindia.com/AUMReport_Rpt_Po.aspx'
MFAPI_URL = 'https://api.mfapi.in/mf'
HEADERS = {'User-Agent': 'MNS-Fund-Analyzer/1.0', 'Accept': '*/*'}


class ProviderError(RuntimeError):
    pass


def fetch_url(url: str, *, params: dict[str, Any] | None = None, timeout: tuple[int, int] = (5, 35)) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            return response
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < 2:
                continue
    raise ProviderError(str(last_error) if last_error else 'Provider request failed')


def _clean(value: Any) -> str | None:
    value = str(value or '').strip()
    return value if value and value != '-' else None


def _category_from_header(value: str) -> tuple[str | None, str | None]:
    match = re.match(r'(?P<type>Open|Close|Interval)\s+Ended\s+Schemes?\s*\(\s*(?P<category>.*?)\s*\)', value, re.I)
    if not match:
        return None, None
    return match.group('type').title(), match.group('category') or None


def parse_amfi_text_data(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    amc: str | None = None
    scheme_type: str | None = None
    category: str | None = None
    for raw in text.splitlines():
        line = raw.strip().lstrip('\ufeff')
        if not line:
            continue
        fields = [field.strip() for field in line.split(';')]
        if len(fields) == 1:
            next_type, next_category = _category_from_header(line)
            if next_type:
                scheme_type, category = next_type, next_category
            elif not line.lower().startswith(('scheme code', 'net asset value')):
                amc = line
            continue
        if not fields[0].isdigit():
            continue
        try:
            if len(fields) >= 8:
                code, isin_growth, isin_reinvest, name, plan, option, nav, nav_date = fields[:8]
            elif len(fields) == 6:
                code, isin_growth, isin_reinvest, name, nav, nav_date = fields
                plan = option = ''
            else:
                continue
            value = float(nav.replace(',', ''))
            if value <= 0:
                continue
            records.append({
                'scheme_code': code, 'isin': _clean(isin_growth) or _clean(isin_reinvest),
                'scheme_name': name, 'plan': _clean(plan), 'option': _clean(option), 'nav': value,
                'date': nav_date, 'amc': amc, 'scheme_type': scheme_type, 'category': category,
            })
        except (TypeError, ValueError):
            continue
    if not records:
        raise ProviderError('AMFI NAV data was empty or invalid')
    return records


def fetch_amfi_latest() -> list[dict[str, Any]]:
    response = fetch_url(AMFI_NAV_URL)
    return parse_amfi_text_data(response.text)


def parse_amfi_latest_nav_excel(payload: bytes) -> list[dict[str, Any]]:
    """Compatibility parser for an AMFI latest-NAV spreadsheet payload."""
    import pandas as pd
    from io import BytesIO

    frame = pd.read_excel(BytesIO(payload))
    columns = {str(column).strip().lower(): column for column in frame.columns}
    code_column = next((columns[key] for key in columns if 'scheme code' in key or key == 'code'), None)
    name_column = next((columns[key] for key in columns if 'scheme name' in key or key == 'name'), None)
    nav_column = next((columns[key] for key in columns if key == 'net asset value' or key == 'nav'), None)
    date_column = next((columns[key] for key in columns if key == 'date' or 'nav date' in key), None)
    if not all((code_column, name_column, nav_column, date_column)):
        raise ProviderError('AMFI latest NAV workbook columns were not recognised')
    result = []
    for row in frame.to_dict('records'):
        try:
            result.append({'scheme_code': str(row[code_column]), 'scheme_name': str(row[name_column]), 'nav': float(row[nav_column]), 'date': str(row[date_column])})
        except (TypeError, ValueError):
            continue
    if not result:
        raise ProviderError('AMFI latest NAV workbook was empty')
    return result


def _history_rows(payload: dict[str, Any], scheme_code: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    data = payload.get('data') or {}
    for group in data.get('nav_groups') or []:
        for row in group.get('historical_records') or []:
            try:
                value = float(row.get('nav'))
                if value > 0:
                    rows.append({'scheme_code': scheme_code, 'date': row.get('date'), 'nav': value})
            except (TypeError, ValueError):
                continue
    return rows


def fetch_amfi_history(scheme_code: str, start: date, end: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=1790))
        response = fetch_url(AMFI_HISTORY_URL, params={'query_type': 'historical_period', 'from_date': cursor.isoformat(), 'to_date': chunk_end.isoformat(), 'sd_id': scheme_code})
        chunk = _history_rows(response.json(), scheme_code)
        if not chunk:
            raise ProviderError(f'AMFI returned no history for scheme {scheme_code}')
        rows.extend(chunk)
        cursor = chunk_end + timedelta(days=1)
    unique = {(row['date'], row['nav']): row for row in rows}
    return sorted(unique.values(), key=lambda row: row['date'])


def parse_amfi_history_text_data(text: str, scheme_code: str) -> list[dict[str, Any]]:
    """Parse AMFI's downloadable semicolon history format for one scheme."""
    rows = []
    for raw in text.splitlines():
        fields = [field.strip() for field in raw.strip().split(';')]
        if len(fields) < 8 or fields[0] != str(scheme_code):
            continue
        try:
            nav = float(next(value for value in (fields[4], fields[6]) if value not in ('', '-')).replace(',', ''))
            if nav > 0:
                rows.append({'scheme_code': str(scheme_code), 'date': fields[7], 'nav': nav})
        except (TypeError, ValueError):
            continue
    return sorted(rows, key=lambda row: row['date'])


def fetch_mfapi_data(scheme_code: str, latest: bool = False) -> dict[str, Any]:
    suffix = '/latest' if latest else ''
    response = fetch_url(f'{MFAPI_URL}/{scheme_code}{suffix}')
    payload = response.json()
    if not isinstance(payload, dict):
        raise ProviderError('MFAPI returned invalid JSON')
    return payload


def parse_mfapi(payload: dict[str, Any], scheme_code: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    meta = payload.get('meta') or {}
    rows = []
    for item in payload.get('data') or []:
        try:
            rows.append({'scheme_code': scheme_code, 'date': item.get('date'), 'nav': float(item.get('nav'))})
        except (TypeError, ValueError):
            continue
    if not rows:
        raise ProviderError(f'MFAPI returned no NAV history for scheme {scheme_code}')
    info = {'scheme_code': scheme_code, 'scheme_name': meta.get('scheme_name'), 'amc': meta.get('fund_house'), 'category': meta.get('scheme_category'), 'isin': meta.get('isin_div_payout'), 'plan': None, 'option': None}
    return info, sorted(rows, key=lambda row: row['date'])


def fetch_amfi_ter_snapshot() -> dict[str, tuple[float | None, str | None]]:
    """Fetch the current AMFI TER table once, keyed by scheme code."""
    try:
        today = date.today()
        financial_year = today.year if today.month >= 4 else today.year - 1
        year = f'{financial_year}-{financial_year + 1}'
        months = fetch_url('https://www.amfiindia.com/api/populate-ter-month', params={'year': year}).json()
        month_rows = months[0].get('data', []) if isinstance(months, list) and months else []
        if not month_rows:
            return None, None
        month = month_rows[0].get('MonthNumber')
        result: dict[str, tuple[float | None, str | None]] = {}
        for fund_type in ('-1', '1', '2', '3'):
            first = fetch_url(AMFI_TER_URL, params={'MF_ID': 'All', 'Month': month, 'strCat': '-1', 'strType': fund_type, 'page': 1, 'pageSize': 100}).json()
            meta = first.get('meta') or {}
            pages = int(meta.get('pageCount') or 1)
            for page in range(1, pages + 1):
                payload = first if page == 1 else fetch_url(AMFI_TER_URL, params={'MF_ID': 'All', 'Month': month, 'strCat': '-1', 'strType': fund_type, 'page': page, 'pageSize': 100}).json()
                rows = payload.get('data') if isinstance(payload, dict) else []
                for row in rows if isinstance(rows, list) else []:
                    code = str(row.get('NSDLSchemeCode') or row.get('SchemeCode') or '')
                    value = row.get('D_TER') or row.get('D_TER_Total')
                    result[code] = ((float(value) if value not in (None, '') else None), row.get('TER_Date'))
            if result:
                return result
    except (ProviderError, ValueError, TypeError, AttributeError, KeyError):
        return {}
    return result


def fetch_amfi_ter(scheme_code: str, latest_records: list[dict[str, Any]], ter_snapshot: dict[str, tuple[float | None, str | None]] | None = None) -> tuple[float | None, str | None]:
    """Fetch current TER for one scheme, returning null when AMFI has no match."""
    snapshot = ter_snapshot if ter_snapshot is not None else fetch_amfi_ter_snapshot()
    return snapshot.get(str(scheme_code), (None, None))


def fetch_amfi_aum(scheme_name: str) -> tuple[float | None, str | None]:
    """Read the current scheme-wise AAUM report; values are in lakhs."""
    try:
        today = date.today()
        quarter_start_month = ((today.month - 1) // 3) * 3 + 1
        if quarter_start_month == 1:
            report_date = date(today.year - 1, 10, 1)
        else:
            report_date = date(today.year, quarter_start_month - 3, 1)
        quarter_end_month = report_date.month + 2
        quarter = f'{report_date.strftime("%B")} - {date(report_date.year, quarter_end_month, 1).strftime("%B")} {report_date.year}'
        response = fetch_url(AMFI_AUM_URL, params={'dtAUM': report_date.strftime('%d-%b-%Y'), 'mf': 0, 'qt': quarter, 'rpt': 'scwise'})
        text = response.text
        match = re.search(re.escape(scheme_name) + r'.{0,500}?([\d,]+\.\d+)\s+([\d,]+\.\d+)', text, re.I | re.S)
        if not match:
            return None, None
        return float(match.group(1).replace(',', '')), report_date.isoformat()
    except (ProviderError, ValueError, TypeError):
        return None, None
