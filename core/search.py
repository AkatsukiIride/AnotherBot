"""Web search with scoring, dedup, date extraction — no API key needed"""
import re
import asyncio
import httpx
from datetime import datetime, timedelta
from urllib.parse import quote

PAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# ── Date extraction ───────────────────────────────────────────

_DATE_PATTERNS = [
    (re.compile(r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?'), 'ymd'),
    (re.compile(r'(?:^|[^\d])(\d{1,2})[月\-/.](\d{1,2})日?(?:[^\d]|$)'), 'md'),
    (re.compile(r'(\d{4})[年\-/.](\d{1,2})月?'), 'ym'),
    (re.compile(r'(今天|昨天|明天|前天|后天|上周|本周|下周|本月|上月|下月|今年|去年|明年)'), 'relative'),
    (re.compile(r'(\d+)\s*(天|小时|分钟|周|个?月|年)\s*(前|后)'), 'relative_n'),
]

_RELATIVE_MAP = {
    '今天': 0, '昨天': -1, '明天': 1, '前天': -2, '后天': 2,
    '上周': -7, '本周': 0, '下周': 7,
    '本月': 0, '上月': -30, '下月': 30,
    '今年': 0, '去年': -365, '明年': 365,
}


def extract_dates(text: str, reference_date: datetime = None) -> list[dict]:
    """Extract date references from text with confidence scores."""
    if reference_date is None:
        reference_date = datetime.now()
    found = []
    for pattern, ptype in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            try:
                if ptype == 'ymd':
                    y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    if 1900 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
                        found.append({'date': datetime(y, m, d), 'source': match.group(0), 'confidence': 1.0})
                elif ptype == 'md':
                    m, d = int(match.group(1)), int(match.group(2))
                    if 1 <= m <= 12 and 1 <= d <= 31:
                        dt = datetime(reference_date.year, m, d)
                        if dt > reference_date + timedelta(days=180):
                            dt = datetime(reference_date.year - 1, m, d)
                        found.append({'date': dt, 'source': match.group(0), 'confidence': 0.6})
                elif ptype == 'ym':
                    y, m = int(match.group(1)), int(match.group(2))
                    if 1900 <= y <= 2100 and 1 <= m <= 12:
                        found.append({'date': datetime(y, m, 1), 'source': match.group(0), 'confidence': 0.5})
                elif ptype == 'relative':
                    delta = _RELATIVE_MAP.get(match.group(1), 0)
                    found.append({'date': reference_date + timedelta(days=delta), 'source': match.group(0), 'confidence': 0.4})
                elif ptype == 'relative_n':
                    n = int(match.group(1))
                    unit = match.group(2)
                    direction = match.group(3)
                    mult = {'小时': 1/24, '分钟': 1/1440, '天': 1, '周': 7, '个月': 30, '个?月': 30, '年': 365}.get(unit, 1)
                    delta = n * mult * (-1 if direction == '前' else 1)
                    found.append({'date': reference_date + timedelta(days=delta), 'source': match.group(0), 'confidence': 0.4})
            except (ValueError, OverflowError):
                continue
    return found


# ── Text extraction ───────────────────────────────────────────

def _extract_text(html: str, max_chars: int = 3000) -> str:
    """Extract readable text from HTML."""
    html = re.sub(r'<(script|style|noscript|header|footer|nav|aside)[^>]*>.*?</\1>',
                  '', html, flags=re.DOTALL)
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    lines = []
    for l in text.split('\n'):
        s = l.strip()
        if len(s) < 10:
            if re.search(r'\d{4}|发布时间|来源|作者|发表于|更新于', s):
                lines.append(s)
            continue
        if re.match(r'^[\s\d\.\,\|\-\+\=\>\<\(\)\[\]\{\}\/\*\$#@!~]+$', s):
            continue
        lines.append(s)
    result = '\n'.join(lines)
    if len(result) > max_chars:
        result = result[:max_chars] + "..."
    return result


# ── Page fetching ─────────────────────────────────────────────

async def fetch_page(url: str, max_retries: int = 1) -> str:
    """Fetch webpage with retry. Returns extracted text or empty string."""
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, max_redirects=5) as client:
                resp = await client.get(url, headers=PAGE_HEADERS)
                resp.raise_for_status()
                text = _extract_text(resp.text)
                if text.strip():
                    return text
                if attempt < max_retries:
                    continue
        except (httpx.HTTPError, httpx.TimeoutException):
            if attempt < max_retries:
                continue
        except Exception:
            return ""
    return ""


# ── Search ────────────────────────────────────────────────────

async def search_web(query: str, max_results: int = 5) -> list[dict]:
    """Search Baidu, return structured results with rank."""
    try:
        from baidusearch.baidusearch import search
        results = search(query, num_results=max_results)
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""),
             "abstract": r.get("abstract", ""), "rank": r.get("rank", 0)}
            for r in results if r.get("title")
        ]
    except Exception:
        return []


# ── Scoring ───────────────────────────────────────────────────

