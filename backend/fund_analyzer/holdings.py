from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from io import BytesIO
from threading import Lock
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlsplit

import pandas as pd
import requests
from django.core.cache import cache

from .providers import HEADERS, ProviderError, fetch_amfi_latest, fetch_url

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
    'SBI Mutual Fund': {
        'key': 'sbi',
        'url': 'https://www.sbimf.com/portfolios',
        'parser': 'sbi_monthly_excel',
    },
}

PORTFOLIO_CACHE_SECONDS = 24 * 60 * 60
PAGE_CACHE_SECONDS = 60 * 60
PAGE_ERROR_CACHE_SECONDS = 5 * 60
PORTFOLIO_LOOKBACK_MONTHS = 6
PARSED_HOLDINGS_CACHE_SECONDS = 180 * 24 * 60 * 60
PORTFOLIO_CACHE_MAX_BYTES = 128 * 1024 * 1024
IMPORTED_HOLDINGS_CACHE_SECONDS = 70 * 24 * 60 * 60
_download_lock = Lock()
_portfolio_file_cache: dict[tuple[str, str], tuple[datetime, dict[str, bytes]]] = {}
SBI_PORTFOLIO_LIST_URL = 'https://www.sbimf.com/ajaxcall/CMS/GetSchemePortfolioSheets'
HDFC_PUBLIC_FILE_ROOT = 'https://files.hdfcfund.com/s3fs-public/'
# Verified public Excel filename for the AMFI scheme; the workbook's own name
# and reporting date are still validated before any holdings are used.
HDFC_PUBLIC_FILE_NAMES = {'hdfc flexi cap fund': 'HDFC Flexi Cap Fund'}
PPFAS_SCHEME_FILE_PREFIXES = {
    'parag parikh flexi cap fund': 'PPFCF_',
    'parag parikh large cap fund': 'PPLCF_',
    'parag parikh elss tax saver fund': 'PPTSF_',
    'parag parikh conservative hybrid fund': 'PPCHF_',
    'parag parikh dynamic asset allocation fund': 'PPDAAF_',
    'parag parikh arbitrage fund': 'PPAF_',
    'parag parikh liquid fund': 'PPLF_',
}


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


def _portfolio_date(month: str) -> str:
    first = date.fromisoformat(f'{month}-01')
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (next_month - timedelta(days=1)).isoformat()


def _recent_portfolio_months() -> set[str]:
    cursor = date.today().replace(day=1) - timedelta(days=1)
    months = set()
    for _ in range(PORTFOLIO_LOOKBACK_MONTHS):
        months.add(cursor.strftime('%Y-%m'))
        cursor = cursor.replace(day=1) - timedelta(days=1)
    return months


