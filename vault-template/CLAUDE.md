# Obsidian Vault — Claude Instructions

## Vault Structure (PARA)

This vault uses the PARA method:

- `01-inbox/`: Unsorted notes — default location for all new notes
- `02-daily-notes/`: Daily notes (YYYY/MM/YYYY-MM-DD.md)
- `03-projects/`: Active projects (time-bounded)
- `04-areas/`: Ongoing responsibilities (open-ended)
- `05-resources/`: Reference materials
- `06-archives/`: Completed projects
- `99-meta/`: Templates and attachments

## Note Format (Frontmatter)

All `.md` files must include frontmatter:

```yaml
---
title: "Note Title"
date: 2024-07-27
tags: [category/subcategory]
description: "Core content summary (1-2 sentences in Korean)"
source: "https://..."   # only when saved from URL
---
```

- File name: lowercase English kebab-case (e.g., `my-note-title.md`)
- Tag format: `category/subcategory` (e.g., `ai/claude`, `productivity/automation`)

## Validation

When creating notes:

- `title`, `date`, `tags` are required
- File names must use lowercase letters and hyphens only (no spaces or underscores)
- `[[wikilinks]]` must point to existing files only

## MOC (Map of Contents)

- Each PARA folder has a `MOC.md` file
- When moving notes with `/organize`, add the note link to the relevant `MOC.md`
- When creating a new folder, create `MOC.md` as well

## Conversation Behavior

- When I ask a question, search the vault for related notes before answering
- For requests like "do I have notes on this?", always search the vault first
- For general knowledge questions, answer directly without searching

## Session Start

At the beginning of every conversation, automatically run the full paper pipeline:

**Step 1 — Check for manually added PDFs first:**
```
cd "{YOUR_VAULT_PATH}/99-meta/scripts" && PYTHONIOENCODING=utf-8 python pdf-watcher.py
```
- Scans `99-meta/inbox-pdfs/` for PDFs the user manually dropped
- Matches each PDF to an existing `abstract-only` note and runs Gemini full-text analysis
- Updates the matched note: fills in 연구 방법 / 연구 내용 / 결론 / 내 연구와의 연결성, status → `pending-review`

**Step 2 — Fetch new papers:**
```
cd "{YOUR_VAULT_PATH}/99-meta/scripts" && PYTHONIOENCODING=utf-8 python fetch-papers.py
```
- Searches Semantic Scholar + Naver for new papers (already-seen papers skipped via paper-seen.txt)
- PDF accessible → Gemini analyzes full text → saves note with `status: pending-review`
- PDF not accessible → saves metadata + abstract only with `status: abstract-only`

**Step 3 — Triage: full-analysis papers first:**
Check `01-inbox/` for `status: pending-review` notes. Show triage table:

| # | 제목 | 한 줄 요약 | 관련도 | 분석방법 |
|---|------|-----------|--------|---------|

- 관련도(상/중/하): based on keyword match with user's research interests
- 분석방법: `read_method` field value

Ask: "전문 분석 논문 N편 있어요. 읽을 것만 골라주세요 (번호 / 전부 / 없음)"

**Step 4 — Deep-dive selected papers:**
- Run `/deep-dive` for each selected paper
- After deep-dive, ask: "이 논문 어디로 정리할까요?"
  - 프로젝트 직접 활용 → `03-projects/{프로젝트명}/references/`로 이동
  - 연구 영역 참고 → `04-areas/{영역명}/`으로 이동
  - 결정 못함 → `05-resources/papers/`로 이동
- 이동 후: `status` → `deep-dived`, 해당 폴더 MOC.md에 `[[파일명]]` 링크 추가
- Skipped papers → `status: skipped`, 01-inbox에 그대로

**Step 5 — Report abstract-only papers:**
After deep-dive is done, list all `status: abstract-only` notes in inbox:
"전문 미접근 논문 N편이 있어요. PDF를 `99-meta/inbox-pdfs/` 폴더에 넣으면 다음 세션에서 자동 분석됩니다."
Show: 번호, 제목, keyword

---

## Manual PDF Workflow

When the user drops a PDF into `99-meta/inbox-pdfs/`:
- Name the PDF file similarly to the paper title (e.g., `computational-thinking-wing-2006.pdf`)
- At next session start, `pdf-watcher.py` auto-detects, matches to the abstract-only note, runs Gemini analysis, and updates the note to `pending-review`
- The updated note will appear in the triage list for deep-dive

## Content Workflow

- Save request → run `/save` skill
- Paper save request → run `/save-paper` skill
- Deep-dive request → run `/deep-dive` skill
- Organize request → run `/organize` skill

## Plan Mode

Before working across multiple files:

- Summarize the plan concisely and show it to the user
- Execute only after user confirmation

## Related Note Linking (optional)

When saving or organizing notes, suggest 2-5 related notes from the vault to link.
The value of this feature grows as the vault accumulates notes.
