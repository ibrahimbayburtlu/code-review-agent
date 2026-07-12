# 🤖 AI Code Review Agent

[![AI Code Review](https://github.com/ibrahimbayburtlu/code-review-agent/actions/workflows/claude-review.yml/badge.svg)](https://github.com/ibrahimbayburtlu/code-review-agent/actions/workflows/claude-review.yml)

PR açıldığında diff'i inceleyip bulguları **inline yorum** ve **kategorili özet**
olarak PR'a bırakan, sıfırdan yazılmış bir code review agent'ı.

Hazır bir agent framework'ü kullanılmaz: agent döngüsü, tool tanımları ve tool
implementasyonları tamamen [`agent/review_agent.py`](agent/review_agent.py)
içindedir. Claude yalnızca `anthropic` SDK üzerinden model olarak çağrılır.

## Nasıl çalışır?

```
PR açılır / güncellenir
   └─▶ GitHub Actions (.github/workflows/claude-review.yml)
        └─▶ agent/review_agent.py
             ├─ git diff base...head alınır
             ├─ AGENT DÖNGÜSÜ (elle yazılmış):
             │    ┌─▶ client.messages.create(tools=[...])
             │    │     ├─ tool_use → list_files / read_file / grep
             │    │     │   runner'da çalıştırılır, sonuç modele geri gider ──┐
             │    │     └─ submit_review çağrıldı → döngü biter               │
             │    └──────────────────────────────────────────────────────────┘
             ├─ Her bulgu ilgili satıra inline yorum (gh api)
             ├─ Kategorilere gruplu özet yorum (gh pr comment)
             └─ FAIL_ON kuralı eşleşirse PR check'i fail olur
```

Agent'ın tool'ları:

| Tool | Ne yapar |
|---|---|
| `list_files` | `git ls-files` ile dosyaları listeler |
| `read_file` | Dosyayı satır numaralarıyla okur (repo kökü dışına çıkamaz) |
| `grep` | `git grep -n -E` ile regex araması |
| `submit_review` | Nihai raporu `strict: true` şemalı JSON olarak teslim eder, döngüyü bitirir |

## Review kategorileri

Her bulgu tam olarak bir kategoriye atanır; özet yorum kategori bazında gruplanır:

| Kategori | Kapsam |
|---|---|
| 🛡️ `security` | Injection, secret sızıntısı, eksik yetki kontrolü, güvensiz kripto |
| 🐛 `bug` | Mantık hataları, sınır durumları, yarış koşulları, kaynak sızıntıları |
| ⚡ `performance` | N+1 sorgular, döngü içi I/O, verimsiz algoritma seçimi |
| 🏗️ `architecture` | Yanlış katman, sıkı bağlılık, repo desenleriyle uyumsuzluk |
| 🧪 `test` | Değişen davranış için eksik/yanlış test |

## Başka bir projede kullanma (önerilen yol)

Agent'ı her projeye kopyalamana gerek yok — bu repo **reusable workflow** olarak
çağrılır. Herhangi bir projende, proje kökünden iki komut:

```bash
mkdir -p .github/workflows
curl -fsSL https://raw.githubusercontent.com/ibrahimbayburtlu/code-review-agent/main/templates/caller-workflow.yml \
  -o .github/workflows/ai-review.yml

gh secret set ANTHROPIC_API_KEY   # anahtarı gizli olarak yapıştır
```

Commit'le, PR aç — bitti. Agent kodu her çalışmada bu repo'nun `main`'inden
çekilir; agent'ı burada geliştirdikçe bütün projelerin otomatik güncel kalır.

Çağıran dosyada kategori ve fail gate proje bazında ayarlanabilir:

```yaml
jobs:
  review:
    uses: ibrahimbayburtlu/code-review-agent/.github/workflows/reusable-review.yml@main
    with:
      categories: "security,bug"     # bu projede sadece güvenlik + bug
      fail_on: "security:high"       # kritik güvenlik bulgusunda check fail
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

> Sürüm sabitlemek istersen `@main` yerine bir tag veya commit SHA kullan.

## Kurulum (bu repo'nun kendisi için)

1. [console.anthropic.com](https://console.anthropic.com) → API key oluştur
   (öneri: ayrı bir workspace + harcama limiti ile).
2. Repo'da **Settings → Secrets and variables → Actions** altına
   `ANTHROPIC_API_KEY` secret'ını ekle:
   ```bash
   gh secret set ANTHROPIC_API_KEY
   ```
3. PR aç — review 1-2 dakika içinde düşer.

## Yapılandırma

Workflow'daki (`.github/workflows/claude-review.yml`) ortam değişkenleri:

```yaml
# Hangi kategoriler çalışsın (alt küme seçilebilir):
REVIEW_CATEGORIES: "security,bug,performance,architecture,test"

# Hangi bulgular PR check'ini kırmızıya düşürsün (fail gate):
FAIL_ON: ""                           # boş = hiç fail etme (varsayılan)
# FAIL_ON: "security:high"            # yüksek önemli güvenlik bulgusunda fail
# FAIL_ON: "security:medium,bug:high" # birden çok kural
# FAIL_ON: "any:high"                 # kategori fark etmeksizin tüm yüksek bulgular
```

`FAIL_ON`'u branch protection ile birleştirirsen "kritik bulgusu olan PR merge
edilemez" kuralına dönüşür.

## Yerelde çalıştırma

```bash
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...
export GH_TOKEN=$(gh auth token)
export REPO=owner/repo
export PR_NUMBER=123
export BASE_SHA=$(git merge-base origin/main HEAD)
export HEAD_SHA=$(git rev-parse HEAD)

python agent/review_agent.py
```

## Özelleştirme

- **Yeni kategori:** `CATEGORIES` sözlüğüne emoji + başlık + yönlendirme metni
  ekle — şema, sistem prompt'u ve raporlama otomatik uyum sağlar.
- **Yeni tool:** `build_tools()` içine şemayı, `execute_tool()` içine
  implementasyonu ekle (örn. testleri çalıştıran `run_tests`).
- **Model:** `MODEL` sabiti (varsayılan `claude-opus-4-8`; daha ucuz/hızlı
  review için `claude-sonnet-5`).
- **Limitler:** `MAX_ITERATIONS`, `MAX_INLINE_COMMENTS`, `MAX_DIFF_CHARS`,
  `MAX_TOOL_OUTPUT_CHARS`.

## Güvenlik notları

- Agent'ın tool'ları yalnızca **okuma** yapar; `read_file` ve `grep` repo kökü
  dışına erişemez (`safe_path`).
- Fork'lardan gelen PR'larda GitHub secret'ları vermez; agent yalnızca aynı
  repo içindeki branch PR'larında çalışır.
- Satırı diff dışında kalan bulgular (GitHub 422) otomatik olarak özet yoruma
  taşınır; model `submit_review` çağırmadan biterse workflow fail olur ve PR'a
  uyarı düşer.