def _amc_directory_name(amc_name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', amc_name.lower()).strip('-')


def _import_index_key(amc_name: str, scheme_code: str) -> str:
    return f'fund-analyzer:portfolio-import:index:{_amc_directory_name(amc_name)}:{scheme_code}'


def _imported_links(amc_name: str, scheme_code: str) -> list[dict[str, str]]:
    return cache.get(_import_index_key(amc_name, scheme_code)) or []


def _parsed_index_key(scheme_code: str) -> str:
    return f'fund-analyzer:portfolio-parsed:index:{scheme_code}'


def _parsed_links(scheme_code: str) -> list[dict[str, str]]:
    return cache.get(_parsed_index_key(scheme_code)) or []


def _cache_parsed_holdings(scheme_code: str, reporting_date: str, holdings: dict[str, float], url: str) -> None:
    month = reporting_date[:7]
    cache_key = f'fund-analyzer:portfolio-parsed:{scheme_code}:{month}'
    link = {'url': url, 'cache_key': cache_key, 'month': month, 'portfolio_date': reporting_date, 'cached': True}
    try:
        cache.set(cache_key, {'holdings': holdings, 'portfolio_date': reporting_date}, timeout=PARSED_HOLDINGS_CACHE_SECONDS)
        existing = cache.get(_parsed_index_key(scheme_code)) or []
        links = [link, *(item for item in existing if item.get('month') != month)]
        links.sort(key=lambda item: item['month'], reverse=True)
        cache.set(_parsed_index_key(scheme_code), links[:PORTFOLIO_LOOKBACK_MONTHS], timeout=PARSED_HOLDINGS_CACHE_SECONDS)
    except Exception:
        logger.exception('Parsed portfolio cache write failed for scheme %s', scheme_code)


def _normalise_name(value: str) -> str:
    text = re.sub(r'\b(direct|regular|growth|option|plan|idcw|reinvestment|reinvest|dividend)\b', ' ', value, flags=re.I)
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


def _is_debt_fund(record: dict) -> bool:
    category = re.sub(r'\s+', ' ', str(record.get('category') or '')).strip().lower()
    return category.startswith('debt scheme') or category.startswith('debt fund')


def _overlap_debug_record(code: str, record: dict | None = None, *, error: str | None = None) -> dict[str, Any]:
    """Create a stable, JSON-serialisable diagnostic record for the overlap endpoint."""
    record = record or {}
    amc_name = record.get('amc') or None
    return {
        'scheme_code': str(code),
        'scheme_name': record.get('scheme_name'),
        'category': record.get('category'),
        'amc': amc_name,
        'amc_name': amc_name,
        'amc_in_sources': bool(amc_name and amc_name in AMC_SOURCES),
        'monthly_links_found': 0,
        'months_found': [],
        'chosen_common_month': None,
        'matched_sheet_name': None,
        'parse_result': None,
        'attempted_months': [],
        'errors_by_month': {},
        'error': error,
    }


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
    if parser_key == 'sbi_monthly_excel':
        return 'monthly portfolio' in combined or 'monthly-portfolio' in combined
    return False


def _sbi_monthly_links() -> list[dict[str, str]]:
    """SBI publishes the workbook links through the public portfolios page's POST feed."""
    months = []
    cursor = date.today().replace(day=1) - timedelta(days=1)
    for _ in range(PORTFOLIO_LOOKBACK_MONTHS):
        months.append(cursor)
        cursor = cursor.replace(day=1) - timedelta(days=1)

    def fetch_month(month_end: date) -> list[dict[str, str]]:
        response = requests.post(
            SBI_PORTFOLIO_LIST_URL,
            json={
                'FundId': 0,
                'PSYear': str(month_end.year),
                'PSMonth': month_end.strftime('%B'),
                'PSFrequency': 'Monthly',
            },
            headers={**HEADERS, 'Content-Type': 'application/json;charset=utf-8'},
            timeout=(3, 10),
        )
        response.raise_for_status()
        parser = _PortfolioLinks()
        parser.feed(response.text)
        found = {}
        for item in parser.links:
            url = urljoin('https://www.sbimf.com/portfolios', item['href'].strip())
            title = re.sub(r'\s+', ' ', item['text']).strip()
            if not _candidate_link('sbi_monthly_excel', title, url):
                continue
            month = _month_in_text(f'{title} {url}')
            if month != month_end.strftime('%Y-%m'):
                continue
            found[url] = {
                'url': url,
                'text': title,
                'month': month,
                'portfolio_date': month_end.isoformat(),
            }
        return list(found.values())

    links = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(fetch_month, month) for month in months]
        for future in futures:
            try:
                links.extend(future.result())
            except (requests.RequestException, ValueError) as exc:
                logger.warning('SBI monthly portfolio listing unavailable: %s', exc)
    if not links:
        raise ProviderError('SBI monthly portfolio listing unavailable')
    return links