def score_result(result: dict, query_terms: list[str], reference_date: datetime) -> tuple[float, dict]:
    """Score a result by relevance (40%) + recency (35%) + authority (25%)."""
    title_lower = result.get('title', '').lower()
    abstract_lower = result.get('abstract', '').lower()
    total_terms = len(query_terms) or 1
    matches = sum(2.0 if t in title_lower else 0.0 for t in query_terms)
    matches += sum(0.5 if t in abstract_lower else 0.0 for t in query_terms)
    max_possible = total_terms * 2.5
    relevance = min(matches / max_possible, 1.0) if max_possible > 0 else 0.0

    text = f"{result.get('title','')} {result.get('abstract','')}"
    dates = extract_dates(text, reference_date)
    recency = 0.5
    if dates:
        closest_days = min(abs((d['date'] - reference_date).days) for d in dates)
        recency = max(0.0, 1.0 - (closest_days / 365) ** 0.5)
    rank = result.get('rank', 99)
    authority = max(0.0, 1.0 - (rank - 1) / 20)

    total = relevance * 0.40 + recency * 0.35 + authority * 0.25
    return total, {'relevance': round(relevance, 3), 'recency': round(recency, 3),
                   'authority': round(authority, 3), 'dates': dates, 'total': round(total, 3)}


# ── Deduplication ─────────────────────────────────────────────

def _char_jaccard(a: str, b: str) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb: return 1.0
    if not sa or not sb: return 0.0
    return len(sa & sb) / len(sa | sb)


def _extract_domain(url: str) -> str:
    m = re.search(r'://(?:www\.)?([^/]+)', url)
    if not m: return ''
    parts = m.group(1).split('.')
    return '.'.join(parts[-2:]) if len(parts) > 2 else m.group(1)


def _text_overlap_ratio(a: str, b: str) -> float:
    wa, wb = set(a.lower().split()), set(b.lower().split())
    union = wa | wb
    return len(wa & wb) / len(union) if union else 0.0


_JUNK_TITLES = {'听', '问题分析中', '为您推荐', '相关结果'}
_JUNK_PREFIXES = ('总结全网', '大家还在搜', '相关搜索', '搜索', '为您推荐')


def _is_quality_result(r: dict) -> bool:
    """Filter out Baidu internal/junk results."""
    title = r.get('title', '').strip()
    abstract = r.get('abstract', '').strip()
    # Must have a meaningful title
    if not title or title in _JUNK_TITLES:
        return False
    if any(title.startswith(p) for p in _JUNK_PREFIXES):
        return False
    # Must have some content (abstract or longer title)
    if len(title) < 4 and not abstract:
        return False
    return True


def deduplicate_results(results: list[dict]) -> list[dict]:
    """Remove near-duplicate results."""
    if len(results) <= 1:
        return results
    kept = []
    for r in results:
        is_dup = False
        for k in kept:
            if r.get('url') == k.get('url'): is_dup = True; break
            if _char_jaccard(r.get('title', ''), k.get('title', '')) > 0.8: is_dup = True; break
            rd, kd = _extract_domain(r.get('url', '')), _extract_domain(k.get('url', ''))
            if rd and rd == kd and _text_overlap_ratio(r.get('abstract', ''), k.get('abstract', '')) > 0.7:
                is_dup = True; break
        if not is_dup:
            kept.append(r)
    return kept


# ── Formatting ────────────────────────────────────────────────

def format_results_for_llm(results: list[dict], pages: list[str],
                           reference_date: datetime = None, max_chars_per: int = 2500) -> str:
    """Format results for LLM. Mixed mode: page content where available, abstract fallback."""
    if reference_date is None:
        reference_date = datetime.now()
    parts = []
    for i, r in enumerate(results):
        idx = i + 1
        title = r.get('title', '无标题')
        url = r.get('url', '')
        domain = _extract_domain(url)
        header = f"[{idx}] {title}"
        if domain:
            header += f"  ({domain})"
        parts.append(header)

        dates = r.get('_dates', None)
        if dates is None:
            dates = extract_dates(f"{title} {r.get('abstract','')}", reference_date)
        if dates:
            ds = [f"{d['date'].strftime('%Y-%m-%d')}(距今{(reference_date-d['date']).days}天)" for d in dates]
            parts.append(f"   日期: {', '.join(ds)}")

        if i < len(pages) and pages[i] and pages[i].strip():
            content = pages[i][:max_chars_per]
        else:
            abstract = r.get('abstract', '')
            content = f"[摘要] {abstract}" if abstract else "[无法获取内容]"
        parts.append(f"   {content}")
    return "\n\n".join(parts)


# ── Orchestration ─────────────────────────────────────────────

async def search_and_rank(query: str, max_results: int = 5, fetch_pages: int = 2,
                          reference_date: datetime = None) -> dict:
    """Full search pipeline: search → dedup → score → fetch → format-ready."""
    if reference_date is None:
        reference_date = datetime.now()

    results = await search_web(query, max_results=max_results)
    if not results:
        return {'results': [], 'pages': [], 'query_terms': [], 'reference_date': reference_date}

    # Filter junk results
    results = [r for r in results if _is_quality_result(r)]
    results = deduplicate_results(results)

    try:
        import jieba
        query_terms = list(jieba.cut(query))
    except ImportError:
        query_terms = query.split()

    for r in results:
        score, meta = score_result(r, query_terms, reference_date)
        r['_score'] = score
        r['_score_meta'] = meta
        r['_dates'] = meta.get('dates', [])

    results.sort(key=lambda r: r.get('_score', 0), reverse=True)

    pages: list[str] = []
    if fetch_pages > 0:
        tasks = [fetch_page(r['url']) for r in results[:fetch_pages]]
        pages = await asyncio.gather(*tasks)
        pages.extend([''] * (len(results) - len(pages)))

    return {'results': results, 'pages': pages, 'query_terms': query_terms, 'reference_date': reference_date}
