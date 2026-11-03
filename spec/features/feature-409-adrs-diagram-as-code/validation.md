# Validation Criteria: Feature 4.9 — Architecture Decision Records (ADRs) & Diagram-as-Code

## 1. Success Definition
Feature 4.9 is successful when: all 9 Arabic ADRs, the index, the template, and `spec/architecture.md` (6 Mermaid diagrams) exist and satisfy R1–R3; `tests/test_architecture_docs.py` passes on the real repository **and** demonstrably fails when drift is injected; `docs.yml` is valid and scoped; the full existing test suite still passes; and the supervisor visually confirms that diagrams render correctly with RTL prose.

Discovered repository capabilities: `uv` package manager, `pytest` + `pytest-asyncio` (`testpaths = ["tests"]`), `ruff` (line-length 100). No `mypy`, no Node/mermaid-cli.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- [ ] `tests/test_architecture_docs.py` unit checks pass against the real repo:
  - 9 ADR files exist and appear in `spec/adr/README.md` (R4.1).
  - Each ADR has Status / Date / Related Feature / Code References and the 4 markers `(Context)`, `(Decision)`, `(Alternatives Rejected)`, `(Consequences)` (R4.2).
  - Every referenced path exists (R4.3); every referenced config key is in `Settings.model_fields` (R4.4).
  - `architecture.md` has exactly 6 Mermaid blocks of the required types and `classDef planned` (R4.5).

### Tier 2: Integration Verification
- **Status**: Not Applicable
- **Technical Justification**: The feature adds static Markdown documents and a file-reading test. There is no runtime collaboration between services, no database, no LLM/RAG call, and no state mutation. The only cross-component touchpoint (docs ↔ `src/config.Settings` field names, docs ↔ filesystem paths) is already covered by Tier 1 assertions R4.3/R4.4.

### Tier 3: Error & Edge-Case Verification (Drift Injection)
Prove the guard actually catches drift (performed on a scratch copy / reverted immediately):
- [ ] Rename a referenced path inside an ADR's Code References to `src/ai_core/does_not_exist.py` → test fails naming the ADR and path.
- [ ] Reference a non-existent config key (e.g. `cache_semantic_thresholdX`) → test fails naming the key.
- [ ] Remove the `## العواقب (Consequences)` heading from one ADR → test fails naming the ADR and missing section.
- [ ] Delete one Mermaid block from `architecture.md` → test fails reporting 5 ≠ 6.
- [ ] Remove an ADR row from `README.md` → test fails naming the missing ADR.
- [ ] Boundary: an ADR with exactly 2 alternatives passes R1.5 review; manual check that each ADR lists ≥ 2.

### Tier 4: Regression Checks
- [ ] Full suite passes with no new failures versus the baseline before this feature: `uv run pytest -q`.
- [ ] `git diff --stat src/` shows **zero** changes (C1).
- [ ] `git diff .github/workflows/evals.yml` is empty (C5); `pyproject.toml` unchanged (C3).

### Tier 5: Build, Lint & Type Checks
- [ ] `uv run ruff check tests/test_architecture_docs.py` → no errors.
- [ ] `docs.yml` is valid YAML: `uv run python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/docs.yml', encoding='utf-8'))"` (PyYAML is available transitively; if not, verification falls back to GitHub Actions run on push).
- Type checks: **Not Applicable** — no type checker (`mypy`/`pyright`) is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- [ ] Open `spec/architecture.md` in VS Code Markdown Preview (with Mermaid support) or on GitHub after push: all 6 diagrams render without "Syntax error".
- [ ] Planned components (LiveKit worker, Deepgram, ElevenLabs, Prometheus/Grafana, SSO, ECS) appear dashed/differently styled with `[Planned]`.
- [ ] Arabic prose is right-aligned and readable in each ADR and in `architecture.md`.
- [ ] Spot-check ADR values against code: ADR 008 → `cache_semantic_threshold = 0.97`; ADR 003 → `gemini_fallback_model = gemini-2.0-flash` and circuit breaker threshold; ADR 005 → token budget 8,000 and daily cap $10 / 80% alert; ADR 006 → RAGAS thresholds 0.90/0.85/0.80/0.85.
- [ ] Supervisor reviews `feature-400.../plan.md`, `implementation_plan.md`, `tech.md` diffs for R6.

### Tier 7: API / CLI / Application Checks
- [ ] After push, GitHub Actions run of **docs.yml** is green (visible in the repo's Actions tab); confirm it did **not** require any secrets.
- [ ] Confirm `evals.yml` is not triggered by a docs-only change under `spec/**`.

---

## 3. Automated Execution Commands
```powershell
cd "d:\AI Projects\Voice_Agent_For_Clinics\Voice_Agent"

# Tier 1 — docs-drift test
uv run pytest tests/test_architecture_docs.py -v

# Tier 4 — full regression suite
uv run pytest -q

# Tier 4 — no application code touched
git diff --stat -- src/ pyproject.toml .github/workflows/evals.yml

# Tier 5 — lint
uv run ruff check tests/test_architecture_docs.py
```