def _load_page_links(amc_key: str, page_url: str, parser_key: str) -> list[dict[str, str]]:
    cache_key = f'fund-analyzer:portfolio-page:{amc_key}'
    try:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    except Exception:
        logger.exception('Portfolio page cache read failed for %s', amc_key)

    try:
        recent_error = cache.get(f'{cache_key}:error')
        if recent_error:
            stale = cache.get(f'{cache_key}:stale')
            if stale:
                return stale
            raise ProviderError(recent_error)
    except ProviderError:
        raise
    except Exception:
        logger.exception('Portfolio page error cache read failed for %s', amc_key)

    try:
        if parser_key == 'sbi_monthly_excel':
            results = _sbi_monthly_links()
        else:
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
                    results.append({'url': href, 'text': text, 'month': month, 'portfolio_date': _portfolio_date(month)})
        if not results:
            raise ProviderError(f'No monthly portfolio files found for {amc_key}')
    except ProviderError as exc:
        try:
            cache.set(f'{cache_key}:error', str(exc), timeout=PAGE_ERROR_CACHE_SECONDS)
            stale = cache.get(f'{cache_key}:stale')
            if stale:
                logger.warning('Using cached monthly portfolio links after %s page failed', amc_key)
                return stale
        except Exception:
            logger.exception('Stale portfolio page cache read failed for %s', amc_key)
        raise
    try:
        cache.set(cache_key, results, timeout=PAGE_CACHE_SECONDS)
        cache.set(f'{cache_key}:stale', results, timeout=PARSED_HOLDINGS_CACHE_SECONDS)
        cache.delete(f'{cache_key}:error')
    except Exception:
        logger.exception('Portfolio page cache write failed for %s', amc_key)
    return results


def _monthly_files_for_fund(source: dict, fund_name: str) -> list[dict[str, str]]:
    try:
        links = _load_page_links(source['key'], source['url'], source['parser'])
    except ProviderError as exc:
        public_name = HDFC_PUBLIC_FILE_NAMES.get(_normalise_name(fund_name))
        if source['parser'] != 'hdfc_xlsx_by_scheme' or not public_name:
            raise
        # The HDFC listing can reject server requests while its separate public
        # file host permits ordinary GETs. No cookies or access workarounds.
        links = []
        for month in sorted(_recent_portfolio_months(), reverse=True):
            reporting_date = date.fromisoformat(_portfolio_date(month))
            folder = (reporting_date + timedelta(days=1)).strftime('%Y-%m')
            filename = f"Monthly {public_name} - {reporting_date.day} {reporting_date.strftime('%B %Y')}.xlsx"
            links.append({
                'url': urljoin(HDFC_PUBLIC_FILE_ROOT, f'{folder}/{quote(filename)}'),
                'text': filename, 'month': month, 'listing_error': str(exc),
            })
        logger.warning('HDFC listing failed; checking its public Excel file host: %s', exc)
        return links
    if source['parser'] == 'ppfas_consolidated_excel':
        prefix = PPFAS_SCHEME_FILE_PREFIXES.get(_normalise_name(fund_name))
        if prefix:
            scheme_links = [link for link in links if urlsplit(link['url']).path.rsplit('/', 1)[-1].upper().startswith(prefix)]
            if scheme_links:
                return scheme_links
        return [link for link in links if link['text'].lower() == 'consolidated']
    if source['parser'] in ('hdfc_xlsx_by_scheme', 'sbi_monthly_excel'):
        links = [link for link in links if _scheme_link_matches(f"{link['text']} {urlsplit(link['url']).path}", fund_name)]
        if source['parser'] == 'sbi_monthly_excel' and not links:
            links = [link for link in _load_page_links(source['key'], source['url'], source['parser']) if 'all schemes' in link['text'].lower()]
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
    has_holdings_header = any(
        'isin' in ' '.join(str(value).lower() for value in frame.iloc[row_index].tolist())
        for row_index in range(min(len(frame), 80))
    )
    if not has_holdings_header:
        return 0
    wanted = _normalise_name(fund_name)
    sheet_title = _normalise_name(sheet_name)
    if wanted and wanted in sheet_title:
        return 3
    context = frame.iloc[:25, :12].fillna('').astype(str).to_numpy().ravel()
    candidate = _normalise_name(' '.join([sheet_name, *context]))
    if wanted and wanted in candidate:
        return 2
    if candidate and candidate in wanted and len(candidate) >= max(12, int(len(wanted) * 0.7)):
        return 1
    return 0


