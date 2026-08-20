# Roadmap

The MVP covers visualisation, editing, annotation, restriction analysis, primers,
alignment, projects/RBAC, jobs and deployment. This is the order in which the remaining
SnapGene-class capability should land, with the extension point each item plugs into.

## Next (high value, low risk)

1. **Assembly simulation** — Gibson / Golden Gate / restriction ligation that produces a
   *new* construct with merged annotations.
   *Where:* `app/bio/assembly.py` (new) reusing `digest.compatible_overhangs` and
   `edit.set_origin`; handler `assembly`; UI: a wizard tab in the workbench.
2. **AB1 / SCF chromatogram import** — parse trace files, show peaks above the alignment,
   flag low-quality miscalls.
   *Where:* `seqio.parse_ab1`, a `traces` JSON column on `sequences`, a canvas track in
   `SequenceViewer`.
3. **Batch operations** — apply a digest/primer design/annotation pass to every construct
   in a project and download a report.
   *Where:* a `batch` job handler that fans out over `sequence_ids`; the job result already
   supports arbitrary JSON.
4. **Undo/redo in the editor UI** — versions already exist server-side; the UI needs a
   keyboard-driven stack that calls `restore` on the right version.
5. **Print / PDF export of maps** — the plasmid map is already pure SVG; add a
   `?format=svg` export endpoint plus a print stylesheet.

## Then (deeper science)

6. **CRISPR guide design** — PAM scanning, on-target scoring (Doench), off-target search
   against a reference, guide features written back onto the construct.
   *Where:* `app/bio/crispr.py`, handler `crispr_guides`, new side-panel tab.
7. **Real BLAST integration** — submit to NCBI URLAPI (or a local `blastn`), poll the RID,
   render hits as tracks. The external registry and job queue already model both halves;
   only a result parser and a track renderer are missing.
8. **Progressive multiple alignment** — replace center-star with guide-tree progressive
   alignment (and optional MAFFT/MUSCLE shell-out when installed) for >10 sequences.
9. **Codon optimisation / back-translation** — species codon-usage tables, GC and repeat
   constraints, restriction-site avoidance.
10. **Protein view** — domains, secondary-structure annotation, hydropathy plots for CDS
    features.

## Platform hardening

11. **Rate limiting and quotas** per user/API key (Redis token bucket) — the queue is the
    only current backpressure.
12. **SSO** — OIDC/SAML login for institutional accounts; `services/users.py` already
    isolates credential handling.
13. **Object storage for uploads** — S3/MinIO instead of the local `storage/` volume, so
    the API becomes fully stateless.
14. **Field-level encryption + retention policy** for constructs classified as sensitive,
    and a documented GDPR-style export/delete path.
15. **Observability** — Prometheus metrics (`/metrics`), OpenTelemetry traces around
    services and job handlers, Sentry for exceptions.
16. **Test depth** — property-based tests (Hypothesis) for editing invariants
    (`length_after == length_before + delta`, feature containment), a Playwright suite
    replacing the ad-hoc headless checks, and a load profile for 100 kb constructs.

## Explicit non-goals

* Read mapping / variant calling at genome scale — that is a pipeline job (BWA, GATK),
  not a plasmid editor; GeneForge should *link* to those results instead.
* Structure prediction and molecular dynamics.
* Being a LIMS: inventory, freezer maps and ordering belong in an external system that
  GeneForge integrates with through the external-resource registry.
