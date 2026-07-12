#!/usr/bin/env python3
"""İnteraktif tartışma agent'ı — PR'da "/ai <soru>" yorumuna cevap verir.

Geliştirici bir review yorumuna veya PR'a "/ai bu neden önemli?" gibi bir soru
yazınca tetiklenir. Agent, PR diff'ini ve repo'yu (read_file/grep/list_files ile)
inceleyerek soruyu bağlam içinde yanıtlar ve cevabı PR'a yorum olarak bırakır.

Beklenen ortam değişkenleri:
  ANTHROPIC_API_KEY, GH_TOKEN, REPO, PR_NUMBER, BASE_SHA, HEAD_SHA
  QUESTION      - "/ai" önekinden sonraki kullanıcı sorusu
   COMMENT_URL   - (opsiyonel) tetikleyen yoruma 👀 reaksiyonu için API URL'i
"""

from __future__ import annotations

import os

import anthropic

# review_agent'taki salt-okunur tool altyapısını yeniden kullan
from review_agent import (
    MAX_DIFF_CHARS,
    MAX_ITERATIONS,
    MAX_TOOL_OUTPUT_CHARS,
    READ_TOOLS,
    execute_tool,
    get_diff,
    sh,
    truncate,
)

MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """\
Sen bu pull request'i inceleyen kıdemli yazılım mühendisisin. Geliştirici sana
review'la ilgili bir soru sordu. Soruyu, PR diff'i ve repo bağlamında yanıtla.

list_files, read_file ve grep tool'larıyla gerektiğinde koda bak. Cevabın:
- Doğrudan ve teknik olsun, gereksiz uzatma.
- Somut kod örneği gerekiyorsa ver (```dil bloklarıyla).
- Emin değilsen bunu belirt, uydurma.
- Türkçe yanıtla.

Cevabını normal metin olarak yaz; sonunda ayrı bir tool çağrısına gerek yok."""


def answer_question(question: str, diff: str) -> str:
    client = anthropic.Anthropic()
    messages: list[dict] = [{
        "role": "user",
        "content": (
            f"=== PR DIFF ===\n{diff}\n\n"
            f"=== GELİŞTİRİCİNİN SORUSU ===\n{question}"
        ),
    }]

    answer_parts: list[str] = []
    for _ in range(MAX_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=READ_TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        # Bu turda üretilen metni topla
        for block in response.content:
            if block.type == "text" and block.text.strip():
                answer_parts.append(block.text.strip())

        if response.stop_reason == "pause_turn":
            continue
        if response.stop_reason != "tool_use":
            break  # model cevabını verdi

        tool_results: list[dict] = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                output = truncate(execute_tool(block.name, block.input), MAX_TOOL_OUTPUT_CHARS)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
            except Exception as exc:
                tool_results.append({
                    "type": "tool_result", "tool_use_id": block.id,
                    "content": f"Hata: {exc}", "is_error": True,
                })
        messages.append({"role": "user", "content": tool_results})

    return "\n\n".join(answer_parts).strip()


def main() -> None:
    repo = os.environ["REPO"]
    pr = os.environ["PR_NUMBER"]
    question = os.environ.get("QUESTION", "").strip()

    # Tetikleyici "/ai" (veya "/ai:") önekini soru metninden temizle
    for prefix in ("/ai:", "/ai"):
        if question.lower().startswith(prefix):
            question = question[len(prefix):].strip()
            break

    if not question:
        print("Soru boş, atlanıyor.")
        return

    diff = truncate(get_diff(), MAX_DIFF_CHARS)
    answer = answer_question(question, diff)
    if not answer:
        answer = "Bu soruya cevap üretemedim, workflow loglarına bakın."

    body = f"## 🤖 AI Yanıt\n\n**Soru:** {question}\n\n{answer}"
    sh("gh", "pr", "comment", pr, "--repo", repo, "--body", body)
    print("Yanıt gönderildi.")


if __name__ == "__main__":
    main()