def _reporting_date_from_frame(frame: pd.DataFrame) -> str | None:
    patterns = (
        '%d %B %Y', '%d %b %Y', '%B %d %Y', '%b %d %Y',
        '%d %B %y', '%d %b %y', '%B %d %y', '%b %d %y',
    )
    for row in frame.iloc[:40].itertuples(index=False, name=None):
        values = [value for value in row if not pd.isna(value) and str(value).strip()]
        context = ' '.join(str(value) for value in values)
        if not re.search(r'(?i)(portfolio|statement|holdings|as\s+on|as\s+at|month\s+ended)', context):
            continue
        for value in values:
            if isinstance(value, (datetime, date)):
                return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
        for candidate in re.findall(
            r'(?i)\b(?:\d{1,2}[\s/-]+[A-Za-z]{3,9}[\s/-]+\d{2,4}|'
            r'[A-Za-z]{3,9}[\s/-]+\d{1,2},?[\s/-]+\d{2,4}|\d{4}-\d{2}-\d{2})\b',
            context,
        ):
            cleaned = re.sub(r'[,/-]', ' ', candidate).strip()
            if re.fullmatch(r'\d{4}\s+\d{2}\s+\d{2}', cleaned):
                cleaned = candidate
                try:
                    return date.fromisoformat(cleaned).isoformat()
                except ValueError:
                    continue
            for pattern in patterns:
                try:
                    return datetime.strptime(cleaned, pattern).date().isoformat()
                except ValueError:
                    continue
    return None


def _column_index(headers: list[str], candidates: tuple[str, ...]) -> int | None:
    for index, header in enumerate(headers):
        compact = re.sub(r'[^a-z0-9%]+', ' ', header.lower()).strip()
        if any(candidate in compact for candidate in candidates):
            return index
    return None


def _is_equity_section(text: str) -> bool | None:
    value = re.sub(r'[^a-z]+', ' ', text.lower())
    if re.search(r'\b(reits?|invits?|derivatives?)\b', value) or any(token in value for token in (
        'real estate investment trust', 'infrastructure investment trust', 'mutual fund units',
    )):
        return False
    if value.strip() in ('equity', 'equities'):
        return True
    if any(token in value for token in ('equity and equity related', 'equity equity related', 'equity related instruments', 'equity shares', 'equity instruments')):
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
    if suffix.endswith('.csv'):
        for encoding in ('utf-8-sig', 'cp1252'):
            try:
                frame = pd.read_csv(BytesIO(payload), header=None, dtype=object, encoding=encoding)
                return {'Portfolio': frame}, {'Portfolio': []}
            except UnicodeDecodeError:
                continue
        raise ProviderError('Portfolio CSV encoding was not recognised')
    # Some AMCs publish an OOXML workbook with a legacy .xls filename.
    if suffix.endswith('.xls') and not payload.startswith(b'PK\x03\x04'):
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


def _read_equity_holdings(
    payload: bytes,
    url: str,
    fund_name: str,
    parser_key: str,
    diagnostics: dict[str, Any] | None = None,
    workbook: tuple[dict[str, pd.DataFrame], dict[str, list[list[str]]]] | None = None,
) -> dict[str, float]:
    suffix = urlsplit(url).path.lower()
    try:
        sheets, formats_by_sheet = workbook if workbook is not None else _workbook_sheets(payload, suffix)
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
    if diagnostics is not None:
        diagnostics['matched_sheet_name'] = sheet_name
        diagnostics['reporting_date'] = _reporting_date_from_frame(frame)

    header_candidates = []
    for row_index in range(min(len(frame), 80)):
        row_headers = [str(value).strip() if not pd.isna(value) else '' for value in frame.iloc[row_index].tolist()]
        normalised = [re.sub(r'[^a-z0-9%]+', ' ', value.lower()).strip() for value in row_headers]
        candidate_isin = _column_index(normalised, ('isin',))
        candidate_weight = _column_index(normalised, ('% to nav', 'percent to nav', '% of net assets', 'percentage to nav', 'percentage of net assets', '% to aum', 'percentage to aum', '% of aum'))
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
    if sum(holdings.values()) > 101:
        raise ProviderError(f'Equity holdings weights exceed 100% for {fund_name}')
    if diagnostics is not None:
        diagnostics['parse_result'] = {'status': 'ok', 'holding_count': len(holdings)}
    return holdings


