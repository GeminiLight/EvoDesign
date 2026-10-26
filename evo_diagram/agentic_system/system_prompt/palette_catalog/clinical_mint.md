## clinical_mint

**display_name:** Clinical Mint

**digest:** Clinical pathways / hospital workflows / lab protocols / biotech-pharma processes.

**mood:** Hospital-corridor calm — primary teal on clinical white, with red kept strictly for true alarms.

**use_when:** Clinical pathways, hospital workflows, lab protocols, patient-journey diagrams, biotech and pharma processes — anywhere calm and order should read as the dominant tone.

**avoid_when:** Marketing and finance (reads as too soft), technical engineering content (too clinical, lacks gravitas), kid-facing education (not warm enough), creative brainstorming (too procedural). The palette demands a serious topic.

**reference_anchors:** Mayo Clinic patient portals, Epic clinical UIs, HL7 protocol diagrams, NIH study flow charts, FDA submission diagrams.

**balance_guidance:** Teal is the lead voice (~40%). Mint for follow-on success states. Sky for information and data inputs. Amber for decisions and intermediate steps. Alert (red) is strictly reserved for true clinical alarms — at most a couple of nodes. The diagram should feel like a calm corridor, never a fire alarm.

**common_mistakes:** Over-using alert dilutes its meaning — clinicians should see red only when something is genuinely wrong. Painting routine decisions in alert (amber is the right `needs attention` hue). Replacing teal with sky for general nodes — teal IS the clinical voice here.

**canvas:** `#F5F5F5`
**border_default:** `#10217D`
**accent_edge:** `#00838F`

### Fill Families

| name | fill | stroke | voice |
|------|------|--------|-------|
| teal | `#B2EBF2` | `#00838F` | The clinical voice — primary protocols, main-pathway anchors, the diagram's resting tone. |
| mint | `#D1FAE5` | `#065F46` | Success and follow-on states — completed steps, positive outcomes, `patient stable`. |
| sky | `#E0F2FE` | `#0369A1` | Information, data inputs, lab values, external data sources. |
| amber | `#FEF3C7` | `#92400E` | Decisions, intermediate steps, `needs attention but not alarm` — the routine clinical-judgment tone. |
| alert | `#FECACA` | `#B91C1C` | True alarms only — adverse events, critical failures, code-red states (<=5%). |
