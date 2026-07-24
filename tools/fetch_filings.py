#!/usr/bin/env python3
"""财报下载工具 - 免登录下载美股 SEC EDGAR / 港股披露易 / 公司官网财报原件。

为 AI Berkshire stock-research skill 提供"原始财报归档"能力：把年报/季报
原件下载到 financial-report/{market}/{ticker}/raw/ 下，并维护 manifest.json，
支持"复用优先"（已有且哈希一致则跳过，仅补下缺失财年/季度）。

三个数据源均免登录、免付费：

  1. 美股 / 外国发行人 —— SEC EDGAR
     - ticker -> CIK 映射：https://www.sec.gov/files/company_tickers.json
     - 申报清单：https://data.sec.gov/submissions/CIK{cik}.json
     - 年报取 10-K（外国私人发行人取 20-F，如 TSM/TCEHY/NTES）
     - 季报取 10-Q
     - 文件下载：https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{primaryDoc}
     - SEC 要求 User-Agent 含联系方式，且 ≤10 请求/秒。

  2. 港股 —— 港交所披露易（hkexnews.hk）
     - 股票代码 -> 内部 stockId 映射：/ncms/script/eds/activestock_sehk_e.json
       （披露易用内部 id 而非股票代码做检索，例：00700 TENCENT -> i=7609）
     - 检索：POST /search/titlesearch.xhtml（JSF 表单，需先 GET 取 ViewState）
     - 年报取 headline 含 "Annual Report"/"年報" 的 PDF
     - 中期报告取 "Interim Report"/"中期報告"/"Interim Results"

  3. 公司官网 —— --ir-url / --ir-list 直接下载指定 PDF（兜底或补充一手原件）

用法（由 stock-research skill 自动调用）：
    python3 tools/fetch_filings.py 0700.HK --type annual --years 5
    python3 tools/fetch_filings.py AAPL --type all --years 5
    python3 tools/fetch_filings.py TSM --type annual
    python3 tools/fetch_filings.py 00700 --list
    python3 tools/fetch_filings.py 0700.HK --ir-url https://static.www.tencent.com/.../xxx.pdf
    python3 tools/fetch_filings.py 0700.HK --rebuild-manifest

依赖 requests（pip install requests）。
"""

import argparse
import hashlib
import html as html_lib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("错误：需要 requests（pip install requests）。")

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

DEFAULT_CACHE_ROOT = Path(
    "/Users/wujiaqi/workspace/finanace-data-ws/finanace-data/financial-report"
)

SEC_UA_EMAIL = os.environ.get("SEC_UA_EMAIL", "ai-berkshire-research@example.com")
SEC_USER_AGENT = f"ai-berkshire research ({SEC_UA_EMAIL})"
SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik_padded}.json"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"

HKEX_SEARCH_URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml"
HKEX_STOCK_MAP_URL = (
    "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_e.json"
)
HKEX_DOC_BASE = "https://www1.hkexnews.hk"

HTTP_TIMEOUT = 30
SEC_RATE_GAP = 0.12  # ~8 req/s，留余量

CST = timezone(timedelta(hours=8))


# --------------------------------------------------------------------------- #
# 通用辅助
# --------------------------------------------------------------------------- #

def now_iso():
    return datetime.now(CST).isoformat(timespec="seconds")


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_filename_part(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "", s)[:80]


def http_session(proxy: str = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": SEC_USER_AGENT})
    s.headers.update({"Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8"})
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    return s


def download_to(session: requests.Session, url: str, dest: Path,
                referer: str = None, headers: dict = None) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    hdrs = dict(headers or {})
    if referer:
        hdrs.setdefault("Referer", referer)
    with session.get(url, stream=True, timeout=HTTP_TIMEOUT, headers=hdrs) as r:
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} 下载失败: {url}")
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                if chunk:
                    fh.write(chunk)
    return dest.stat().st_size


# --------------------------------------------------------------------------- #
# manifest（复用优先）
# --------------------------------------------------------------------------- #

def manifest_path(raw_dir: Path) -> Path:
    return raw_dir / "manifest.json"


def load_manifest(raw_dir: Path) -> dict:
    mp = manifest_path(raw_dir)
    if mp.exists():
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"generated_at": now_iso(), "ticker": None, "files": []}


