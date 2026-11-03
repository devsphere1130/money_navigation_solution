from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from html.parser import HTMLParser
from io import BytesIO
from threading import Lock
from urllib.parse import unquote, urljoin, urlsplit

import pandas as pd
from django.core.cache import cache

from .providers import ProviderError, fetch_amfi_latest, fetch_url

logger = logging.getLogger(__name__)

# The keys must exactly match the AMC names in AMFI NAVAll.txt. These are
# official AMC disclosure pages; each parser key handles that page's file list.
AMC_SOURCES = {
    'HDFC Mutual Fund': {
        'key': 'hdfc',
        'url': 'https://www.hdfcfund.com/statutory-disclosure/portfolio/monthly-portfolio',
        'parser': 'hdfc_xlsx_by_scheme',
    },
    'PPFAS Mutual Fund': {
        'key': 'ppfas',
        'url': 'https://amc.ppfas.com/downloads/portfolio-disclosure/',
        'parser': 'ppfas_consolidated_excel',
    },
    'Nippon India Mutual Fund': {
        'key': 'nippon',
        'url': 'https://mf.nipponindiaim.com/investor-service/downloads/factsheet-portfolio-and-other-disclosures/',
        'parser': 'nippon_monthly_excel',
    },
}

PORTFOLIO_CACHE_SECONDS = 24 * 60 * 60
PAGE_CACHE_SECONDS = 60 * 60
PORTFOLIO_CACHE_MAX_BYTES = 128 * 1024 * 1024
_download_lock = Lock()
_portfolio_file_cache: dict[tuple[str, str], tuple[datetime, dict[str, bytes]]] = {}


class _PortfolioLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a':
            self._current = {'href': dict(attrs).get('href', ''), 'text': ''}

    def handle_data(self, data):
        if self._current is not None:
            self._current['text'] += data

    def handle_endtag(self, tag):
        if tag.lower() == 'a' and self._current is not None:
            self.links.append(self._current)
            self._current = None


def _month_in_text(value: str) -> str | None:
    text = re.sub(r'[-_./]+', ' ', value)
    patterns = (
        '%d %B %Y', '%d %b %Y', '%d %B %y', '%d %b %y',
        '%B %d %Y', '%b %d %Y', '%B %Y', '%b %Y', '%B %y', '%b %y',
    )
    candidates = re.findall(
        r'(?i)(?:\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}\b|'
        r'\b[A-Za-z]{3,9}\s+\d{1,2}\s+\d{2,4}\b|'
        r'\b[A-Za-z]{3,9}\s+\d{2,4}\b)', text,
    )
    for candidate in candidates:
        for pattern in patterns:
            try:
                return datetime.strptime(candidate, pattern).strftime('%Y-%m')
            except ValueError:
                continue
    return None


def _normalise_name(value: str) -> str:
    text = re.sub(r'\b(direct|regular|growth|option|plan|idcw|reinvestment|reinvest|dividend)\b', ' ', value, flags=re.I)
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


def _is_debt_fund(record: dict) -> bool:
    category = re.sub(r'\s+', ' ', str(record.get('category') or '')).strip().lower()
    return category.startswith('debt scheme') or category.startswith('debt fund')


def _scheme_link_matches(text: str, fund_name: str) -> bool:
    wanted = _normalise_name(fund_name)
    candidate = _normalise_name(unquote(text))
    return bool(wanted and (wanted in candidate or candidate in wanted))


def _candidate_link(parser_key: str, text: str, href: str) -> bool:
    combined = f'{text} {href}'.lower()
    path = urlsplit(href).path.lower()
    if not path.endswith(('.xls', '.xlsx')):
        return False
    if 'fortnight' in combined or 'half-year' in combined or 'half yearly' in combined:
        return False
    if parser_key == 'hdfc_xlsx_by_scheme':
        return 'monthly' in combined
    if parser_key == 'ppfas_consolidated_excel':
        return 'consolidated' in combined or 'ppfas_monthly_portfolio_report' in combined
    if parser_key == 'nippon_monthly_excel':
        return 'monthly portfolio' in combined or 'monthly-portfolio' in combined
    return False


