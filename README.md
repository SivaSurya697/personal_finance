# Personal Finance Dashboard (Local-first)

Streamlit + DuckDB app for ingesting debit/bank and credit card statements into a canonical, auditable ledger.

## Features
- Parser registry with plugin-style parser interface.
- Supports:
  - **FORMAT A** (`~|~` delimited card statements with metadata + table marker)
  - **FORMAT B** (`.txt`/`.csv` comma bank statements)
- Idempotent ingestion via file hash and unique ledger fingerprints.
- Canonical `txn_ledger` with dedupe (exact + near), transfer linking, circular-flow graph flags, CC payment detection/linking.
- Rules-first categorization with override precedence:
  `txn_overrides > merchant_overrides > merchant_rules > heuristics > Uncategorized`.
- Expense vs cashflow analytics views.
- Data quality page supports transaction-level override edits and recomputation.

## Environment setup (venv + dependencies)

### Option A: One-command setup script
```bash
bash scripts/install_deps.sh
source .venv/bin/activate
```

### Option B: Manual setup
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

## Run
```bash
python make_demo_data.py
streamlit run app/streamlit_app.py
```

Database file: `data/db/finance.duckdb`

## Tests
```bash
pytest -q
```

## Adding a new parser
1. Create a new class implementing `Parser` in `finance_core/ingestion/parsers.py` (or a new module).
2. Implement:
   - `can_parse(path, sniff_text_lines) -> bool`
   - `parse(path) -> ParsedStatement`
3. Register parser in `IngestionService` parser registry, earlier in order if it should take precedence.
4. Add tests in `tests/test_parsers.py`.

## Matching overview
- **Fingerprint**: `sha256(account + date + amount + direction + normalized_description + raw_ref)`.
- **Duplicates**:
  - Exact duplicates are flagged and grouped.
  - Near duplicates are flagged by same account + merchant + amount within config window.
  - CGST/SGST lines are preserved (not deduped away).
- **Transfers**: opposite-direction amount/date proximity across different accounts.
- **CC payments**: keyword heuristic with best-effort monthly spend linking and `cc_payment_group_id`.
- **Circular flow**: transfer graph cycle detection in rolling window.

## Project layout
- `app/` Streamlit app and pages.
- `finance_core/` ingestion, normalization, matching, rules, storage, analytics.
- `rules/` taxonomy, merchant rules, and matching config.
- `tests/` parser and pipeline behavior tests.
