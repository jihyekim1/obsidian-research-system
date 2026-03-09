#!/usr/bin/env python3
"""
setup.py — Obsidian Research System 초기 설정
vault 경로, 연구 관심사, API 키를 입력받아 config.txt와 .api-keys를 생성합니다.
"""

import os
import sys
import shutil
from pathlib import Path

def main():
    print("=" * 60)
    print("  Obsidian Research System — 초기 설정")
    print("=" * 60)
    print()

    # ── 1. vault 경로 입력 ─────────────────────────────────────
    print("[1/4] Obsidian vault 경로를 입력하세요.")
    print("  예) C:/Users/홍길동/Documents/Obsidian Vault")
    print("  예) /Users/honggildong/Documents/ObsidianVault")
    print()

    while True:
        vault_path = input("Vault 경로: ").strip().strip('"').strip("'")
        if not vault_path:
            print("  경로를 입력해주세요.")
            continue
        vault_path = vault_path.replace("\\", "/")
        if os.path.isdir(vault_path):
            print(f"  확인: {vault_path}")
            break
        else:
            create = input(f"  '{vault_path}' 폴더가 없습니다. 새로 만들까요? (y/n): ").strip().lower()
            if create == "y":
                os.makedirs(vault_path, exist_ok=True)
                print(f"  폴더 생성 완료: {vault_path}")
                break
            else:
                print("  다시 입력해주세요.")

    print()

    # ── 2. 연구 관심사 입력 ────────────────────────────────────
    print("[2/4] 연구 관심사를 입력하세요.")
    print("  논문 분석 시 'AI가 내 연구와의 연결성'을 평가할 때 사용됩니다.")
    print("  예) machine learning, education technology, HCI")
    print("  예) 인공지능 교육, 컴퓨팅 사고력, 피지컬 컴퓨팅")
    print()

    research_interests = input("연구 관심사 (쉼표로 구분): ").strip()
    if not research_interests:
        research_interests = "your research interests"
    print(f"  확인: {research_interests}")
    print()

    # ── 3. vault 폴더 구조 복사 ────────────────────────────────
    print("[3/4] vault 템플릿을 복사합니다...")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(script_dir, "vault-template")

    folders = [
        "01-inbox", "02-daily-notes", "03-projects",
        "04-areas", "05-resources/papers", "06-archives",
        "99-meta/scripts", "99-meta/inbox-pdfs"
    ]

    for folder in folders:
        target = os.path.join(vault_path, folder)
        os.makedirs(target, exist_ok=True)

    # 스크립트 복사
    scripts_src = os.path.join(template_dir, "99-meta", "scripts")
    scripts_dst = os.path.join(vault_path, "99-meta", "scripts")
    for fname in ["fetch-papers.py", "pdf-watcher.py"]:
        src = os.path.join(scripts_src, fname)
        dst = os.path.join(scripts_dst, fname)
        if os.path.exists(src):
            shutil.copy2(src, dst)

    # MOC 파일 복사 (이미 있으면 건너뜀)
    for folder_name in ["01-inbox", "02-daily-notes", "03-projects",
                        "04-areas", "05-resources", "06-archives", "99-meta"]:
        src = os.path.join(template_dir, folder_name, "MOC.md")
        dst = os.path.join(vault_path, folder_name, "MOC.md")
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)

    # paper-watch.md 복사 (없을 때만)
    pw_src = os.path.join(template_dir, "99-meta", "paper-watch.md")
    pw_dst = os.path.join(vault_path, "99-meta", "paper-watch.md")
    if os.path.exists(pw_src) and not os.path.exists(pw_dst):
        shutil.copy2(pw_src, pw_dst)

    # CLAUDE.md 복사 + 경로 치환
    claude_src = os.path.join(template_dir, "CLAUDE.md")
    claude_dst = os.path.join(vault_path, "CLAUDE.md")
    if os.path.exists(claude_src) and not os.path.exists(claude_dst):
        with open(claude_src, encoding="utf-8") as f:
            content = f.read()
        content = content.replace("{YOUR_VAULT_PATH}", vault_path)
        with open(claude_dst, "w", encoding="utf-8") as f:
            f.write(content)
        print("  CLAUDE.md 생성 완료")

    print("  vault 구조 복사 완료")
    print()

    # ── 4. config.txt 생성 ────────────────────────────────────
    print("[4/4] 설정 파일을 생성합니다...")

    config_path = os.path.join(vault_path, "99-meta", "config.txt")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(f"# Obsidian Research System 설정\n")
        f.write(f"# 이 파일은 setup.py가 자동 생성했습니다.\n\n")
        f.write(f"VAULT_PATH={vault_path}\n")
        f.write(f"RESEARCH_INTERESTS={research_interests}\n")
    print(f"  config.txt 생성: {config_path}")

    # .api-keys 예시 파일 복사
    api_keys_example_src = os.path.join(template_dir, "99-meta", ".api-keys.example")
    api_keys_dst = os.path.join(vault_path, "99-meta", ".api-keys")
    if not os.path.exists(api_keys_dst) and os.path.exists(api_keys_example_src):
        shutil.copy2(api_keys_example_src, api_keys_dst)
        print(f"  .api-keys 생성 (API 키를 직접 입력해주세요)")

    print()
    print("=" * 60)
    print("  설정 완료!")
    print("=" * 60)
    print()
    print("다음 단계:")
    print()
    print(f"  1. {vault_path}/99-meta/.api-keys 파일을 열어")
    print("     Gemini API 키와 Naver API 키를 입력하세요.")
    print()
    print(f"  2. {vault_path}/99-meta/paper-watch.md 파일을 열어")
    print("     모니터링할 키워드를 입력하세요.")
    print()
    print("  3. Obsidian에서 vault를 열고, Claude Code를 실행하세요.")
    print()
    print("  API 키 발급 방법:")
    print("  - Gemini: https://aistudio.google.com/apikey (무료)")
    print("  - Naver:  https://developers.naver.com/apps/#/register (무료)")
    print()


if __name__ == "__main__":
    main()
