#!/usr/bin/env python3
"""
pdf-watcher.py
99-meta/inbox-pdfs/ 폴더에 수동으로 넣은 PDF를 감지하여:
1. 기존 abstract-only 노트와 매칭
2. Gemini로 전문 분석
3. 노트 업데이트 (status: abstract-only → pending-review)
"""

import os
import re
import sys
import time
from pathlib import Path

import requests
from google import genai

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── config.txt에서 경로 로드 ──────────────────────────────────
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
API_KEYS  = os.path.join(VAULT, "99-meta", ".api-keys")
INBOX     = os.path.join(VAULT, "01-inbox")
PDF_INBOX = os.path.join(VAULT, "99-meta", "inbox-pdfs")
DONE_DIR  = os.path.join(VAULT, "99-meta", "inbox-pdfs", "processed")

GEMINI_MODEL = "gemini-2.5-flash"

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


# ═══════════════════════════════════════════════════════════════
#  유틸
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


def normalize(text):
    return re.sub(r"[^a-z0-9가-힣]", " ", text.lower()).split()


def title_similarity(a, b):
    wa, wb = set(normalize(a)), set(normalize(b))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def find_matching_note(pdf_stem):
    best_path, best_score = None, 0.0
    for fname in os.listdir(INBOX):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(INBOX, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                head = f.read(800)
        except Exception:
            continue
        if "status: abstract-only" not in head:
            continue
        m = re.search(r'^title:\s*"?(.+?)"?\s*$', head, re.MULTILINE)
        note_title = m.group(1) if m else fname
        score = title_similarity(pdf_stem, note_title)
        if score > best_score:
            best_score = score
            best_path = fpath
    return best_path, best_score


# ═══════════════════════════════════════════════════════════════
#  Gemini 분석
# ═══════════════════════════════════════════════════════════════

def analyze_pdf(client, pdf_path):
    uploaded = client.files.upload(
        file=pdf_path,
        config={"mime_type": "application/pdf"},
    )
    while uploaded.state.name == "PROCESSING":
        time.sleep(2)
        uploaded = client.files.get(name=uploaded.name)

    if uploaded.state.name == "FAILED":
        raise RuntimeError(f"Gemini 파일 업로드 실패: {uploaded.name}")

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[uploaded, GEMINI_PROMPT],
    )
    try:
        client.files.delete(name=uploaded.name)
    except Exception:
        pass
    return response.text


def parse_analysis(analysis_text):
    sections = {
        "연구 방법": "",
        "연구 내용": "",
        "결론": "",
        "내 연구와의 연결성": "",
    }
    current, lines = None, []
    for line in analysis_text.split("\n"):
        m = re.match(r"^###?\s*(.+)", line)
        if m:
            if current and current in sections:
                sections[current] = "\n".join(lines).strip()
            lines, current = [], None
            for key in sections:
                if key in m.group(1).strip():
                    current = key
                    break
        else:
            lines.append(line)
    if current and current in sections:
        sections[current] = "\n".join(lines).strip()
    return sections


# ═══════════════════════════════════════════════════════════════
#  노트 업데이트
# ═══════════════════════════════════════════════════════════════

def update_note(note_path, sections, pdf_filename):
    with open(note_path, encoding="utf-8") as f:
        content = f.read()

    content = content.replace("status: abstract-only", "status: pending-review")
    content = re.sub(
        r'tags: \[research/paper, abstract-only\]',
        "tags: [research/paper, pending-review]",
        content,
    )
    content = re.sub(r'read_method: "초록만"', 'read_method: "전문"', content)

    analysis_block = f"""## 연구 방법

{sections.get('연구 방법', '(분석 실패)')}

## 연구 내용

{sections.get('연구 내용', '(분석 실패)')}

## 결론

{sections.get('결론', '(분석 실패)')}

## 내 연구와의 연결성

{sections.get('내 연구와의 연결성', '(분석 실패)')}

> PDF 수동 추가 후 분석: `{pdf_filename}` (Gemini {GEMINI_MODEL})
"""
    content = re.sub(
        r"## 분석\n.*",
        analysis_block,
        content,
        flags=re.DOTALL,
    )

    with open(note_path, "w", encoding="utf-8") as f:
        f.write(content)


# ═══════════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════════

def main():
    keys = load_api_keys()
    gemini_key = keys.get("GEMINI_API_KEY", "")
    if not gemini_key:
        print("GEMINI_API_KEY가 없습니다.")
        return
    client = genai.Client(api_key=gemini_key)

    pdfs = [f for f in os.listdir(PDF_INBOX)
            if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(PDF_INBOX, f))]

    if not pdfs:
        print("inbox-pdfs/에 새 PDF 없음.")
        return

    os.makedirs(DONE_DIR, exist_ok=True)
    updated = []

    for pdf_fname in pdfs:
        pdf_path = os.path.join(PDF_INBOX, pdf_fname)
        pdf_stem = os.path.splitext(pdf_fname)[0]
        print(f"\n[PDF] {pdf_fname}")

        note_path, score = find_matching_note(pdf_stem)
        if note_path and score >= 0.25:
            print(f"  매칭 노트: {os.path.basename(note_path)} (유사도 {score:.2f})")
        else:
            print(f"  매칭 노트 없음 (유사도 {score:.2f}) — 스킵")
            print(f"  힌트: PDF 파일명을 논문 제목과 비슷하게 지정해주세요.")
            continue

        print(f"  Gemini 분석 중...")
        try:
            raw = analyze_pdf(client, pdf_path)
            sections = parse_analysis(raw)
            update_note(note_path, sections, pdf_fname)
            print(f"  노트 업데이트 완료: {os.path.basename(note_path)}")
            updated.append(os.path.basename(note_path))

            done_path = os.path.join(DONE_DIR, pdf_fname)
            os.rename(pdf_path, done_path)
        except Exception as e:
            print(f"  분석 실패: {e}")

        time.sleep(4)

    print(f"\n완료: {len(updated)}개 노트 업데이트")
    for n in updated:
        print(f"  - {n}")
    return updated


if __name__ == "__main__":
    main()