def save_manifest(raw_dir: Path, manifest: dict):
    manifest["generated_at"] = now_iso()
    manifest_path(raw_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def find_in_manifest(manifest: dict, ftype: str, period: str):
    for f in manifest.get("files", []):
        if f.get("type") == ftype and f.get("period") == period:
            return f
    return None


def record_file(manifest: dict, raw_dir: Path, ftype: str, filename: str,
                period: str, source: str, source_url: str, size_bytes: int,
                md5: str):
    entry = {
        "type": ftype,
        "filename": filename,
        "period": period,
        "source": source,
        "source_url": source_url,
        "size_bytes": size_bytes,
        "md5": md5,
        "downloaded_at": now_iso(),
    }
    files = manifest.setdefault("files", [])
    # 去重：同 type+period 覆盖
    for i, f in enumerate(files):
        if f.get("type") == ftype and f.get("period") == period:
            files[i] = entry
            return
    files.append(entry)


# --------------------------------------------------------------------------- #
# 市场识别
# --------------------------------------------------------------------------- #

def normalize_hk_code(ticker: str) -> str:
    """0700.HK / 00700 / 700 -> '00700'（5 位补零）。"""
    code = re.sub(r"\.HK$", "", ticker.strip(), flags=re.I)
    code = re.sub(r"[^0-9]", "", code)
    return code.zfill(5)


def detect_market(ticker: str) -> str:
    t = ticker.strip()
    if re.search(r"\.HK$", t, re.I):
        return "hongkong"
    if re.fullmatch(r"\d{4,5}(\.HK)?", t, re.I):
        return "hongkong"
    return "american"


# --------------------------------------------------------------------------- #
# SEC EDGAR
# --------------------------------------------------------------------------- #

def sec_cik_map(session: requests.Session) -> dict:
    """返回 {TICKER: cik_str(int)}。本地缓存 1 天。"""
    cache = Path("/tmp/.sec_tickers.json")
    if cache.exists() and (time.time() - cache.stat().st_mtime < 86400):
        data = json.loads(cache.read_text(encoding="utf-8"))
    else:
        r = session.get(SEC_TICKER_MAP_URL, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        cache.write_text(json.dumps(data), encoding="utf-8")
    out = {}
    for v in data.values():
        out[v["ticker"].upper()] = int(v["cik_str"])
    return out


def sec_list_filings(session: requests.Session, cik: int, years: int) -> list:
    """返回最近 years 年内的 10-K/20-F/10-Q 申报记录列表。

    每条：{form, filing_date, report_date, accession, primary_doc, description}
    """
    cik_padded = str(cik).zfill(10)
    r = session.get(
        SEC_SUBMISSIONS_URL.format(cik_padded=cik_padded), timeout=HTTP_TIMEOUT
    )
    r.raise_for_status()
    data = r.json()
    recent = data["filings"]["recent"]
    rows = []
    keys = recent.keys()
    n = len(recent["accessionNumber"])
    cutoff = datetime.now(CST) - timedelta(days=years * 366 + 30)

    def collect(arr):
        for i in range(len(arr["accessionNumber"])):
            form = arr["form"][i]
            if form not in ("10-K", "20-F", "10-Q"):
                continue
            fdate = arr["filingDate"][i]
            try:
                dt = datetime.strptime(fdate, "%Y-%m-%d").replace(tzinfo=CST)
            except ValueError:
                continue
            if dt < cutoff:
                continue
            rows.append({
                "form": form,
                "filing_date": fdate,
                "report_date": arr.get("reportDate", [""] * n)[i],
                "accession": arr["accessionNumber"][i],
                "primary_doc": arr["primaryDocument"][i],
                "description": (arr.get("primaryDocDescription") or [""] * n)[i],
            })

    collect(recent)
    # recent 通常 ~40 条已够 5 年；不够则翻页拉取历史
    for f in data["filings"].get("files", []):
        if len(rows) >= years * 6:  # 够用即停
            break
        name = f["name"]
        url = f"https://data.sec.gov/submissions/{name}"
        rr = session.get(url, timeout=HTTP_TIMEOUT)
        if rr.status_code != 200:
            continue
        collect(rr.json())
        time.sleep(SEC_RATE_GAP)

    rows.sort(key=lambda x: x["filing_date"], reverse=True)
    return rows


def sec_period(form: str, report_date: str) -> str:
    """10-K/20-F -> 'YYYY'；10-Q -> 'YYYYQN'。"""
    if not report_date:
        return "unknown"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", report_date)
    if not m:
        return report_date[:4] if len(report_date) >= 4 else "unknown"
    year, month = int(m.group(1)), int(m.group(2))
    if form in ("10-K", "20-F"):
        return str(year)
    # 10-Q 季度：按财月归到 Q1-Q4（近似：自然月）
    q = (month - 1) // 3 + 1
    return f"{year}Q{q}"


def fetch_sec(session, ticker, raw_dir, want_types, years, force):
    cik_map = sec_cik_map(session)
    tk = ticker.upper().replace(".US", "")
    if tk not in cik_map:
        raise SystemExit(f"SEC EDGAR 未找到 ticker '{tk}'。可在 sec.gov 检索确认。")
    cik = cik_map[tk]
    print(f"[SEC] {tk} -> CIK {cik}", file=sys.stderr)
    filings = sec_list_filings(session, cik, years)

    manifest = load_manifest(raw_dir)
    manifest["ticker"] = ticker
    saved = 0

    for fl in filings:
        ftype = "annual" if fl["form"] in ("10-K", "20-F") else "quarterly"
        if ftype not in want_types:
            continue
        period = sec_period(fl["form"], fl["report_date"])
        if not force:
            ex = find_in_manifest(manifest, ftype, period)
            if ex and (raw_dir / ftype / ex["filename"]).exists():
                print(f"[SEC] 复用 {ftype} {period}: {ex['filename']}", file=sys.stderr)
                continue
        ext = Path(fl["primary_doc"]).suffix or ".htm"
        filename = f"{ticker}-{ftype}-{safe_filename_part(period)}{ext}"
        dest = raw_dir / ftype / filename
        url = SEC_ARCHIVE_URL.format(
            cik=cik, acc_nodash=fl["accession"].replace("-", ""),
            doc=fl["primary_doc"],
        )
        time.sleep(SEC_RATE_GAP)
        try:
            size = download_to(session, url, dest)
        except RuntimeError as e:
            print(f"[SEC] 跳过 {fl['form']} {period}: {e}", file=sys.stderr)
            continue
        md5 = md5_file(dest)
        src = f"SEC EDGAR {fl['form']} (accession {fl['accession']}, filed {fl['filing_date']})"
        record_file(manifest, raw_dir, ftype, filename, period, src, url, size, md5)
        save_manifest(raw_dir, manifest)
        saved += 1
        print(f"[SEC] 下载 {ftype} {period}: {filename} ({size:,} B)", file=sys.stderr)
    return saved


# --------------------------------------------------------------------------- #
# 港交所披露易
# --------------------------------------------------------------------------- #

def hkex_stock_id(session, code5: str):
    """股票代码 -> 披露易内部 stockId。本地缓存 7 天。"""
    cache = Path("/tmp/.hkex_stocks.json")
    if cache.exists() and (time.time() - cache.stat().st_mtime < 7 * 86400):
        stocks = json.loads(cache.read_text(encoding="utf-8"))
    else:
        r = session.get(HKEX_STOCK_MAP_URL, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        stocks = r.json()
        cache.write_text(json.dumps(stocks), encoding="utf-8")
    for s in stocks:
        if s.get("c") == code5:
            return s.get("i"), s.get("n")
    return None, None


def hkex_search(session, stock_id, date_from, date_to,
               t1code="-2", t2code="-2"):
    """返回 [{date, headline, url}, ...]。date_from/to 为 'YYYYMMDD'。

    t1code/t2code 为披露易文档类别层级码：
      年报  t1code=40000 t2code=40100
      中期  t1code=40000 t2code=40200
    默认 -2 表示不限（广搜，结果可能超 100 条上限）。
    """
    # 1) GET 取动态 form id + ViewState + cookie
    r = session.get(HKEX_SEARCH_URL, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    page = r.text
    fm = re.search(r'<form id="(j_idt\d+)"', page)
    vm = re.search(r'<input[^>]*name="javax.faces.ViewState"[^>]*>', page)
    if not fm or not vm:
        raise RuntimeError("披露易页面结构变化：无法定位 form/ViewState。")
    form_id = fm.group(1)
    view_state = re.search(r'value="([^"]+)"', vm.group(0)).group(1)

    # 2) POST 检索
    fields = {
        form_id: form_id,
        "javax.faces.ViewState": view_state,
        "stockId": str(stock_id),
        "stockCode": "",
        "category": "0",
        "documentType": "-2",
        "from": date_from,
        "to": date_to,
        "lang": "EN",
        "market": "SEHK",
        "searchType": "1",
        "t1code": str(t1code),
        "t2code": str(t2code),
        "t2Gcode": "-2",
        "title": "",
        "MB-Daterange": "0",
        "titleSearchResultControl.searchByIndex": "0",
    }
    r = session.post(
        HKEX_SEARCH_URL, data=fields, timeout=HTTP_TIMEOUT,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    r.raise_for_status()
    return hkex_parse_rows(r.text)


def hkex_parse_rows(page: str) -> list:
    rows = re.findall(r"<tr[^>]*>.*?</tr>", page, re.S)
    out = []
    for tr in rows:
        if "listconews" not in tr:
            continue
        url_m = re.search(r'href="(/listedco/listconews/[^"]+)"', tr)
        if not url_m:
            continue
        date_m = re.search(
            r'release-time[^>]*>\s*(?:<span[^>]*>[^<]*</span>)?\s*(\d{2}/\d{2}/\d{4})',
            tr, re.S,
        )
        head_m = re.search(r'class="headline">(.*?)</div>', tr, re.S)
        headline = ""
        if head_m:
            headline = re.sub(r"<[^>]+>", "", head_m.group(1)).strip()
        headline = html_lib.unescape(re.sub(r"\\s+", " ", headline))
        date = date_m.group(1) if date_m else ""  # DD/MM/YYYY
        out.append({
            "date": date,
            "headline": headline,
            "url": HKEX_DOC_BASE + url_m.group(1),
        })
    return out


# 披露易文档类别层级码（来自 eds/tierone_e.json、tiertwo_e.json）
HKEX_T1_FINANCIAL = 40000      # Financial Statements/ESG Information
HKEX_T2_ANNUAL = 40100         # Annual Report
HKEX_T2_INTERIM = 40200        # Interim Report


def hk_period_from_date(ftype, date_str):
    """从公布日期反推财年/期间。

    港股年报通常次年 3-4 月公布，覆盖上一自然年 -> FY = 公布年-1；
    中期报告通常 8 月公布，覆盖当年 H1 -> YYYYH1。
    """
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", date_str or "")
    if not m:
        return "unknown"
    try:
        d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return "unknown"
    if ftype == "annual":
        return str(d.year - 1 if d.month <= 6 else d.year)
    return f"{d.year}H1"


def fetch_hkex(session, ticker, raw_dir, want_types, years, force):
    code5 = normalize_hk_code(ticker)
    stock_id, name = hkex_stock_id(session, code5)
    if not stock_id:
        raise SystemExit(
            f"披露易未找到股票代码 '{code5}'（{ticker}）。请确认代码。"
        )
    print(f"[HKEX] {code5} {name or ''} -> stockId {stock_id}", file=sys.stderr)

    today = datetime.now(CST)
    date_to = today.strftime("%Y%m%d")
    date_from = (today - timedelta(days=years * 366 + 30)).strftime("%Y%m%d")

    # 按类别精准检索：年报 t2=40100、中期 t2=40200，各自只返回数条，无需翻页
    jobs = []
    if "annual" in want_types:
        jobs.append(("annual", HKEX_T2_ANNUAL))
    if "quarterly" in want_types:
        jobs.append(("quarterly", HKEX_T2_INTERIM))

    manifest = load_manifest(raw_dir)
    manifest["ticker"] = ticker
    seen = set()
    saved = 0

    for ftype, t2 in jobs:
        rows = hkex_search(
            session, stock_id, date_from, date_to,
            t1code=HKEX_T1_FINANCIAL, t2code=t2,
        )
        label = {"annual": "年报", "quarterly": "中期"}[ftype]
        print(f"[HKEX] {label}(t2={t2}) 命中 {len(rows)} 条", file=sys.stderr)
        for row in rows:
            period = hk_period_from_date(ftype, row["date"])
            if period in seen:
                continue
            if not force:
                ex = find_in_manifest(manifest, ftype, period)
                if ex and (raw_dir / ftype / ex["filename"]).exists():
                    print(f"[HKEX] 复用 {ftype} {period}: {ex['filename']}",
                          file=sys.stderr)
                    seen.add(period)
                    continue
            ext = ".pdf" if row["url"].lower().endswith(".pdf") else ".htm"
            filename = f"{ticker}-{ftype}-{safe_filename_part(period)}{ext}"
            dest = raw_dir / ftype / filename
            try:
                size = download_to(
                    session, row["url"], dest, referer=HKEX_SEARCH_URL
                )
            except RuntimeError as e:
                print(f"[HKEX] 跳过 {ftype} {period}: {e}", file=sys.stderr)
                continue
            md5 = md5_file(dest)
            src = (f"港交所披露易 hkexnews.hk（{row['headline'][:40]}，"
                   f"公布 {row['date']}）")
            record_file(
                manifest, raw_dir, ftype, filename, period, src,
                row["url"], size, md5,
            )
            save_manifest(raw_dir, manifest)
            seen.add(period)
            saved += 1
            print(f"[HKEX] 下载 {ftype} {period}: {filename} ({size:,} B)",
                  file=sys.stderr)
    return saved

def fetch_ir(session, urls, ticker, raw_dir, force):
    manifest = load_manifest(raw_dir)
    manifest["ticker"] = ticker
    saved = 0
    for idx, url in enumerate(urls):
        ext = ".pdf"
        for e in (".pdf", ".PDF", ".htm", ".html"):
            if url.lower().endswith(e):
                ext = e.lower()
                break
        # 尝试从 URL/文件名解析财年
        period = "ir-supplement"
        ym = re.search(r"(20\d\d)", url)
        if ym:
            period = ym.group(1)
        am = re.search(r"annual|年报|年報", url, re.I)
        qm = re.search(r"interim|中期|中期報告|quarter|季报|季報", url, re.I)
        ftype = "annual" if am else ("quarterly" if qm else "annual")
        if not force:
            ex = find_in_manifest(manifest, ftype, period)
            if ex and (raw_dir / ftype / ex["filename"]).exists():
                print(f"[IR] 复用 {ftype} {period}: {ex['filename']}", file=sys.stderr)
                continue
        filename = f"{ticker}-{ftype}-{safe_filename_part(period)}-{idx}{ext}"
        dest = raw_dir / ftype / filename
        try:
            size = download_to(session, url, dest)
        except RuntimeError as e:
            print(f"[IR] 跳过 {url}: {e}", file=sys.stderr)
            continue
        md5 = md5_file(dest)
        record_file(
            manifest, raw_dir, ftype, filename, period,
            f"公司官网 {urlparse(url).netloc}", url, size, md5,
        )
        save_manifest(raw_dir, manifest)
        saved += 1
        print(f"[IR] 下载 {ftype} {period}: {filename} ({size:,} B)", file=sys.stderr)
    return saved


# --------------------------------------------------------------------------- #
# --list / --rebuild-manifest
# --------------------------------------------------------------------------- #

def do_list(session, ticker, market, years):
    if market == "hongkong":
        code5 = normalize_hk_code(ticker)
        sid, name = hkex_stock_id(session, code5)
        if not sid:
            print(f"披露易未找到 {code5}", file=sys.stderr)
            return
        today = datetime.now(CST)
        df = (today - timedelta(days=years * 366 + 30)).strftime("%Y%m%d")
        dt = today.strftime("%Y%m%d")
        for ftype, t2, label in (
            ("annual", HKEX_T2_ANNUAL, "[年报]"),
            ("quarterly", HKEX_T2_INTERIM, "[中期]"),
        ):
            rows = hkex_search(session, sid, df, dt,
                               t1code=HKEX_T1_FINANCIAL, t2code=t2)
            for row in rows:
                period = hk_period_from_date(ftype, row["date"])
                print(f"{label} {period}  {row['date']}  "
                      f"{row['headline'][:50]}  {row['url']}")
    else:
        cik_map = sec_cik_map(session)
        tk = ticker.upper().replace(".US", "")
        cik = cik_map.get(tk)
        if not cik:
            print(f"SEC 未找到 {tk}", file=sys.stderr)
            return
        for fl in sec_list_filings(session, cik, years):
            print(f"[{fl['form']:5}] {fl['filing_date']}  period={fl['report_date']}  {fl['primary_doc']}")


def do_rebuild(raw_dir, ticker):
    manifest = {"generated_at": now_iso(), "ticker": ticker, "files": []}
    for ftype in ("annual", "quarterly"):
        sub = raw_dir / ftype
        if not sub.is_dir():
            continue
        for f in sorted(sub.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                # 从文件名解析 period: {ticker}-{type}-{period}.{ext}
                pm = re.match(
                    rf"{re.escape(ticker)}-{ftype}-(.+)\.[A-Za-z0-9]+$", f.name
                )
                period = pm.group(1) if pm else "unknown"
                record_file(
                    manifest, raw_dir, ftype, f.name, period,
                    "本地归档（rebuild-manifest 重建）", "", f.stat().st_size,
                    md5_file(f),
                )
    save_manifest(raw_dir, manifest)
    print(f"[rebuild] {raw_dir}/manifest.json 已重建，"
          f"共 {len(manifest['files'])} 个文件", file=sys.stderr)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(
        description="免登录下载美股 SEC EDGAR / 港股披露易 / 公司官网财报原件。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("ticker", help="股票代码：美股 AAPL/TSM/TCEHY；港股 0700.HK/00700")
    ap.add_argument("--market", choices=["american", "hongkong", "auto"], default="auto")
    ap.add_argument("--type", choices=["annual", "quarterly", "all"], default="all")
    ap.add_argument("--years", type=int, default=5, help="回溯年数（默认 5）")
    ap.add_argument("--out-dir", default=str(DEFAULT_CACHE_ROOT),
                    help=f"财报缓存根目录（默认 {DEFAULT_CACHE_ROOT}）")
    ap.add_argument("--ir-url", action="append", default=[],
                    help="公司官网 PDF 直链，可重复（兜底/补充）")
    ap.add_argument("--ir-list", help="IR 登记文件：每行 'ticker<TAB>url'")
    ap.add_argument("--list", action="store_true", help="仅列出可下载财报，不下载")
    ap.add_argument("--rebuild-manifest", action="store_true",
                    help="扫描 raw/ 重建 manifest.json")
    ap.add_argument("--force", action="store_true", help="强制重新下载（忽略复用）")
    ap.add_argument("--proxy", help="HTTP/HTTPS 代理地址")
    args = ap.parse_args()

    from urllib.parse import urlparse  # 局部导入，供 fetch_ir 使用
    globals()["urlparse"] = urlparse

    market = args.market
    if market == "auto":
        market = detect_market(args.ticker)

    raw_dir = Path(args.out_dir) / market / args.ticker.upper() / "raw"

    if args.rebuild_manifest:
        do_rebuild(raw_dir, args.ticker)
        return

    want = {"annual", "quarterly"} if args.type == "all" else {args.type}
    session = http_session(args.proxy)

    if args.list:
        do_list(session, args.ticker, market, args.years)
        return

    total = 0
    if market == "american":
        total += fetch_sec(session, args.ticker, raw_dir, want, args.years, args.force)
    else:
        total += fetch_hkex(session, args.ticker, raw_dir, want, args.years, args.force)

    # 公司官网兜底
    ir_urls = list(args.ir_url)
    if args.ir_list and Path(args.ir_list).exists():
        for line in Path(args.ir_list).read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].strip().upper() == args.ticker.upper():
                ir_urls.append(parts[1].strip())
    if ir_urls:
        total += fetch_ir(session, ir_urls, args.ticker, raw_dir, args.force)

    print(f"\n完成：{args.ticker} 共下载/复用 {total} 份财报 -> {raw_dir}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
