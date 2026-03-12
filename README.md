# ksef-cli

Command-line client for the Polish National e-Invoice System (KSeF / Krajowy System e-Faktur). Built for both humans and AI agents.

- Authenticate with the KSeF production API (v2)
- Generate KSeF-compliant FA(3) XML from PDF, image, or raw data
- Send, download, and list invoices
- Machine-readable `--json` output for agent/automation use
- Secure credential storage (`~/.ksef/config.toml`, mode 600)

---

## Installation

```bash
git clone https://github.com/ArturSkowronski/ksef-cli
cd ksef-cli
pip install -e ".[dev]"
```

Requires **Python 3.11+**.

For AI-powered PDF extraction, set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Quick Start

```bash
# 1. Save credentials
ksef config set --nip 1234567890 --token <YOUR_KSEF_TOKEN>

# 2. Log in
ksef auth login

# 3. List this month's invoices
ksef invoice list

# 4. Send an invoice
ksef invoice send invoice.xml
```

---

## Authentication

```bash
ksef auth login --nip 1234567890 --token <TOKEN>   # challenge/response auth
ksef auth status                                    # show session + expiry
ksef auth refresh                                   # refresh access token
ksef auth logout                                    # clear local session
```

---

## Invoice Commands

### Generate XML

Convert a PDF, image, or data file to KSeF FA(3) XML without sending:

```bash
ksef invoice generate invoice.pdf --out invoice.xml   # from PDF
ksef invoice generate scan.png --out invoice.xml      # from image
ksef invoice generate existing.xml --out validated.xml # passthrough + validate
ksef invoice generate invoice.pdf                     # print XML to stdout
```

### Send

```bash
ksef invoice send invoice.xml          # send XML, wait for KSeF processing
ksef invoice send invoice.pdf          # auto-convert PDF → XML, then send
ksef invoice send invoice.xml --no-wait   # send and return immediately
```

### Check Status

```bash
ksef invoice status <reference-number>
```

### Download

```bash
ksef invoice get <ksef-number> --out invoice.xml        # download as XML
ksef invoice get <ksef-number> --pdf --out invoice.pdf  # render as PDF
```

### List

```bash
ksef invoice list                                           # current month
ksef invoice list --date-from 2024-01-01 --date-to 2024-01-31
ksef invoice list --received                               # received invoices
ksef invoice list --seller-nip 9876543210                  # filter by seller
```

---

## Configuration

```bash
ksef config set --nip 1234567890 --token <TOKEN>
ksef config set --environment TEST    # PRD (default) | TEST | DEMO
ksef config show
```

Credentials are stored in `~/.ksef/config.toml` with permissions 600. Tokens are masked in all output.

---

## Agent / Automation Mode

All key commands support `--json` for machine-readable output:

```bash
ksef auth status --json
# → {"nip": "1234567890", "environment": "PRD", "sessionActive": true, "expiresIn": 3542, "expiry": "..."}

ksef invoice list --json
# → {"invoices": [{"ksefNumber": "...", "invoiceNumber": "...", "buyer": "...", "netAmount": "...", ...}]}

ksef invoice status <ref> --json
# → {"processingCode": 200, "processingDescription": "Processed", "ksefNumber": "KSeF/123/2024"}

ksef invoice send invoice.xml --json
# → {"invoiceRef": "...", "ksefNumber": "KSeF/123/2024", "processingCode": 200}
```

Errors go to **stderr** as `{"error": "message"}` with exit code 1. Exit code 0 means success.

A Claude Code agent skill is included at [`skills/ksef-cli/SKILL.md`](skills/ksef-cli/SKILL.md).

---

## How Invoice Extraction Works

When you pass a PDF or image to `generate` or `send`:

1. **PDF with text layer** — `pdfplumber` extracts text; a heuristic parser locates invoice fields
2. **Low confidence or image-only** — `claude-opus-4-6` extracts fields via multimodal analysis
3. **Existing XML** — passed through as-is with optional XSD validation

Extraction confidence is shown at runtime. Below 50%, you'll get a warning to review the generated XML before sending.

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v          # 55 tests

# Run a single test file
pytest tests/test_invoice_cli.py -v
```

### Project Structure

```
ksef/
├── main.py         # CLI entry point (Typer)
├── config.py       # Config file (~/.ksef/config.toml)
├── client.py       # KSeF API HTTP client (httpx)
├── auth.py         # Auth commands + RSA-OAEP token encryption
├── invoice.py      # Invoice commands
├── extractor.py    # PDF/image → InvoiceData (pdfplumber + Claude)
├── xml_builder.py  # InvoiceData → FA(3) XML
├── models.py       # Pydantic models
├── crypto.py       # AES-256-CBC + RSA-OAEP helpers
├── pdf_renderer.py # XML → PDF rendering
└── tui.py          # Interactive TUI dashboard

skills/
└── ksef-cli/
    └── SKILL.md    # Claude Code agent skill
```

---

## KSeF API

Targets the **production** KSeF API v2 at `https://ksef.mf.gov.pl`.

- Auth: challenge/response with RSA-OAEP encrypted token → access token + refresh token
- Send: session-based (AES-256-CBC encrypted invoice inside an RSA-OAEP encrypted session)
- Schema: FA(3) namespace `http://crd.gov.pl/wzor/2025/06/25/13775/`

---

## License

MIT
