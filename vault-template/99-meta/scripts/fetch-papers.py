#!/usr/bin/env python3
"""
fetch-papers.py
논문 자동 수집 + Gemini PDF 분석 파이프라인.

1. Semantic Scholar API로 키워드 검색 (영문)
2. Naver 학술 API로 키워드 검색 (한국어 논문 보완)
3. PDF 다운로드 (arXiv / OA)
4. Gemini API로 전문 분석 (PDF 또는 초록)
5. 완성된 .md 파일을 01-inbox에 저장
"""

import os
import re
import json
import sys
import time
import urllib.request
import urllib.parse
from datetime import date
from pathlib import Path

import requests
from google import genai

# Windows 콘솔 인코딩 문제 방지
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── config.txt에서 경로 및 설정 로드 ─────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "..", "config.txt")

def load_config():
    config = {}
    if not os.path.exists(CONFIG_FILE):
        print("오류: 99-meta/config.txt 파일이 없습니다.")
        print("프로젝트 루트에서 setup.py를 먼저 실행해주세요.")
        sys.exit(1)
    with open(CONFIG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()
    return config

config = load_config()

VAULT = config.get("VAULT_PATH", "")
if not VAULT:
    print("오류: config.txt에 VAULT_PATH가 설정되지 않았습니다.")
    sys.exit(1)

RESEARCH_INTERESTS = config.get(
    "RESEARCH_INTERESTS",
    "your research interests here"
)

# ── 경로 설정 ────────────────────────────────────────────────
API_KEYS   = os.path.join(VAULT, "99-meta", ".api-keys")
WATCH_FILE = os.path.join(VAULT, "99-meta", "paper-watch.md")
SEEN_FILE  = os.path.join(VAULT, "99-meta", "paper-seen.txt")
INBOX      = os.path.join(VAULT, "01-inbox")
PDF_DIR    = os.path.join(VAULT, "99-meta", "pdfs")

# ── Semantic Scholar ─────────────────────────────────────────
S2_BASE   = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "title,abstract,authors,year,venue,externalIds,isOpenAccess,openAccessPdf,tldr,citationCount"

# ── 수집 설정 ────────────────────────────────────────────────
S2_LIMIT      = 5
NAVER_DISPLAY = 5
DAILY_LIMIT   = 5
GEMINI_MODEL  = "gemini-2.5-flash"
S2_RETRY_MAX  = 3
S2_RETRY_WAIT = 60


# ═══════════════════════════════════════════════════════════════
#  유틸리티
# ═══════════════════════════════════════════════════════════════

def load_api_keys():
    keys = {}
    with open(API_KEYS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    return keys


def load_keywords():
    keywords = []
    with open(WATCH_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("- "):
                keywords.append(line[2:].strip())
    return keywords


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_seen(identifier):
    with open(SEEN_FILE, "a", encoding="utf-8") as f:
        f.write(identifier + "\n")


def strip_html(text):
    return re.sub(r"<[^>]+>", "", text).strip()


def make_slug(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:50]


# ═══════════════════════════════════════════════════════════════
#  Semantic Scholar API
# ═══════════════════════════════════════════════════════════════

def s2_request(url, params, s2_api_key=None):
    headers = {}
    if s2_api_key:
        headers["x-api-key"] = s2_api_key
    for attempt in range(S2_RETRY_MAX):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code == 429:
                wait = S2_RETRY_WAIT * (attempt + 1)
                print(f"    S2 rate limit — {wait}초 대기 중...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            time.sleep(1)
            return resp.json()
        except requests.exceptions.HTTPError:
            raise
        except Exception as e:
            print(f"    S2 요청 오류: {e!r}")
            return None
    print("    S2 rate limit 재시도 초과")
    return None


def search_semantic_scholar(query, limit=S2_LIMIT, s2_api_key=None):
    url = f"{S2_BASE}/paper/search"
    params = {"query": query, "limit": limit, "fields": S2_FIELDS}
    result = s2_request(url, params, s2_api_key)
    return result.get("data", []) if result else []


# ═══════════════════════════════════════════════════════════════
#  Naver 학술 API
# ═══════════════════════════════════════════════════════════════

def search_naver(query, client_id, client_secret, display=NAVER_DISPLAY):
    encoded = urllib.parse.quote(query)
    url = (
        f"https://openapi.naver.com/v1/search/doc.json"
        f"?query={encoded}&display={display}&sort=date"
    )
    req = urllib.request.Request(url, headers={
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    })
    try:
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        print(f"  Naver 오류: {e}")
        return {"items": []}


def enrich_naver_with_s2(title, s2_api_key=None):
    url = f"{S2_BASE}/paper/search"
    params = {"query": title, "limit": 1, "fields": S2_FIELDS}
    result = s2_request(url, params, s2_api_key)
    if result:
        data = result.get("data", [])
        if data:
            found_title = data[0].get("title", "").lower()
            if title.lower()[:30] in found_title or found_title[:30] in title.lower():
                return data[0]
    return None


# ═══════════════════════════════════════════════════════════════
#  PDF 다운로드
# ═══════════════════════════════════════════════════════════════

def download_pdf(url, filename):
    os.makedirs(PDF_DIR, exist_ok=True)
    path = os.path.join(PDF_DIR, filename)
    resp = requests.get(url, timeout=60, headers={
        "User-Agent": "ObsidianVault/2.0 (Academic Research)"
    })
    resp.raise_for_status()
    if not resp.content[:5].startswith(b"%PDF"):
        raise ValueError("응답이 PDF가 아닙니다")
    with open(path, "wb") as f:
        f.write(resp.content)
    return path


def try_download_pdf(arxiv_id, oa_pdf_url, title):
    if arxiv_id:
        try:
            safe_id = arxiv_id.replace("/", "_")
            url = f"https://arxiv.org/pdf/{arxiv_id}"
            path = download_pdf(url, f"{safe_id}.pdf")
            return path, "arXiv 전문"
        except Exception as e:
            print(f"    arXiv PDF 실패: {e}")

    if oa_pdf_url:
        try:
            safe_name = re.sub(r"[^a-z0-9]", "_", title[:30].lower()) + ".pdf"
            path = download_pdf(oa_pdf_url, safe_name)
            return path, "OA 전문"
        except Exception as e:
            print(f"    OA PDF 실패: {e}")

    return None, "초록만"


# ═══════════════════════════════════════════════════════════════
#  Gemini 분석
# ═══════════════════════════════════════════════════════════════

GEMINI_PROMPT = f"""다음 논문을 읽고 한국어로 구조화된 분석을 작성해주세요.
각 섹션 헤더를 정확히 지켜주세요.

### 연구 방법
연구 설계, 데이터 수집/분석 방법, 참여자, 도구 등을 서술하세요.
이론 논문이면 어떤 방법론(문헌 검토, 개념 분석 등)을 사용했는지 서술하세요.

### 연구 내용
주요 발견, 수치적 결과, 이론적 기여점을 서술하세요.

### 결론
저자의 결론, 시사점, 향후 연구 방향을 서술하세요.

### 내 연구와의 연결성
이 논문이 다음 연구 분야와 어떻게 연결되는지 구체적으로 서술하세요:
{RESEARCH_INTERESTS}
"""


def analyze_with_gemini(client, pdf_path=None, abstract=None, title=""):
    if pdf_path:
        uploaded = client.files.upload(
            file=pdf_path,
            config={"mime_type": "application/pdf"},
        )
        while uploaded.state.name == "PROCESSING":
            time.sleep(2)
            uploaded = client.files.get(name=uploaded.name)

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[uploaded, GEMINI_PROMPT],
        )
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass
    else:
        fallback_prompt = (
            f"논문 제목: {title}\n\n"
            f"초록:\n{abstract}\n\n"
            f"{GEMINI_PROMPT}\n\n"
            f"(주의: 전문이 아닌 초록만 제공되었습니다. "
            f"각 섹션 앞에 '초록 기반 -- 전문 미확인'을 명시해주세요.)"
        )
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=fallback_prompt,
        )

    return response.text


def parse_analysis(analysis_text):
    sections = {
        "연구 방법": "",
        "연구 내용": "",
        "결론": "",
        "내 연구와의 연결성": "",
    }

    current = None
    lines = []

    for line in analysis_text.split("\n"):
        header_match = re.match(r"^###?\s*(.+)", line)
        if header_match:
            header = header_match.group(1).strip()
            if current and current in sections:
                sections[current] = "\n".join(lines).strip()
            lines = []
            current = None
            for key in sections:
                if key in header:
                    current = key
                    break
        else:
            lines.append(line)

    if current and current in sections:
        sections[current] = "\n".join(lines).strip()

    return sections


# ═══════════════════════════════════════════════════════════════
#  노트 생성
# ═══════════════════════════════════════════════════════════════

def make_note(title, abstract, authors, year, venue, doi, arxiv_id,
              oa_url, citation_count, tldr, keyword, today,
              analysis_sections, read_method, source_url):
    safe_title = title.replace('"', "'")

    author_names = [a if isinstance(a, str) else a.get("name", "") for a in authors]
    if len(author_names) > 5:
        authors_yaml = ", ".join(author_names[:5]) + " 외"
    else:
        authors_yaml = ", ".join(author_names)

    desc = tldr if tldr else (abstract[:200] if abstract else "")
    safe_desc = desc.replace('"', "'").replace("\n", " ")

    optional = []
    if author_names:
        optional.append(f"authors: [{authors_yaml}]")
    if year:
        optional.append(f"year: {year}")
    if venue:
        optional.append(f'venue: "{venue}"')
    if doi:
        optional.append(f'doi: "{doi}"')
    if arxiv_id:
        optional.append(f'arxiv_id: "{arxiv_id}"')
    if oa_url:
        optional.append(f'oa_url: "{oa_url}"')
    if citation_count:
        optional.append(f"citations: {citation_count}")
    optional.append(f'read_method: "{read_method}"')

    extra_fm = "\n".join(optional)
    s = analysis_sections

    return f"""---
title: "{safe_title}"
date: {today}
tags: [research/paper, pending-review]
source: "{source_url}"
keyword: "{keyword}"
status: pending-review
description: "{safe_desc}"
{extra_fm}
---

# {title}

> 키워드 `{keyword}` 로 자동 수집. 분석: {read_method} (Gemini {GEMINI_MODEL}).

## 초록

{abstract or '(초록 없음)'}

## 연구 방법

{s.get('연구 방법', '(분석 실패)')}

## 연구 내용

{s.get('연구 내용', '(분석 실패)')}

## 결론

{s.get('결론', '(분석 실패)')}

## 내 연구와의 연결성

{s.get('내 연구와의 연결성', '(분석 실패)')}
"""


def make_abstract_note(title, abstract, authors, year, venue, doi, arxiv_id,
                       oa_url, citation_count, tldr, keyword, today, source_url):
    safe_title = title.replace('"', "'")

    author_names = [a if isinstance(a, str) else a.get("name", "") for a in authors]
    if len(author_names) > 5:
        authors_yaml = ", ".join(author_names[:5]) + " 외"
    else:
        authors_yaml = ", ".join(author_names)

    desc = tldr if tldr else (abstract[:200] if abstract else "")
    safe_desc = desc.replace('"', "'").replace("\n", " ")

    optional = []
    if author_names:
        optional.append(f"authors: [{authors_yaml}]")
    if year:
        optional.append(f"year: {year}")
    if venue:
        optional.append(f'venue: "{venue}"')
    if doi:
        optional.append(f'doi: "{doi}"')
    if arxiv_id:
        optional.append(f'arxiv_id: "{arxiv_id}"')
    if oa_url:
        optional.append(f'oa_url: "{oa_url}"')
    if citation_count:
        optional.append(f"citations: {citation_count}")
    optional.append('read_method: "초록만"')

    extra_fm = "\n".join(optional)

    return f"""---
title: "{safe_title}"
date: {today}
tags: [research/paper, abstract-only]
source: "{source_url}"
keyword: "{keyword}"
status: abstract-only
description: "{safe_desc}"
{extra_fm}
---

# {title}

> 키워드 `{keyword}` 로 자동 수집. 전문 미접근 — 초록만 저장.

## 초록

{abstract or '(초록 없음)'}

## 분석

> 전문에 접근할 수 없어 분석하지 않았습니다.
> PDF를 `99-meta/inbox-pdfs/` 폴더에 넣으면 자동으로 분석됩니다.
"""


def process_paper(client, title, abstract, authors, year, venue,
                  ext_ids, oa_pdf, tldr_data, citation_count,
                  keyword, today, seen, source_url):
    doi = ext_ids.get("DOI", "") if ext_ids else ""
    arxiv_id = ext_ids.get("ArXiv", "") if ext_ids else ""
    oa_pdf_url = oa_pdf.get("url", "") if oa_pdf else ""
    tldr = tldr_data.get("text", "") if tldr_data else ""

    print(f"  -> {title[:60]}...")

    pdf_path, read_method = try_download_pdf(arxiv_id, oa_pdf_url, title)

    if pdf_path is None:
        print(f"    [전문 없음 — 초록 노트 저장]")
        filename = f"{today}-{make_slug(title)}.md"
        filepath = os.path.join(INBOX, filename)
        if os.path.exists(filepath):
            filepath = filepath.replace(".md", f"-{hash(title) % 10000}.md")
        note = make_abstract_note(
            title=title, abstract=abstract or "",
            authors=authors or [], year=year or "", venue=venue or "",
            doi=doi, arxiv_id=arxiv_id, oa_url=oa_pdf_url,
            citation_count=citation_count or 0, tldr=tldr,
            keyword=keyword, today=today, source_url=source_url,
        )
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(note)
        print(f"    저장 -> {os.path.basename(filepath)}")
        return True

    print(f"    [{read_method}]")

    try:
        raw_analysis = analyze_with_gemini(
            client,
            pdf_path=pdf_path,
            abstract=abstract,
            title=title,
        )
        sections = parse_analysis(raw_analysis)
        print(f"    Gemini 분석 완료")
    except Exception as e:
        print(f"    Gemini 분석 실패: {e}")
        if pdf_path and os.path.exists(pdf_path):
            os.remove(pdf_path)
        return False

    if pdf_path and os.path.exists(pdf_path):
        os.remove(pdf_path)

    filename = f"{today}-{make_slug(title)}.md"
    filepath = os.path.join(INBOX, filename)

    if os.path.exists(filepath):
        filepath = filepath.replace(".md", f"-{hash(title) % 10000}.md")

    note = make_note(
        title=title, abstract=abstract or "",
        authors=authors or [], year=year or "", venue=venue or "",
        doi=doi, arxiv_id=arxiv_id, oa_url=oa_pdf_url,
        citation_count=citation_count or 0, tldr=tldr,
        keyword=keyword, today=today,
        analysis_sections=sections,
        read_method=read_method,
        source_url=source_url,
    )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(note)
    print(f"    저장 -> {os.path.basename(filepath)}")

    return True


# ═══════════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════════

def main():
    keys     = load_api_keys()
    keywords = load_keywords()
    seen     = load_seen()
    today    = date.today().isoformat()

    gemini_key = keys.get("GEMINI_API_KEY", "")
    if not gemini_key:
        print("GEMINI_API_KEY가 .api-keys에 없습니다.")
        print("https://aistudio.google.com/apikey 에서 발급받으세요.")
        return
    client = genai.Client(api_key=gemini_key)

    naver_id     = keys.get("NAVER_CLIENT_ID", "")
    naver_secret = keys.get("NAVER_CLIENT_SECRET", "")
    s2_key       = keys.get("S2_API_KEY", "")

    new_total = 0

    for kw in keywords:
        if new_total >= DAILY_LIMIT:
            print(f"\n일일 수집 한도 {DAILY_LIMIT}편 도달 — 종료")
            break
        print(f"\n{'='*60}")
        print(f"[검색] {kw}")
        print(f"{'='*60}")

        print(f"\n  --- Semantic Scholar ---")
        papers = search_semantic_scholar(kw, s2_api_key=s2_key)

        for paper in papers:
            paper_id = paper.get("paperId", "")
            ext_ids  = paper.get("externalIds", {}) or {}
            doi      = ext_ids.get("DOI", "")

            if paper_id in seen:
                continue
            if doi and doi in seen:
                continue

            title = paper.get("title", "")
            if not title:
                continue

            source_url = f"https://www.semanticscholar.org/paper/{paper_id}"

            success = process_paper(
                client=client, title=title,
                abstract=paper.get("abstract", ""),
                authors=paper.get("authors", []),
                year=paper.get("year"),
                venue=paper.get("venue", ""),
                ext_ids=ext_ids,
                oa_pdf=paper.get("openAccessPdf"),
                tldr_data=paper.get("tldr"),
                citation_count=paper.get("citationCount", 0),
                keyword=kw, today=today, seen=seen,
                source_url=source_url,
            )

            if success:
                save_seen(paper_id)
                seen.add(paper_id)
                if doi:
                    save_seen(doi)
                    seen.add(doi)
                new_total += 1
                if new_total >= DAILY_LIMIT:
                    break

            time.sleep(4)

        if naver_id and naver_secret:
            print(f"\n  --- Naver 학술 (한국어 보완) ---")
            naver_data = search_naver(kw, naver_id, naver_secret)

            for item in naver_data.get("items", []):
                link = item.get("link", "")
                m = re.search(r"doc_id=(\d+)", link)
                if not m:
                    continue
                doc_id = m.group(1)

                if doc_id in seen:
                    continue

                title = strip_html(item.get("title", ""))
                desc  = strip_html(item.get("description", ""))

                if not title:
                    continue

                s2_data = enrich_naver_with_s2(title, s2_api_key=s2_key)

                if s2_data:
                    s2_id = s2_data.get("paperId", "")
                    if s2_id in seen:
                        continue

                    success = process_paper(
                        client=client,
                        title=s2_data.get("title", title),
                        abstract=s2_data.get("abstract", desc),
                        authors=s2_data.get("authors", []),
                        year=s2_data.get("year"),
                        venue=s2_data.get("venue", ""),
                        ext_ids=s2_data.get("externalIds"),
                        oa_pdf=s2_data.get("openAccessPdf"),
                        tldr_data=s2_data.get("tldr"),
                        citation_count=s2_data.get("citationCount", 0),
                        keyword=kw, today=today, seen=seen,
                        source_url=link,
                    )

                    if success:
                        save_seen(doc_id)
                        seen.add(doc_id)
                        if s2_id:
                            save_seen(s2_id)
                            seen.add(s2_id)
                        new_total += 1
                        if new_total >= DAILY_LIMIT:
                            break
                else:
                    success = process_paper(
                        client=client, title=title, abstract=desc,
                        authors=[], year=None, venue="",
                        ext_ids={}, oa_pdf=None, tldr_data=None,
                        citation_count=0, keyword=kw, today=today,
                        seen=seen, source_url=link,
                    )

                    if success:
                        save_seen(doc_id)
                        seen.add(doc_id)
                        new_total += 1

                if new_total >= DAILY_LIMIT:
                    break

                time.sleep(4)

    if os.path.exists(PDF_DIR):
        try:
            os.rmdir(PDF_DIR)
        except OSError:
            pass

    print(f"\n{'='*60}")
    print(f"완료: 총 {new_total}편 수집 및 분석 저장")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
