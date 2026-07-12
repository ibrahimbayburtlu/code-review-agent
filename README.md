<div align="center">

# 🤖 AI Code Review Agent

**Her pull request'i kıdemli bir mühendis gibi inceleyen, sıfırdan yazılmış bir AI code review agent'ı.**

Bulguları kategorilere ayırır, güven skoru ve düzeltme önerisiyle ilgili satıra bırakır,
PR için bir karar ve release risk skoru üretir — ve `/ai` ile onunla tartışabilirsin.

[![AI Code Review](https://github.com/ibrahimbayburtlu/code-review-agent/actions/workflows/claude-review.yml/badge.svg)](https://github.com/ibrahimbayburtlu/code-review-agent/actions/workflows/claude-review.yml)
&nbsp;![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
&nbsp;![Claude](https://img.shields.io/badge/Claude-Opus%204.8-8B7CFF)
&nbsp;![GitHub Actions](https://img.shields.io/badge/GitHub-Actions-2088FF?logo=githubactions&logoColor=white)

</div>

---

## Neden farklı?

Hazır bir agent framework'ü **kullanılmıyor**. Agent döngüsü (model çağır → tool çalıştır →
sonucu geri besle), tool tanımları ve implementasyonları tamamen
[`agent/review_agent.py`](agent/review_agent.py) içinde. Claude yalnızca `anthropic`
SDK üzerinden bir model olarak çağrılıyor — gerisi bu repo'nun kodu.

## Öne çıkan özellikler

| | Özellik | Açıklama |
|---|---|---|
| 🏷️ | **Kategori bazlı inceleme** | Güvenlik · Bug · Performans · Mimari · Test — her bulgu bir kategoride |
| ⚠️ | **5 önem seviyesi** | Kritik → Yüksek → Orta → Düşük → Bilgi |
| 📊 | **Güven skoru + gerekçe** | Her bulguda `%0–100` güven ve tek cümlelik neden |
| 🔧 | **Auto-fix önerileri** | GitHub'ın tek tıkla uygulanabilir `suggestion` formatında |
| 🎯 | **Karar + risk skoru** | `Approve / Comment / Request Changes` + `0–100` release riski |
| 🎭 | **Reviewer kişilikleri** | strict · mentor · clean-code · paranoid |
| 💬 | **İnteraktif tartışma** | PR'a `/ai <soru>` yazınca agent kod bağlamında yanıtlar |
| 🚦 | **Check gate'leri** | Belirli bulgu veya risk eşiğinde PR check'ini kırmızıya düşür |
| ♻️ | **Tek yerden dağıtım** | Reusable workflow — her projeye ~15 satırlık tek dosyayla kurulur |

## Nasıl çalışır?

```
PR açılır / güncellenir
   └─▶ GitHub Actions (.github/workflows/claude-review.yml)
        └─▶ agent/review_agent.py
             ├─ git diff base...head alınır
             ├─ AGENT DÖNGÜSÜ (elle yazılmış):
             │    ┌─▶ client.messages.create(tools=[…])
             │    │     ├─ tool_use → list_files / read_file / grep
             │    │     │   çalıştırılır, sonuç modele geri gider ──┐
             │    │     └─ submit_review çağrıldı → döngü biter     │
             │    └───────────────────────────────────────────────┘
             ├─ Her bulgu ilgili satıra inline yorum (gh api)
             ├─ Kategorilere gruplu özet + karar + risk (gh pr comment)
             └─ Gate eşleşirse PR check'i fail olur
```

Agent'a verilen tool'lar — üçü salt-okunur, biri raporu teslim eder:

| Tool | Ne yapar |
|---|---|
| `list_files` | `git ls-files` ile dosyaları listeler |
| `read_file` | Dosyayı satır numaralarıyla okur (`safe_path` ile repo kökü dışına çıkamaz) |
| `grep` | `git grep -n -E` ile regex araması yapar |
| `submit_review` | Raporu `strict: true` şemalı JSON olarak teslim eder ve döngüyü bitirir |

## Hızlı başlangıç

Başka bir projeye kurmak için agent'ı kopyalamana gerek yok — bu repo **reusable
workflow** olarak çağrılır. Proje kökünde iki komut yeterli:

```bash
mkdir -p .github/workflows
curl -fsSL https://raw.githubusercontent.com/ibrahimbayburtlu/code-review-agent/main/templates/caller-workflow.yml \
  -o .github/workflows/ai-review.yml

gh secret set ANTHROPIC_API_KEY   # anahtarı gizli olarak yapıştır
```

Commit'le, PR aç — review 1–2 dakika içinde düşer. Agent kodu her çalışmada bu repo'nun
`main` dalından çekilir, yani agent burada geliştirdikçe tüm projelerin otomatik güncel kalır.

> **API anahtarı:** [console.anthropic.com](https://console.anthropic.com) üzerinden oluştur.
> Öneri: CI için ayrı bir workspace + harcama limiti tanımla.

İnteraktif `/ai <soru>` özelliğini de istersen
[`templates/discuss-workflow.yml`](templates/discuss-workflow.yml) dosyasını
`.github/workflows/ai-discuss.yml` olarak kopyala.

## Yapılandırma

Çağıran workflow'da her şey proje bazında ayarlanır:

```yaml
jobs:
  review:
    uses: ibrahimbayburtlu/code-review-agent/.github/workflows/reusable-review.yml@main
    with:
      categories: "security,bug,performance,architecture,test"  # alt küme seçilebilir
      persona: "default"          # strict | mentor | clean-code | paranoid
      fail_on: ""                 # örn: "security:high" veya "any:critical"
      max_risk_score: ""          # örn: "70" → risk > 70 ise check fail
      min_confidence: "0"         # örn: "60" → güveni <60 olan bulgular gizlenir
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

| Parametre | Ne işe yarar |
|---|---|
| `categories` | Çalışacak review türleri |
| `persona` | Reviewer üslubu (yalnızca prompt davranışını değiştirir) |
| `fail_on` | `kategori:min_önem` kuralları — eşleşen bulgu varsa check fail |
| `max_risk_score` | Risk skoru eşiği — aşılırsa check fail |
| `min_confidence` | Bu güven skorunun altındaki bulguları gizle |

> `fail_on` / `max_risk_score`'u branch protection ile birleştirirsen
> "kritik bulgusu olan PR merge edilemez" kuralına dönüşür.
> Sürüm sabitlemek için `@main` yerine bir tag veya commit SHA kullan.

## Review kategorileri

| Kategori | Kapsam |
|---|---|
| 🛡️ `security` | Injection, secret sızıntısı, eksik yetki kontrolü, güvensiz kripto |
| 🐛 `bug` | Mantık hataları, sınır durumları, yarış koşulları, kaynak sızıntıları |
| ⚡ `performance` | N+1 sorgular, döngü içi I/O, verimsiz algoritma seçimi |
| 🏗️ `architecture` | Yanlış katman, sıkı bağlılık, repo desenleriyle uyumsuzluk |
| 🧪 `test` | Değişen davranış için eksik/yanlış test |

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

## Proje yapısı

```
agent/
  review_agent.py       # ana review agent'ı — döngü, tool'lar, raporlama
  discuss_agent.py      # /ai <soru> için interaktif tartışma agent'ı
.github/workflows/
  claude-review.yml     # bu repo'nun PR review tetikleyicisi
  reusable-review.yml   # dışarıdan çağrılabilen paylaşımlı workflow
  ai-discuss.yml        # /ai yorumlarını yakalayan workflow
templates/
  caller-workflow.yml   # başka projelere kopyalanacak review şablonu
  discuss-workflow.yml  # başka projelere kopyalanacak tartışma şablonu
requirements.txt
```

## Özelleştirme

- **Yeni kategori:** `CATEGORIES` sözlüğüne emoji + başlık + yönlendirme metni ekle —
  şema, sistem prompt'u ve raporlama otomatik uyum sağlar.
- **Yeni persona:** `PERSONAS` sözlüğüne bir üslup metni ekle.
- **Yeni tool:** `build_tools()` içine şemayı, `execute_tool()` içine implementasyonu ekle
  (örn. testleri çalıştıran bir `run_tests`).
- **Model:** `MODEL` sabiti — varsayılan `claude-opus-4-8`; daha ucuz/hızlı review için `claude-sonnet-5`.
- **Limitler:** `MAX_ITERATIONS`, `MAX_INLINE_COMMENTS`, `MAX_DIFF_CHARS`, `MAX_TOOL_OUTPUT_CHARS`.

## Güvenlik notları

- Agent'ın tool'ları yalnızca **okuma** yapar; `read_file` ve `grep`, `safe_path` ile
  repo kökü dışına erişemez.
- Fork'lardan gelen PR'larda GitHub secret'ları vermez; agent yalnızca aynı repo içindeki
  branch PR'larında çalışır.
- Satırı diff dışında kalan bulgular (GitHub 422) otomatik olarak özet yoruma taşınır;
  model `submit_review` çağırmadan biterse workflow fail olur ve PR'a bir uyarı düşer.

---

<div align="center">
<sub>Python · Anthropic API (Claude) · GitHub Actions ile geliştirildi.</sub>
</div>