def _load_page_links(amc_key: str, page_url: str, parser_key: str) -> list[dict[str, str]]:
    cache_key = f'fund-analyzer:portfolio-page:{amc_key}'
    try:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    except Exception:
        logger.exception('Portfolio page cache read failed for %s', amc_key)

    response = fetch_url(page_url, timeout=(2, 8), attempts=1)
    parser = _PortfolioLinks()
    parser.feed(response.text)
    results = []
    for link in parser.links:
        href = urljoin(page_url, link['href'].strip())
        text = re.sub(r'\s+', ' ', link['text']).strip()
        if not _candidate_link(parser_key, text, href):
            continue
        month = _month_in_text(f'{text} {href}')
        if month:
            results.append({'url': href, 'text': text, 'month': month})
    if not results:
        raise ProviderError(f'No monthly portfolio files found for {amc_key}')
    try:
        cache.set(cache_key, results, timeout=PAGE_CACHE_SECONDS)
    except Exception:
        logger.exception('Portfolio page cache write failed for %s', amc_key)
    return results


def _monthly_files_for_fund(source: dict, fund_name: str) -> list[dict[str, str]]:
    links = _load_page_links(source['key'], source['url'], source['parser'])
    if source['parser'] == 'hdfc_xlsx_by_scheme':
        links = [link for link in links if _scheme_link_matches(f"{link['text']} {urlsplit(link['url']).path}", fund_name)]
    return links


def _download_cached(amc_key: str, month: str, url: str) -> bytes:
    key = (amc_key, month)
    with _download_lock:
        now = datetime.now()
        cached_entry = _portfolio_file_cache.get(key)
        if cached_entry and cached_entry[0] > now and url in cached_entry[1]:
            return cached_entry[1][url]
        cached_files = cached_entry[1] if cached_entry and cached_entry[0] > now else {}

        response = fetch_url(url, timeout=(3, 20), attempts=1)
        payload = response.content
        if not payload:
            raise ProviderError(f'Empty monthly portfolio file from {amc_key}')
        cached_files[url] = payload
        _portfolio_file_cache[key] = (now + timedelta(seconds=PORTFOLIO_CACHE_SECONDS), cached_files)
        # Bound memory use if a long-lived worker sees many AMC/month pairs.
        while len(_portfolio_file_cache) > 32:
            oldest = min(_portfolio_file_cache, key=lambda cache_key: _portfolio_file_cache[cache_key][0])
            del _portfolio_file_cache[oldest]
        while sum(len(file_bytes) for _, files in _portfolio_file_cache.values() for file_bytes in files.values()) > PORTFOLIO_CACHE_MAX_BYTES:
            oldest = min(_portfolio_file_cache, key=lambda cache_key: _portfolio_file_cache[cache_key][0])
            del _portfolio_file_cache[oldest]
        return payload


def _sheet_name_score(sheet_name: str, frame: pd.DataFrame, fund_name: str) -> int:
    wanted = _normalise_name(fund_name)
    text = sheet_name
    for value in frame.fillna('').astype(str).to_numpy().ravel():
        text += f' {value}'
    candidate = _normalise_name(text)
    if wanted and wanted in candidate:
        return 2
    if candidate and candidate in wanted and len(candidate) >= max(12, int(len(wanted) * 0.7)):
        return 1
    return 0


def _column_index(headers: list[str], candidates: tuple[str, ...]) -> int | None:
    for index, header in enumerate(headers):
        compact = re.sub(r'[^a-z0-9%]+', ' ', header.lower()).strip()
        if any(candidate in compact for candidate in candidates):
            return index
    return None


def _is_equity_section(text: str) -> bool | None:
    value = re.sub(r'[^a-z]+', ' ', text.lower())
    if any(token in value for token in ('equity and equity related', 'equity related instruments', 'equity shares', 'equity instruments')):
        return True
    if any(token in value for token in ('debt instruments', 'money market instruments', 'government securities', 'cash and cash equivalents', 'other assets')):
        return False
    return None


def _section_for_row(row) -> bool | None:
    values = [str(value) for value in row if not pd.isna(value) and str(value).strip()]
    return _is_equity_section(' '.join(values)) if len(values) <= 3 else None