def calculate_overlap(holdings_a: dict[str, float], holdings_b: dict[str, float]) -> float:
    return sum(min(holdings_a[isin], holdings_b[isin]) for isin in holdings_a.keys() & holdings_b.keys())


def import_portfolio_holdings(scheme_code: str, portfolio_date: str, filename: str, payload: bytes, source_url: str = '') -> dict[str, Any]:
    """Validate a real disclosure file and cache its parsed holdings for monthly use."""
    code = str(scheme_code)
    if not filename.lower().endswith(('.xlsx', '.xls', '.csv')):
        raise ProviderError('Upload an Excel or CSV portfolio disclosure file')
    if not payload or len(payload) > 15 * 1024 * 1024:
        raise ProviderError('Portfolio disclosure file must be between 1 byte and 15 MB')
    try:
        reporting_date = date.fromisoformat(portfolio_date)
    except ValueError as exc:
        raise ProviderError('portfolio_date must be YYYY-MM-DD') from exc
    if reporting_date > date.today():
        raise ProviderError('Portfolio reporting date cannot be in the future')
    record = next((item for item in fetch_amfi_latest() if str(item.get('scheme_code')) == code), None)
    if record is None:
        raise ProviderError('Scheme code was not found in AMFI NAV data')
    if _is_debt_fund(record):
        raise ProviderError('Overlap not applicable for debt funds')
    amc_name = record.get('amc') or ''
    if not amc_name:
        raise ProviderError('AMC name was not found in AMFI NAV data')
    diagnostics: dict[str, Any] = {}
    holdings = _read_equity_holdings(payload, filename, record.get('scheme_name') or '', 'import_by_code', diagnostics)
    actual_date = diagnostics.get('reporting_date')
    if not actual_date:
        raise ProviderError('Portfolio reporting date was not found inside the disclosure file')
    if actual_date != reporting_date.isoformat():
        raise ProviderError(f'Portfolio file reports {actual_date}, not {reporting_date.isoformat()}')
    cache_key = f'fund-analyzer:portfolio-import:{_amc_directory_name(amc_name)}:{code}:{reporting_date.isoformat()}'
    link = {
        'url': f'cache://{_amc_directory_name(amc_name)}/{code}/{reporting_date.isoformat()}',
        'cache_key': cache_key,
        'text': filename,
        'month': reporting_date.strftime('%Y-%m'),
        'portfolio_date': reporting_date.isoformat(),
        'imported': True,
    }
    try:
        cache.set(cache_key, {'holdings': holdings, 'source_url': source_url}, timeout=IMPORTED_HOLDINGS_CACHE_SECONDS)
        index_key = _import_index_key(amc_name, code)
        existing = cache.get(index_key) or []
        links = [link, *(item for item in existing if item.get('portfolio_date') != link['portfolio_date'])]
        links.sort(key=lambda item: item['portfolio_date'], reverse=True)
        cache.set(index_key, links[:6], timeout=IMPORTED_HOLDINGS_CACHE_SECONDS)
        if cache.get(cache_key) is None:
            raise ProviderError('Portfolio holdings cache did not retain the import')
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError('Portfolio holdings cache is unavailable') from exc
    return {
        'scheme_code': code,
        'scheme_name': record.get('scheme_name'),
        'amc': amc_name,
        'portfolio_date': reporting_date.isoformat(),
        'holding_count': len(holdings),
    }


def _empty_highest_overlap(total_pairs: int) -> dict[str, Any]:
    return {
        'available': False,
        'percentage': None,
        'fund_a_code': None,
        'fund_a_name': None,
        'fund_b_code': None,
        'fund_b_name': None,
        'portfolio_month': None,
        'portfolio_date': None,
        'pairs_different_months': False,
        'partial_coverage': False,
        'compared_pairs': 0,
        'total_pairs': total_pairs,
        'message': 'Portfolio holdings unavailable',
    }


