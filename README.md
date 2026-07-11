# AI Code Review Agent (sıfırdan)

GitHub'a bir PR açıldığında diff'i inceleyip bulguları PR'a **inline yorum** ve
**özet yorum** olarak bırakan, hazır harness kullanmadan sıfırdan yazılmış bir
code review agent'ı. Agent döngüsü, tool tanımları ve tool implementasyonları
tamamen [agent/review_agent.py](agent/review_agent.py) içindedir; Claude yalnızca
`anthropic` SDK üzerinden model olarak çağrılır.

## Mimari

```
PR açılır/güncellenir
   └─▶ GitHub Actions workflow (.github/workflows/claude-review.yml)
        └─▶ agent/review_agent.py
             ├─ git diff base...head alınır
             ├─ AGENT DÖNGÜSÜ (elle yazılmış):
             │    ┌─▶ client.messages.create(tools=[...])
             │    │     ├─ stop_reason == "tool_use" ise:
             │    │     │    list_files / read_file / grep → burada çalıştırılır,
             │    │     │    sonuç tool_result olarak modele geri gönderilir ──┐
             │    │     └─ submit_review çağrıldıysa → döngü biter             │
             │    └───────────────────────────────────────────────────────────┘
             ├─ Her bulgu ilgili satıra inline yorum olarak eklenir (gh api)
             └─ PR'a genel özet yorumu bırakılır (gh pr comment)
```

Agent'a verilen tool'lar:

| Tool | Ne yapar | Nerede çalışır |
|---|---|---|
| `list_files` | `git ls-files` ile dosyaları listeler | Runner'da (bizim kodumuz) |
| `read_file` | Dosyayı satır numaralarıyla okur (repo kökü dışına çıkamaz) | Runner'da |
| `grep` | `git grep -n -E` ile regex araması | Runner'da |
| `submit_review` | Nihai raporu yapılandırılmış JSON olarak teslim eder (`strict: true` şema) | Döngüyü sonlandırır |

`submit_review`'un `strict: true` olması sayesinde bulgular şemaya birebir uygun
gelir — çıktıdan JSON kazımaya gerek kalmaz.

## Kurulum

1. **API anahtarı al:** [console.anthropic.com](https://console.anthropic.com) → API Keys.

2. **Secret ekle:** GitHub repo'nda **Settings → Secrets and variables → Actions →
   New repository secret** ile `ANTHROPIC_API_KEY` adında ekle.
   (`GITHUB_TOKEN`'ı Actions otomatik sağlar, ekstra bir şey gerekmez.)

3. **Bu dosyaları repo'na kopyala** (veya bu klasörü repo yap):
   - `.github/workflows/claude-review.yml`
   - `agent/review_agent.py`
   - `requirements.txt`

4. **PR aç.** Workflow otomatik çalışır ve birkaç dakika içinde review yorumları düşer.

## Yerelde test etme

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

## Review kategorileri

Her bulgu bir kategoriye atanır; özet yorum kategori bazında gruplanır:

| Kategori | Kapsam |
|---|---|
| 🛡️ `security` | Injection, secret sızıntısı, eksik yetki kontrolü, güvensiz kripto |
| 🐛 `bug` | Mantık hataları, sınır durumları, yarış koşulları, kaynak sızıntıları |
| ⚡ `performance` | N+1 sorgular, döngü içi I/O, verimsiz algoritma seçimi |
| 🏗️ `architecture` | Yanlış katman, sıkı bağlılık, repo desenleriyle uyumsuzluk |
| 🧪 `test` | Değişen davranış için eksik/yanlış test |

Workflow'daki iki ortam değişkeniyle kontrol edilir:

```yaml
# Hangi kategoriler çalışsın (alt küme seçilebilir):
REVIEW_CATEGORIES: "security,bug"

# Hangi bulgular PR check'ini kırmızıya düşürsün (fail gate):
FAIL_ON: "security:high"          # yüksek önemli güvenlik bulgusu varsa fail
# FAIL_ON: "security:medium,bug:high"  # birden çok kural
# FAIL_ON: "any:high"                  # kategori fark etmeksizin tüm yüksek bulgular
# FAIL_ON: ""                          # hiç fail etme (varsayılan)
```

Yeni bir kategori eklemek için `agent/review_agent.py` içindeki `CATEGORIES`
sözlüğüne emoji + başlık + yönlendirme metniyle bir kayıt eklemek yeterli —
şema, sistem prompt'u ve raporlama otomatik uyum sağlar.

## Özelleştirme

- **Review odağı:** kategori `guidance` metinlerini veya `SYSTEM_PROMPT_TEMPLATE`'i
  düzenle (örn. belirli klasörleri yok sayma).
- **Model:** `MODEL` sabiti (varsayılan `claude-opus-4-8`; daha ucuz/hızlı review
  için `claude-sonnet-5`).
- **Yeni tool eklemek:** `build_tools()` içine şemayı ekle, `execute_tool()` içine
  implementasyonunu yaz — örn. testleri çalıştıran bir `run_tests` tool'u.
- **Limitler:** `MAX_ITERATIONS` (agent tur sayısı), `MAX_INLINE_COMMENTS`,
  `MAX_DIFF_CHARS`, `MAX_TOOL_OUTPUT_CHARS`.

## Notlar

- Agent'ın tool'ları yalnızca **okuma** yapar; `read_file` ve `grep`, repo kökü
  dışına erişimi engeller (`safe_path`).
- Bir bulgunun satırı diff içinde değilse GitHub inline yorumu reddeder (422);
  bu bulgular otomatik olarak özet yorumuna taşınır.
- Model `submit_review` çağırmadan biterse workflow başarısız olur ve PR'a bir
  uyarı yorumu düşer.
- Fork'lardan gelen PR'larda secret'lar workflow'a verilmez; agent yalnızca
  aynı repo içindeki branch'lerden açılan PR'larda çalışır.
