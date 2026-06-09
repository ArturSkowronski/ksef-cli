# Batch invoice download + PDF generation — design

**Date:** 2026-06-09
**Goal:** One CLI command that downloads all invoices for a period (default: previous calendar month) and renders each as a PDF.

## Command

```
ksef invoice download [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--month YYYY-MM` | previous calendar month | Target month (full month range) |
| `--date-from` / `--date-to` | — | Explicit range, overrides `--month` |
| `--received` / `-r` | off | Received invoices (subject2) instead of issued (subject1) |
| `--all` / `-a` | off | Both issued and received (deduped by KSeF number) |
| `--out-dir` / `-o` | `./invoices-YYYY-MM` | Output directory (created if missing) |
| `--format pdf\|xml\|both` | `pdf` | What to write per invoice |
| `--json` | off | Machine-readable summary for agent use |

`ksef invoice download` with no options = "all my issued invoices from last month as PDFs" — the primary use case.

## Flow

1. Resolve date range: `--date-from/--date-to` if given, else first/last day of `--month`, else previous calendar month (relative to today).
2. Query invoice metadata via existing `client.query_invoice_metadata` with pagination — the loop currently inlined in `list_invoices` is extracted into a shared helper `_fetch_all_metadata(client, payload)`.
3. For `--all`, run the query for both `subject1` and `subject2`, dedupe by KSeF number.
4. For each invoice: `client.get_invoice_by_ksef(ksef_number)` → XML bytes; render with `pdf_renderer.render_invoice_pdf` when format includes pdf.
5. Filenames: `{ksef_number}.pdf` / `.xml`, with `/` and other path-hostile chars replaced by `_`.
6. Per-invoice failures (download or render) are collected and reported; remaining invoices still download. Exit code 1 only if *every* invoice failed or the metadata query itself failed; partial success exits 0 with warnings.

## Output

- Human mode: progress lines per invoice, final summary (`Saved N invoices to <dir>, M failed`).
- `--json`: `{"outDir": ..., "downloaded": [{"ksefNumber":..., "files":[...]}], "failed": [{"ksefNumber":..., "error":...}]}` on stdout.

## Non-goals

- No async/batch KSeF export package API (sync query is sufficient; max 3-month range already respected since one month is queried).
- No ZIP archiving, no e-mail, no concurrent downloads (volumes are small).

## Testing

CLI tests in `tests/test_invoice_cli.py` style: mock `config.require_session` and `KSeFClient`, use `CliRunner` with `tmp_path` for `--out-dir`. Cover: default previous-month range in payload, files written, `--json` summary, partial failure handling, `--month` parsing, filename sanitisation.
