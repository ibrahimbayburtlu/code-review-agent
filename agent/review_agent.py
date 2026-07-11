#!/usr/bin/env python3
"""Sıfırdan yazılmış code review agent'ı — hazır agent harness'i yok.

Agent döngüsü (model çağır -> tool çalıştır -> sonucu geri ver -> tekrar) bu dosyada
elle kurulmuştur. Claude'a repo'yu incelemesi için üç okuma tool'u verilir
(list_files, read_file, grep); incelemeyi bitirince submit_review tool'unu
çağırarak bulgularını yapılandırılmış olarak teslim eder. Bulgular GitHub PR'ına
inline + özet yorum olarak gönderilir.

GitHub Actions içinde çalışır. Beklenen ortam değişkenleri:
  ANTHROPIC_API_KEY  - Claude API anahtarı
  GH_TOKEN           - GitHub token (Actions'ın verdiği GITHUB_TOKEN yeterli)
  REPO               - "owner/repo" formatında
  PR_NUMBER          - inceleme yapılacak PR numarası
  BASE_SHA / HEAD_SHA - diff'in alınacağı commit aralığı
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import anthropic

MODEL = "claude-opus-4-8"
MAX_DIFF_CHARS = 80_000
MAX_TOOL_OUTPUT_CHARS = 30_000
MAX_ITERATIONS = 30
MAX_INLINE_COMMENTS = 15

REPO_ROOT = Path.cwd().resolve()

SEVERITY_BADGE = {"high": "🔴 Yüksek", "medium": "🟡 Orta", "low": "🔵 Düşük"}

SYSTEM_PROMPT = """\
Sen kıdemli bir yazılım mühendisisin ve pull request incelemesi yapıyorsun.
Sana bir PR diff'i verilecek. Diff'te bağlamı eksik görünen yerlerde list_files,
read_file ve grep tool'larıyla repo'nun tamamına bakarak değerlendir.

Şunlara odaklan:
- Bug'lar ve mantık hataları
- Güvenlik açıkları (injection, secret sızıntısı, eksik yetki kontrolü)
- Performans sorunları
- Hatalı veya eksik hata yönetimi
- Bakım maliyetini ciddi etkileyen tasarım sorunları

Stil ve format gibi önemsiz konuları raporlama. Emin olmadığın bulguları
düşük önem derecesiyle işaretle.

İncelemeyi bitirdiğinde bulgularını MUTLAKA submit_review tool'unu çağırarak
teslim et. Bulgu yoksa submit_review'u boş findings listesiyle çağır.
Her bulgunun "line" değeri, dosyanın YENİ halindeki (diff'in + tarafındaki)
satır numarası olmalı.
"""

TOOLS = [
    {
        "name": "list_files",
        "description": "Repo'daki (git'e ekli) dosyaları listeler. İsteğe bağlı glob deseniyle filtrelenir, örn. 'src/**/*.py'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "glob": {"type": "string", "description": "Opsiyonel glob deseni. Boş bırakılırsa tüm dosyalar."},
            },
            "required": [],
        },
    },
    {
        "name": "read_file",
        "description": "Repo'dan bir dosyanın içeriğini satır numaralarıyla döner.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo köküne göre dosya yolu."},
                "start_line": {"type": "integer", "description": "Opsiyonel başlangıç satırı (1 tabanlı)."},
                "end_line": {"type": "integer", "description": "Opsiyonel bitiş satırı (dahil)."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "grep",
        "description": "Repo içinde regex araması yapar (git grep). Eşleşen satırları dosya:satır formatında döner.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Aranacak ERE regex deseni."},
                "path": {"type": "string", "description": "Opsiyonel: aramayı sınırlayacak dizin veya glob."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "submit_review",
        "description": "İnceleme bittiğinde nihai raporu teslim eder. Bu tool'u çağırmak incelemeyi sonlandırır.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "PR'ın ne yaptığının ve genel değerlendirmenin 2-3 cümlelik özeti.",
                },
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string"},
                            "line": {"type": "integer"},
                            "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                            "title": {"type": "string"},
                            "detail": {"type": "string"},
                            "suggestion": {"type": "string"},
                        },
                        "required": ["file", "line", "severity", "title", "detail", "suggestion"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["summary", "findings"],
            "additionalProperties": False,
        },
    },
]


# --------------------------------------------------------------------------
# Yardımcılar
# --------------------------------------------------------------------------

def sh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, capture_output=True, text=True)


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... çıktı {limit} karakterde kesildi ...]"


def get_diff() -> str:
    base = os.environ["BASE_SHA"]
    head = os.environ["HEAD_SHA"]
    return truncate(sh("git", "diff", f"{base}...{head}").stdout, MAX_DIFF_CHARS)


# --------------------------------------------------------------------------
# Tool implementasyonları (client tarafında, yani burada çalışır)
# --------------------------------------------------------------------------

def safe_path(raw: str) -> Path:
    """Model'in verdiği yolun repo kökü dışına çıkmasını engeller."""
    path = (REPO_ROOT / raw).resolve()
    if not path.is_relative_to(REPO_ROOT):
        raise ValueError(f"Repo dışına erişim engellendi: {raw}")
    return path


def tool_list_files(glob: str = "") -> str:
    args = ["git", "ls-files"]
    if glob:
        args += ["--", glob]
    out = sh(*args, check=False).stdout
    return out or "(eşleşen dosya yok)"


def tool_read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
    file_path = safe_path(path)
    lines = file_path.read_text(errors="replace").splitlines()
    end = end_line or len(lines)
    selected = lines[max(start_line, 1) - 1 : end]
    return "\n".join(f"{i}\t{line}" for i, line in enumerate(selected, start=max(start_line, 1)))


def tool_grep(pattern: str, path: str = "") -> str:
    args = ["git", "grep", "-n", "-I", "-E", pattern]
    if path:
        args += ["--", path]
    result = sh(*args, check=False)
    if result.returncode == 1:
        return "(eşleşme yok)"
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "grep hatası")
    return result.stdout