def _as_weight(value, number_format: str = '') -> float | None:
    try:
        if pd.isna(value):
            return None
        raw_value = str(value).strip()
        result = float(raw_value.replace(',', '').replace('%', '').strip())
        if '%' in number_format and '%' not in raw_value:
            result *= 100
        return result if 0 <= result <= 100 else None
    except (TypeError, ValueError):
        return None


def _workbook_sheets(payload: bytes, suffix: str) -> tuple[dict[str, pd.DataFrame], dict[str, list[list[str]]]]:
    if suffix.endswith('.xls'):
        import xlrd

        workbook = xlrd.open_workbook(file_contents=payload, formatting_info=True)
        frames = {}
        formats = {}
        for sheet in workbook.sheets():
            frames[sheet.name] = pd.DataFrame([sheet.row_values(row) for row in range(sheet.nrows)])
            cell_formats = []
            for row in range(sheet.nrows):
                format_row = []
                for column in range(sheet.ncols):
                    xf = workbook.xf_list[sheet.cell_xf_index(row, column)]
                    fmt = workbook.format_map.get(xf.format_key)
                    format_row.append(fmt.format_str if fmt else '')
                cell_formats.append(format_row)
            formats[sheet.name] = cell_formats
        return frames, formats

    from openpyxl import load_workbook

    workbook = load_workbook(BytesIO(payload), read_only=True, data_only=True)
    frames = {}
    formats = {}
    for sheet in workbook.worksheets:
        frames[sheet.title] = pd.DataFrame(list(sheet.values))
        formats[sheet.title] = [[cell.number_format or '' for cell in row] for row in sheet.iter_rows()]
    workbook.close()
    return frames, formats


