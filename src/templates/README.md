# Skabeloner — AIScore & InsideAI

To skabeloner til kundekommunikation. Begge bruger `{{VARIABEL}}`-syntax til variable felter.

---

## 1. AIScore Rapport (`aiscore-report.html`)

6-siders PDF-rapport. Print via browser → Print → Gem som PDF.

| Variabel | Eksempel |
|---|---|
| `{{COMPANY_NAME}}` | Acme A/S |
| `{{ANALYSIS_DATE}}` | 22. april 2026 |
| `{{OVERALL_SCORE}}` | 74 |
| `{{SYSTEMS_ANALYZED}}` | 5 |
| `{{QUERIES_RUN}}` | 240 |
| `{{RANK}}` | 1 |
| `{{CONTACT_EMAIL}}` | hello@insideai.dk |

**Gentagne blokke** (AI-systemrækker, detailkort, anbefalinger): kopiér template-kommentarblokke og fyld data ind.

**NÆVNT / VALGT:** Brug `tag-chosen` (grøn), `tag-mentioned` (blå), `tag-not-mentioned` (grå) på status-tags.

---

## 2. InsideAI Alarm E-mail (`insideai-alert-email.html`)

HTML e-mail. Test i Litmus eller Email on Acid inden udsendelse.

| Variabel | Retningslinje |
|---|---|
| `{{COMPANY_NAME}}` | Modtagers virksomhedsnavn |
| `{{ALARM_HEADLINE}}` | Én sætning, max 80 tegn — konsekvens, ikke data |
| `{{ALARM_CONTEXT}}` | 2-3 sætninger — hvad sker der |
| `{{ALARM_ACTION}}` | 1-2 sætninger — hvad bør de overveje |
| `{{ALARM_URGENCY}}` | `HOJ PRIORITET` / `MIDDEL PRIORITET` / `LAV PRIORITET` |
| `{{ALARM_DATE}}` | Dato + tidspunkt |
| `{{AI_SYSTEM}}` | fx "ChatGPT, Gemini" |
| `{{CONTACT_URL}}` | Dashboard-link |
| `{{CONTACT_EMAIL}}` | Kontaktmail |
| `{{UNSUBSCRIBE_URL}}` | Afmeld-link |

**Urgency badge-farve** (redigér baggrund på `.urgency-badge`):
- HOJ → `#b91c1c`
- MIDDEL → `#b45309`
- LAV → `#1d4ed8`

**Tekstformat:** `[konsekvens] → hvad I bør overveje`
Eksempel: *"ChatGPT vælger nu [konkurrent] i 3 ud af 4 forespørgsler i jeres kategori → I mister synlighed hos den mest brugte AI-assistent. Overvej at opdatere jeres faglige indhold med fokus på [nøglebegreber]."*

**Afvent Saras konsekvensformulerings-framework** inden I finpudser `{{ALARM_HEADLINE}}` og `{{ALARM_ACTION}}` teksterne. Layoutet er klar til at modtage det framework.
