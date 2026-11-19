# ADR-004: Citation traceability

## Context

RevB §6.1 requires every factual sentence to bind to retrieved span identifiers; §8.3 separately measures citation existence and claim support.

## Decision

Persist citation objects and claim-to-`chunk_id` bindings with each Tutor turn, plus corpus/policy version. Treat title/excerpt strings as presentation data, not identity.

## Consequences

The current chunk identifier is the compatibility provenance ID. Before the experiment freeze it must be upgraded to an immutable corpus item/document version/offset/hash span identity; the LQS must reference that immutable form.

## Revision 2026-11-19 (Phase 2: immutable span identity, resolver and legacy migration)

Status: accepted for Phase 2 engineering. It implements plan tasks 2.2-2.4 and Phase 2 G. The D-30 rule is **provisional** (P1-D-18). The full design is `docs/architecture/phase2-implementation-spec.md`; the decision above stays as history.

### Span identity (span-v2)
- **The record.** A span is `(item_id, item_version, section_ordinal, start, end, content_hash)` over the item's deterministic canonical text (`sections-v1`).
  - A document's canonical text is its `parse_docx_sections` output joined as heading, `\n\n`, body, with sections separated by `\n\n\n`.
  - The authored item `authored-curriculum` is the lesson text of `MODULE_BLUEPRINTS`.
  - Spans are the pinned splitter's chunks (langchain-text-splitters 1.1.2, 700/120), placed with LangChain's `add_start_index` rule.
  - `content_hash` is the sha256 of the full span text.
- **The id.**
  - `span_id = "span-" + sha256(canonical JSON {scheme, item_id, start, end, content_hash})`.
  - `item_id` is always `source_asset_id(filename, kind)` or `authored-curriculum`, never a free-form manifest id [R9]. A 2.0 manifest item whose id differs from that rule fails to load.
- **What stays out of the id.** `corpus_version`, `item_version`, licence and approval fields and lesson slugs never enter it.
  - Ids are stable across rebuilds (AC-2-1).
  - A licence edit rotates none (AC-2-2).
  - This is the E-45 fix. The deviation from plan 11.2 is that `item_version` and `section_ordinal` are fields, not id inputs, so a re-save with no text change rotates nothing (spec conflict 2).
- **Offsets are item-global.** An edit early in an item rotates the ids of later spans.
  - Old ids keep resolving through the append-only, text-free `corpus_spans` table. Database triggers refuse UPDATE, DELETE and TRUNCATE.
  - The request path writes cited spans through to that table (`SPAN_REGISTRY_WRITE_THROUGH`). `app.workers.register_spans` registers the rest on demand.
  - Start-up never writes span rows.

### `corpus_version` and `index_version`
- **`corpus_version`** (corpus-version-v2) hashes the sorted `(item_id, version, sha256, plane, bound)` of every manifest item, plus the span scheme. It is content and membership only.
- **`index_version`** also captures what is served: the entries, their lessons, the retrieval configuration and the active gate. It changes on partial approval (plan 11.1). Citations store `corpus_version`, and `/ready` reports both values.

### Resolver
- `SpanResolver` and `GET /spans/{span_id}` (task 2.4) are read-only.
  - They resolve from the current build, then from `corpus_spans`.
  - They never resolve a non-public plane, and take no learner input (invariant 1).
- **The route** returns 404 unless `SPAN_RESOLVER_ROUTE_ENABLED`: on in development, off elsewhere, under the freeze.
  - In a governed build, a document span of an item that is not approved is also a 404.
  - Every 404 carries `Cache-Control: no-store`.
- **Excerpts.** The route returns an excerpt only for a servable span: current, public plane, of a bound and approved document. Under D-31 there is none.

### Citation v2 and dual-read
- **New fields.** A citation gains `citation_schema` (2), `item_id`, `item_version`, `start`, `end`, `resolution` (`resolved` or `legacy_unresolved`), `migration_status`, `unresolved_reason`, `legacy_chunk_id`, `legacy_span_id`, `near_floor` and `label`.
- **Compatibility.** `chunk_id` stays and equals `span_id`.
- **Shape detection.** The shape is read from `citation_schema`, never from the id form.
- **Dual-read.** Readers accept the v0 (2026-04-05 build), v1 (Phase 1) and v2 shapes, for two releases (plan 11.2).
- **Quoting (D-19 containment).** `contain_answer` quotes only citations that the span registry verifies. The quotation is the span's own text, so a forged or tampered citation can never put words in it.

### Legacy migration (task 2.3; D3; plan G)
- **The match rule.** A stored v0 or v1 citation migrates only when the sha256 of its whitespace-normalised excerpt equals the excerpt key of exactly one span. There are two keys:
  - lexical: the display excerpt as the lexical path built it, truncated twice;
  - semantic: truncated once.
- **Diagnostics only.** Title equality, excerpt containment (plan 11.2) and the v1 `content_hash` agreement are reported and never change the outcome [R5]. A stricter rule would turn hash-unique citations into unresolved ones, which is D-30's own stop condition.
- **Unresolved citations.** Video citations are `chapter_summary_excluded` (task 2.7). All others that do not migrate are `legacy_unresolved` with a reason, are labelled "unverified historical reference", and stay provisional.
- **Reversibility.** Every rewritten element keeps `legacy_original`. `--downgrade` restores it.
  - A row is rewritten only when its stored text is exactly what SQLAlchemy's JSON type writes (`json.dumps`). The restored `CAST(col AS TEXT)` is then byte-for-byte the original on SQLite and on PostgreSQL `json` [R6].
  - Writes are a compare-and-set on that text. `--dry-run` writes nothing.
- **D-30 (provisional; P1-D-18; configuration package `legacy_citations`).** The run stops (exit 3) in any of three cases:
  - a citation the Phase 2 pipeline created does not resolve (native threshold 0);
  - a previously exact-match citation would become unresolved;
  - in `--apply`, a non-canonical row was skipped.
- **The share of legacy citations left unresolved** is reported with a Wilson interval. It is not gated.

### The reading of AC-2-3
AC-2-3 reads: "Every stored or returned citation resolves". This revision, the spec and the tests (`tests/test_phase2_acceptance.py`) read it as follows:
- every citation the Phase 2 pipeline stores or returns resolves: it is `resolved`, the resolver finds it, and its `content_hash` is equal;
- every migrated citation resolves;
- a `legacy_unresolved` citation is never returned as resolved. It is either withheld, or labelled `legacy_unresolved`, `provisional: true` and "unverified historical reference". Two cases are withheld:
  - answers stored before containment (R1.2);
  - in governed builds, citations of items the manifest does not approve [R13].

### The provisional marker (plan G; AC-1-13)
- `provisional = not (CITATION_PROVISIONAL_LIFT_ENABLED and resolution == "resolved")`.
- The flag defaults off, because lifting the marker removes a learner-visible label under the freeze.
- Enabling it outside development logs a `config.override` event. It also needs AC-2-3 green in a cited CI run and D-05 approval (spec conflict 7).