def _read_equity_holdings(payload: bytes, url: str, fund_name: str, parser_key: str) -> dict[str, float]:
    suffix = urlsplit(url).path.lower()
    try:
        sheets, formats_by_sheet = _workbook_sheets(payload, suffix)
    except Exception as exc:
        raise ProviderError('Monthly portfolio workbook could not be parsed') from exc
    if not sheets:
        raise ProviderError('Monthly portfolio workbook contains no sheets')

    ranked = sorted((( _sheet_name_score(name, frame, fund_name), name, frame) for name, frame in sheets.items()), key=lambda row: row[0], reverse=True)
    if not ranked or ranked[0][0] == 0:
        if parser_key == 'hdfc_xlsx_by_scheme' and len(ranked) == 1:
            _, sheet_name, frame = ranked[0]
        else:
            raise ProviderError(f'No sheet matched fund {fund_name}')
    else:
        _, sheet_name, frame = ranked[0]

    header_candidates = []
    for row_index in range(min(len(frame), 80)):
        row_headers = [str(value).strip() if not pd.isna(value) else '' for value in frame.iloc[row_index].tolist()]
        normalised = [re.sub(r'[^a-z0-9%]+', ' ', value.lower()).strip() for value in row_headers]
        candidate_isin = _column_index(normalised, ('isin',))
        candidate_weight = _column_index(normalised, ('% to nav', 'percent to nav', '% of net assets', 'percentage to nav', 'percentage of net assets'))
        candidate_market_value = _column_index(normalised, ('market value', 'market value rs', 'value rs'))
        if candidate_isin is not None and (candidate_weight is not None or candidate_market_value is not None):
            header_candidates.append((row_index, candidate_isin, candidate_weight, _column_index(normalised, ('asset class', 'asset type', 'nature of instrument', 'instrument type', 'classification')), candidate_market_value))
    if not header_candidates:
        raise ProviderError(f'ISIN and portfolio weight/value columns were not found for {fund_name}')

    wanted_name = _normalise_name(fund_name)
    named_headers = []
    for header in header_candidates:
        header_row = header[0]
        context_rows = frame.iloc[max(0, header_row - 20):header_row, :12].fillna('').astype(str).to_numpy().ravel()
        context = _normalise_name(' '.join(context_rows))
        if wanted_name and wanted_name in context:
            named_headers.append(header)
    if named_headers:
        header_at, isin_at, weight_at, asset_at, market_value_at = named_headers[-1]
    elif len(header_candidates) == 1 and (_sheet_name_score(sheet_name, frame, fund_name) > 0 or parser_key == 'hdfc_xlsx_by_scheme'):
        header_at, isin_at, weight_at, asset_at, market_value_at = header_candidates[0]
    else:
        raise ProviderError(f'No holdings section matched fund {fund_name}')
    section_end = next((header[0] for header in header_candidates if header[0] > header_at), len(frame))

    total_fund_value = None
    if weight_at is None and market_value_at is not None:
        for _, total_row in frame.iterrows():
            label = ' '.join(str(value) for value in total_row.iloc[:min(len(total_row), 6)].tolist()).lower()
            if not any(marker in label for marker in ('net assets', 'grand total', 'total assets', 'total portfolio value')):
                continue
            if market_value_at >= len(total_row) or pd.isna(total_row.iloc[market_value_at]):
                continue
            try:
                value = float(str(total_row.iloc[market_value_at]).replace(',', '').strip())
                if value > 0:
                    total_fund_value = value
            except (TypeError, ValueError):
                continue
        if total_fund_value is None:
            raise ProviderError(f'Total fund value was not found for {fund_name}')

    equity_context: bool | None = None
    for row_index in range(header_at):
        section = _section_for_row(frame.iloc[row_index].tolist())
        if section is not None:
            equity_context = section

    holdings: dict[str, float] = {}
    saw_equity_classification = False
    cell_formats = formats_by_sheet.get(sheet_name, [])
    for row_index in range(header_at + 1, section_end):
        row = frame.iloc[row_index].tolist()
        section = _section_for_row(row)
        if section is not None:
            equity_context = section
            continue

        is_equity = equity_context is True
        if asset_at is not None and asset_at < len(row) and not pd.isna(row[asset_at]):
            classification = str(row[asset_at]).strip().lower()
            if classification:
                saw_equity_classification = True
                is_equity = 'equity' in classification and 'non equity' not in classification
        if not is_equity:
            continue
        if isin_at >= len(row) or (weight_at is not None and weight_at >= len(row)) or (weight_at is None and (market_value_at is None or market_value_at >= len(row))):
            continue
        isin_value = '' if pd.isna(row[isin_at]) else str(row[isin_at])
        isin = re.sub(r'\s+', '', isin_value).upper()
        if weight_at is not None:
            weight_format = cell_formats[row_index][weight_at] if row_index < len(cell_formats) and weight_at < len(cell_formats[row_index]) else ''
            weight = _as_weight(row[weight_at], weight_format)
        else:
            try:
                market_value = float(str(row[market_value_at]).replace(',', '').strip())
                weight = market_value / total_fund_value * 100 if market_value >= 0 else None
            except (TypeError, ValueError):
                weight = None
        if len(isin) != 12 or not isin.isalnum() or weight is None:
            continue
        holdings[isin] = holdings.get(isin, 0.0) + weight

    if not holdings:
        classification_note = ' Equity rows could not be identified.' if not saw_equity_classification and equity_context is None else ''
        raise ProviderError(f'No ISIN equity holdings found for {fund_name}.{classification_note}')
    return holdings


def calculate_overlap(holdings_a: dict[str, float], holdings_b: dict[str, float]) -> float:
    return sum(min(holdings_a[isin], holdings_b[isin]) for isin in holdings_a.keys() & holdings_b.keys())