def execute_tool(name: str, tool_input: dict) -> str:
    if name == "list_files":
        return tool_list_files(tool_input.get("glob", ""))
    if name == "read_file":
        return tool_read_file(
            tool_input["path"],
            tool_input.get("start_line", 1),
            tool_input.get("end_line"),
        )
    if name == "grep":
        return tool_grep(tool_input["pattern"], tool_input.get("path", ""))
    raise ValueError(f"Bilinmeyen tool: {name}")


# --------------------------------------------------------------------------
# Agent döngüsü
# --------------------------------------------------------------------------

def run_agent(diff: str) -> dict | None:
    """Model çağır -> tool çalıştır -> sonucu geri besle döngüsü.

    submit_review çağrıldığında bulguları döner; model tool çağırmadan
    biterse None döner (fallback üst katmanda ele alınır).
    """
    client = anthropic.Anthropic()
    messages: list[dict] = [
        {"role": "user", "content": f"Aşağıdaki pull request diff'ini incele.\n\n=== PR DIFF ===\n{diff}"}
    ]

    total_in = total_out = 0
    for iteration in range(MAX_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens

        # Assistant cevabını (thinking + text + tool_use blokları dahil) geçmişe ekle
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "pause_turn":
            continue

        if response.stop_reason != "tool_use":
            break  # model tool çağırmadan bitirdi

        review: dict | None = None
        tool_results: list[dict] = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "submit_review":
                review = block.input
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "Review teslim alındı.",
                })
                continue
            try:
                output = truncate(execute_tool(block.name, block.input), MAX_TOOL_OUTPUT_CHARS)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })
            except Exception as exc:  # tool hatası modele bildirilir, döngü sürer
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Hata: {exc}",
                    "is_error": True,
                })

        # Tüm tool sonuçları tek bir user mesajında geri gider
        messages.append({"role": "user", "content": tool_results})

        if review is not None:
            print(f"Toplam token: {total_in} giriş / {total_out} çıkış ({iteration + 1} tur)")
            return review

    print(f"Toplam token: {total_in} giriş / {total_out} çıkış", file=sys.stderr)
    return None


# --------------------------------------------------------------------------
# GitHub'a raporlama
# --------------------------------------------------------------------------

def post_inline_comment(repo: str, pr: str, head_sha: str, finding: dict) -> bool:
    body = f"**{SEVERITY_BADGE.get(finding['severity'], '🔵')} — {finding['title']}**\n\n{finding['detail']}"
    if finding.get("suggestion"):
        body += f"\n\n**Öneri:** {finding['suggestion']}"
    result = sh(
        "gh", "api", f"repos/{repo}/pulls/{pr}/comments",
        "-f", f"body={body}",
        "-f", f"commit_id={head_sha}",
        "-f", f"path={finding['file']}",
        "-F", f"line={finding['line']}",
        "-f", "side=RIGHT",
        check=False,
    )
    if result.returncode != 0:
        # Satır diff içinde değilse GitHub 422 döner; bulgu özete taşınır
        print(f"Inline yorum eklenemedi ({finding['file']}:{finding['line']}): {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def format_finding_line(finding: dict) -> str:
    badge = SEVERITY_BADGE.get(finding["severity"], "🔵")
    line = f"- {badge} `{finding['file']}:{finding['line']}` — **{finding['title']}**: {finding['detail']}"
    if finding.get("suggestion"):
        line += f"\n  - Öneri: {finding['suggestion']}"
    return line


def post_summary(repo: str, pr: str, review: dict, leftover_findings: list[dict]) -> None:
    findings = review["findings"]
    lines = ["## 🤖 AI Code Review", "", review["summary"], ""]
    if not findings:
        lines.append("✅ Kayda değer bir sorun bulunamadı.")
    else:
        lines.append(f"**{len(findings)} bulgu** tespit edildi.")
        if leftover_findings:
            lines += ["", "### Satıra bağlanamayan bulgular", ""]
            lines += [format_finding_line(f) for f in leftover_findings]
    sh("gh", "pr", "comment", pr, "--repo", repo, "--body", "\n".join(lines))


def main() -> None:
    repo = os.environ["REPO"]
    pr = os.environ["PR_NUMBER"]
    head_sha = os.environ["HEAD_SHA"]

    diff = get_diff()
    if not diff.strip():
        print("Diff boş, review atlanıyor.")
        return

    review = run_agent(diff)
    if review is None:
        print("Agent submit_review çağırmadan bitti.", file=sys.stderr)
        sh("gh", "pr", "comment", pr, "--repo", repo,
           "--body", "## 🤖 AI Code Review\n\n⚠️ İnceleme tamamlanamadı, workflow loglarına bakın.")
        sys.exit(1)

    leftover: list[dict] = []
    for finding in review["findings"][:MAX_INLINE_COMMENTS]:
        if not post_inline_comment(repo, pr, head_sha, finding):
            leftover.append(finding)
    leftover += review["findings"][MAX_INLINE_COMMENTS:]

    post_summary(repo, pr, review, leftover)
    print(f"Review tamamlandı: {len(review['findings'])} bulgu.")


if __name__ == "__main__":
    main()