def analyze_holdings_overlap(scheme_codes: list[str]) -> dict:
    if len(scheme_codes) < 2:
        return {
            'portfolio_month': None,
            'funds': [],
            'pairs': [],
            'pairs_different_months': False,
            'highest_pair': None,
            'highest_overlap': _empty_highest_overlap(0),
            'available': False,
            'debug': [_overlap_debug_record(str(code), error='At least two funds are required for overlap comparison') for code in scheme_codes],
        }
    try:
        latest_records = fetch_amfi_latest()
    except ProviderError:
        debug = [_overlap_debug_record(str(code), error='AMC lookup unavailable') for code in scheme_codes]
        logger.debug('Holdings overlap diagnostics: %s', debug)
        return {
            'portfolio_month': None,
            'funds': [{'scheme_code': str(code), 'available': False, 'reason': 'AMC lookup unavailable'} for code in scheme_codes],
            'pairs': [],
            'pairs_different_months': False,
            'highest_pair': None,
            'highest_overlap': _empty_highest_overlap(len(scheme_codes) * (len(scheme_codes) - 1) // 2),
            'available': False,
            'debug': debug,
        }
    record_by_code = {str(row.get('scheme_code')): row for row in latest_records}
    recent_months = _recent_portfolio_months()
    fund_results = []
    debug_by_code: dict[str, dict[str, Any]] = {}
    links_by_code: dict[str, list[dict[str, str]]] = {}
    source_by_code: dict[str, dict] = {}

    for code in scheme_codes:
        code = str(code)
        record = record_by_code.get(code)
        debug = _overlap_debug_record(code, record)
        debug_by_code[code] = debug
        if not record:
            debug['error'] = 'Fund is missing from the latest AMFI scheme list'
            fund_results.append({'scheme_code': code, 'available': False, 'reason': debug['error']})
            continue
        amc_name = record.get('amc') or ''
        if _is_debt_fund(record):
            debug['parse_result'] = {'status': 'skipped', 'reason': 'debt_fund_restriction'}
            debug['error'] = 'Overlap not applicable for debt funds'
            fund_results.append({
                'scheme_code': code,
                'scheme_name': record.get('scheme_name'),
                'amc': amc_name,
                'available': False,
                'reason': debug['error'],
            })
            continue
        try:
            imported_links = _imported_links(amc_name, code)
            parsed_links = _parsed_links(code)
        except Exception as exc:
            logger.warning('Portfolio holdings cache unavailable for %s: %s', code, exc)
            imported_links = []
            parsed_links = []
        source = AMC_SOURCES.get(amc_name)
        if not source and not imported_links and not parsed_links:
            debug['error'] = 'Overlap not available for this AMC'
            fund_results.append({'scheme_code': code, 'scheme_name': record.get('scheme_name'), 'amc': amc_name, 'available': False, 'reason': debug['error']})
            continue
        remote_links = []
        try:
            if source:
                remote_links = _monthly_files_for_fund(source, record.get('scheme_name') or '')
                listing_errors = [link['listing_error'] for link in remote_links if link.get('listing_error')]
                if listing_errors:
                    debug['error'] = listing_errors[0]
        except ProviderError as exc:
            logger.warning('Portfolio link lookup failed for AMC %s: %s', amc_name, exc)
            debug['error'] = str(exc)
        try:
            links = [link for link in [*imported_links, *parsed_links, *remote_links] if link.get('month') in recent_months]
            if not links:
                raise ProviderError('No monthly portfolio links or cached holdings in the lookback period')
            months = sorted({str(link.get('month')) for link in links if link.get('month')})
            debug.update({'monthly_links_found': len(links), 'months_found': months})
            links_by_code[str(code)] = links
            source_by_code[str(code)] = source or {'key': _amc_directory_name(amc_name), 'parser': 'import_by_code'}
            fund_results.append({'scheme_code': code, 'scheme_name': record.get('scheme_name'), 'amc': amc_name, 'available': False, 'reason': 'Waiting for a common portfolio month'})
        except ProviderError as exc:
            debug['error'] = debug['error'] or str(exc)
            fund_results.append({'scheme_code': code, 'scheme_name': record.get('scheme_name'), 'amc': amc_name, 'available': False, 'reason': 'Overlap unavailable right now'})

    supported_codes = list(links_by_code)
    candidate_months = sorted((
        month for month in {link['month'] for links in links_by_code.values() for link in links}
        if sum(any(link['month'] == month for link in links_by_code[code]) for code in supported_codes) >= 2
    ), reverse=True)
    valid_by_month: dict[str, dict[str, dict[str, Any]]] = {}
    downloaded: dict[str, bytes] = {}
    workbooks: dict[str, tuple[dict[str, pd.DataFrame], dict[str, list[list[str]]]]] = {}
    global_month: str | None = None

    for month in candidate_months:
        month_results: dict[str, dict[str, Any]] = {}
        for code in supported_codes:
            links = [link for link in links_by_code[code] if link['month'] == month]
            if not links:
                continue
            debug = debug_by_code[code]
            debug['attempted_months'].append(month)
            for link in links:
                try:
                    if link.get('imported') or link.get('cached'):
                        cached = cache.get(link['cache_key'])
                        if not cached or not cached.get('holdings'):
                            raise ProviderError('Cached monthly holdings expired')
                        holdings = cached['holdings']
                        reporting_date = cached.get('portfolio_date') or link.get('portfolio_date')
                        debug['parse_result'] = {
                            'status': 'ok', 'holding_count': len(holdings),
                            'source': 'monthly_import' if link.get('imported') else 'parsed_cache',
                        }
                    else:
                        source = source_by_code[code]
                        if link['url'] not in downloaded:
                            downloaded[link['url']] = _download_cached(source['key'], month, link['url'])
                        if link['url'] not in workbooks:
                            workbooks[link['url']] = _workbook_sheets(downloaded[link['url']], urlsplit(link['url']).path.lower())
                        holdings = _read_equity_holdings(
                            downloaded[link['url']], link['url'],
                            record_by_code[code].get('scheme_name') or '', source['parser'],
                            debug, workbooks[link['url']],
                        )
                        reporting_date = debug.get('reporting_date')
                    if not reporting_date:
                        raise ProviderError('Portfolio reporting date was not found inside the disclosure file')
                    if reporting_date[:7] != month:
                        raise ProviderError(f'Portfolio file reports {reporting_date}, not {month}')
                    source_label = (debug.get('parse_result') or {}).get('source')
                    debug['parse_result'] = {
                        'status': 'ok', 'holding_count': len(holdings),
                        **({'source': source_label} if source_label else {}),
                    }
                    if link.get('cached') or link.get('imported'):
                        debug['matched_sheet_name'] = 'Cached holdings'
                    month_results[code] = {
                        'holdings': holdings, 'portfolio_date': reporting_date,
                        'matched_sheet_name': debug['matched_sheet_name'],
                        'source': source_label,
                    }
                    if not link.get('imported') and not link.get('cached'):
                        _cache_parsed_holdings(code, reporting_date, holdings, link['url'])
                    break
                except Exception as exc:
                    error = str(exc) or exc.__class__.__name__
                    logger.warning('Portfolio %s failed for scheme %s: %s', month, code, error)
                    debug['errors_by_month'].setdefault(month, []).append(error)
                    debug['error'] = error
                    debug['parse_result'] = {'status': 'error'}
        valid_by_month[month] = month_results
        if len(supported_codes) >= 2 and len(month_results) == len(supported_codes):
            global_month = month
            break

    for fund in fund_results:
        code = fund['scheme_code']
        if code not in links_by_code:
            continue
        best_month = global_month if global_month and code in valid_by_month[global_month] else next(
            (month for month in candidate_months if code in valid_by_month.get(month, {})), None,
        )
        if best_month:
            selected = valid_by_month[best_month][code]
            fund.update({
                'available': True, 'reason': None, 'portfolio_month': best_month,
                'portfolio_date': selected['portfolio_date'], 'holding_count': len(selected['holdings']),
            })
            debug_by_code[code]['chosen_common_month'] = best_month
            debug_by_code[code]['reporting_date'] = selected['portfolio_date']
            debug_by_code[code]['matched_sheet_name'] = selected['matched_sheet_name']
            debug_by_code[code]['parse_result'] = {
                'status': 'ok', 'holding_count': len(selected['holdings']),
                **({'source': selected['source']} if selected['source'] else {}),
            }
        else:
            fund['reason'] = 'Overlap unavailable right now'
            debug_by_code[code]['error'] = debug_by_code[code]['error'] or (
                'No valid common-month holdings in the lookback period'
                if candidate_months else 'No portfolio month shared with another selected fund'
            )

    pairs = []
    for left_index, left_code in enumerate(scheme_codes):
        for right_code in scheme_codes[left_index + 1:]:
            left_code, right_code = str(left_code), str(right_code)
            pair_month = global_month or next((
                month for month in candidate_months
                if left_code in valid_by_month.get(month, {}) and right_code in valid_by_month[month]
            ), None)
            if not pair_month:
                continue
            left_data = valid_by_month[pair_month][left_code]
            right_data = valid_by_month[pair_month][right_code]
            left_record = record_by_code[left_code]
            right_record = record_by_code[right_code]
            pairs.append({
                'left': {'scheme_code': left_code, 'scheme_name': left_record.get('scheme_name')},
                'right': {'scheme_code': right_code, 'scheme_name': right_record.get('scheme_name')},
                'overlap_pct': calculate_overlap(left_data['holdings'], right_data['holdings']),
                'portfolio_month': pair_month,
                'portfolio_date': left_data['portfolio_date'] if left_data['portfolio_date'] == right_data['portfolio_date'] else None,
            })

    highest_pair = max(pairs, key=lambda pair: pair['overlap_pct'], default=None)
    pair_months = {pair['portfolio_month'] for pair in pairs}
    pairs_different_months = len(pair_months) > 1
    selected_month = global_month or (next(iter(pair_months)) if len(pair_months) == 1 else None)
    rounded_pairs = [{**pair, 'overlap_pct': round(pair['overlap_pct'], 2)} for pair in pairs]
    if highest_pair is not None:
        highest_pair = {**highest_pair, 'overlap_pct': round(highest_pair['overlap_pct'], 2)}
    total_pairs = len(scheme_codes) * (len(scheme_codes) - 1) // 2
    unavailable_reasons = {fund.get('reason') for fund in fund_results if not fund.get('available')}
    if 'Overlap not applicable for debt funds' in unavailable_reasons:
        unavailable_message = 'Overlap not applicable for debt funds'
    elif 'Overlap not available for this AMC' in unavailable_reasons:
        unavailable_message = 'Overlap not available for this AMC'
    else:
        missing_names = [
            str(fund['scheme_name'])
            for fund in fund_results
            if not fund.get('available') and fund.get('scheme_name')
            and (fund['scheme_code'] not in links_by_code or debug_by_code[fund['scheme_code']]['attempted_months'])
        ]
        unavailable_message = (
            f"Monthly holdings unavailable for {', '.join(missing_names)}"
            if missing_names else 'No common monthly portfolio holdings available'
        )
    highest_overlap = {
        'available': highest_pair is not None,
        'percentage': round(highest_pair['overlap_pct'], 2) if highest_pair else None,
        'fund_a_code': highest_pair['left']['scheme_code'] if highest_pair else None,
        'fund_a_name': highest_pair['left']['scheme_name'] if highest_pair else None,
        'fund_b_code': highest_pair['right']['scheme_code'] if highest_pair else None,
        'fund_b_name': highest_pair['right']['scheme_name'] if highest_pair else None,
        'portfolio_month': highest_pair['portfolio_month'] if highest_pair else None,
        'portfolio_date': highest_pair['portfolio_date'] if highest_pair else None,
        'pairs_different_months': pairs_different_months,
        'partial_coverage': bool(highest_pair and len(pairs) < total_pairs),
        'compared_pairs': len(pairs),
        'total_pairs': total_pairs,
        'message': None if highest_pair else unavailable_message,
    }
    debug = [debug_by_code[str(code)] for code in scheme_codes]
    logger.debug('Holdings overlap diagnostics: %s', debug)
    return {
        'portfolio_month': selected_month,
        'funds': fund_results,
        'pairs': rounded_pairs,
        'pairs_different_months': pairs_different_months,
        'highest_pair': highest_pair,
        'highest_overlap': highest_overlap,
        'available': highest_pair is not None,
        'debug': debug,
    }
