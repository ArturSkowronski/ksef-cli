---
name: ksef-cli
description: Use when an agent needs to interact with the Polish KSeF e-invoice system — list, send, download invoices or check auth session status via the ksef CLI tool
---

# ksef-cli

CLI tool for the Polish National e-Invoice System (KSeF). Agents use this tool to authenticate, list, send, and download invoices programmatically.

## Prerequisites

- `ksef` installed: `pip install -e .` in the project root
- Credentials configured: `KSEF_NIP` + `KSEF_TOKEN` env vars, OR run `ksef config set --nip NIP --token TOKEN`
- For PDF/image extraction: `ANTHROPIC_API_KEY` env var set

## Agent Workflow

Always check auth before any invoice operation:

```bash
ksef auth status --json
```

If `sessionActive` is `false`, log in first:

```bash
ksef auth login --nip $KSEF_NIP --token $KSEF_TOKEN
```

## Commands

### Auth Status
```bash
ksef auth status --json
# → {"nip": "1234567890", "environment": "PRD", "sessionActive": true, "expiresIn": 3542, "expiry": "2026-03-12T14:00:00+00:00"}
```

### List Invoices
```bash
ksef invoice list --json
ksef invoice list --json --date-from 2024-01-01 --date-to 2024-01-31
ksef invoice list --json --received   # received invoices instead of issued
# → {"invoices": [{"ksefNumber": "...", "invoiceNumber": "...", "issueDate": "...", "buyer": "...", "seller": "...", "netAmount": "...", "grossAmount": "...", "currency": "PLN"}]}
```

### Check Invoice Status
```bash
ksef invoice status REF_NUMBER --json
# → {"processingCode": 200, "processingDescription": "Processed", "ksefNumber": "KSeF/123/2024"}
```

### Send Invoice
```bash
ksef invoice send invoice.xml --json          # wait for processing (default)
ksef invoice send invoice.pdf --json          # auto-converts PDF to XML first
ksef invoice send invoice.xml --no-wait --json
# → {"invoiceRef": "...", "ksefNumber": "KSeF/123/2024", "processingCode": 200}
# → with --no-wait: {"invoiceRef": "...", "ksefNumber": null, "processingCode": null}
```

### Download Invoice
```bash
ksef invoice get KSeF_NUMBER --out invoice.xml    # save XML
ksef invoice get KSeF_NUMBER --pdf --out inv.pdf  # save as PDF
```

### Batch Download (whole period as PDFs)
```bash
ksef invoice download --json                      # previous month, issued, PDFs → ./invoices-YYYY-MM/
ksef invoice download --month 2026-04 --json      # specific month
ksef invoice download --all --json                # issued + received, deduped
ksef invoice download --format both -o DIR --json # XML + PDF into DIR
# → {"outDir": "invoices-2026-05", "downloaded": [{"ksefNumber": "...", "files": ["..."]}], "failed": []}
# Partial failures exit 0 with entries in "failed"; exit 1 only if everything failed.
```

### Generate XML (no send)
```bash
ksef invoice generate invoice.pdf --out invoice.xml
```

## Error Handling

- Exit code `0` = success, exit code `1` = error
- With `--json`: errors go to **stderr** as `{"error": "message"}`
- Read stderr with: `result = subprocess.run([...], capture_output=True); err = json.loads(result.stderr)`

## Environments

Default: `PRD` (production). Switch with `ksef config set --environment TEST`.