def analyze_holdings_overlap(scheme_codes: list[str]) -> dict:
    if len(scheme_codes) < 2:
        return {'portfolio_month': None, 'funds': [], 'pairs': [], 'highest_pair': None, 'available': False}
    try:
        latest_records = fetch_amfi_latest()
    except ProviderError:
        return {
            'portfolio_month': None,
            'funds': [{'scheme_code': str(code), 'available': False, 'reason': 'AMC lookup unavailable'} for code in scheme_codes],
            'pairs': [],
            'highest_pair': None,
            'available': False,
        }
    record_by_code = {str(row.get('scheme_code')): row for row in latest_records}
    fund_results = []
    links_by_code: dict[str, list[dict[str, str]]] = {}
    source_by_code: dict[str, dict] = {}

    for code in scheme_codes:
        record = record_by_code.get(str(code))
        if not record:
            fund_results.append({'scheme_code': str(code), 'available': False, 'reason': 'Fund is missing from the latest AMFI scheme list'})
            continue
        amc_name = record.get('amc') or ''
        if _is_debt_fund(record):
            fund_results.append({
                'scheme_code': str(code),
                'scheme_name': record.get('scheme_name'),
                'amc': amc_name,
                'available': False,
                'reason': 'Overlap not applicable for debt funds',
            })
            continue
        source = AMC_SOURCES.get(amc_name)
        if not source:
            fund_results.append({'scheme_code': str(code), 'scheme_name': record.get('scheme_name'), 'amc': amc_name, 'available': False, 'reason': 'Overlap not available for this AMC'})
            continue
        try:
            links = _monthly_files_for_fund(source, record.get('scheme_name') or '')
            if not links:
                raise ProviderError('No monthly file found for the selected fund')
            links_by_code[str(code)] = links
            source_by_code[str(code)] = source
            fund_results.append({'scheme_code': str(code), 'scheme_name': record.get('scheme_name'), 'amc': amc_name, 'available': False, 'reason': 'Waiting for a common portfolio month'})
        except ProviderError as exc:
            logger.warning('Portfolio link lookup failed for AMC %s: %s', amc_name, exc)
            fund_results.append({'scheme_code': str(code), 'scheme_name': record.get('scheme_name'), 'amc': amc_name, 'available': False, 'reason': 'Overlap unavailable right now'})

    supported_codes = list(links_by_code)
    common_month: str | None = None
    if supported_codes:
        common_months = set(link['month'] for link in links_by_code[supported_codes[0]])
        for code in supported_codes[1:]:
            common_months.intersection_update(link['month'] for link in links_by_code[code])
        if common_months:
            common_month = max(common_months)

    holdings_by_code: dict[str, dict[str, float]] = {}
    if common_month:
        downloaded: dict[str, bytes] = {}
        for code in supported_codes:
            source = source_by_code[code]
            link = next((item for item in links_by_code[code] if item['month'] == common_month), None)
            if not link:
                continue
            try:
                if link['url'] not in downloaded:
                    downloaded[link['url']] = _download_cached(source['key'], common_month, link['url'])
                holdings_by_code[code] = _read_equity_holdings(downloaded[link['url']], link['url'], record_by_code[code].get('scheme_name') or '', source['parser'])
                fund = next(item for item in fund_results if item['scheme_code'] == code)
                fund.update({'available': True, 'reason': None, 'portfolio_month': common_month, 'holding_count': len(holdings_by_code[code])})
            except Exception as exc:
                logger.warning('Portfolio parse failed for scheme %s: %s', code, exc)
                fund = next(item for item in fund_results if item['scheme_code'] == code)
                fund.update({'available': False, 'reason': 'Overlap unavailable right now'})
    else:
        for fund in fund_results:
            if fund.get('reason') == 'Waiting for a common portfolio month':
                fund['reason'] = 'Overlap unavailable right now'

    pairs = []
    for left_index, left_code in enumerate(scheme_codes):
        for right_code in scheme_codes[left_index + 1:]:
            left_holdings = holdings_by_code.get(str(left_code))
            right_holdings = holdings_by_code.get(str(right_code))
            if left_holdings is None or right_holdings is None:
                continue
            left_record = record_by_code[str(left_code)]
            right_record = record_by_code[str(right_code)]
            pairs.append({
                'left': {'scheme_code': str(left_code), 'scheme_name': left_record.get('scheme_name')},
                'right': {'scheme_code': str(right_code), 'scheme_name': right_record.get('scheme_name')},
                'overlap_pct': calculate_overlap(left_holdings, right_holdings),
            })

    highest_pair = max(pairs, key=lambda pair: pair['overlap_pct'], default=None)
    return {
        'portfolio_month': common_month,
        'funds': fund_results,
        'pairs': pairs,
        'highest_pair': highest_pair,
        'available': highest_pair is not None,
    }
