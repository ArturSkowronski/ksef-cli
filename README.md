# ksef-cli

Command-line client for the Polish National e-Invoice System (KSeF / Krajowy System e-Faktur).

## Features

- Authenticate with the KSeF production API
- Generate KSeF-compliant FA(2) XML invoices from PDF/image files using OCR + Claude AI
- Send invoices directly to KSeF and poll for processing status
- Download and list invoices
- Secure credential storage (`~/.ksef/config.toml`, permissions 600)

## Installation

```bash
pip install -e ".[dev]"
```

Requires Python 3.11+.

## Configuration

Set credentials without authenticating:

```bash
ksef config set --nip 1234567890 --token <YOUR_KSEF_TOKEN>
ksef config show
```

For Claude AI fallback extraction, set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Authentication

```bash
# Log in (performs challenge/response auth against KSeF)
ksef auth login --nip 1234567890 --token <YOUR_KSEF_TOKEN>

# Check session status
ksef auth status

# Log out
ksef auth logout
```

## Invoice Commands

### Generate XML (no send)

```bash
# From PDF
ksef invoice generate invoice.pdf --out invoice.xml

# From image
ksef invoice generate scan.png --out invoice.xml

# From existing XML (passthrough validation)
ksef invoice generate existing.xml --out validated.xml

# Print to stdout
ksef invoice generate invoice.pdf
```

### Send Invoice

```bash
# Send XML directly
ksef invoice send invoice.xml

# Send PDF (auto-generates XML first)
ksef invoice send invoice.pdf

# Send without waiting for processing
ksef invoice send invoice.xml --no-wait
```

### Check Status

```bash
ksef invoice status <reference-number>
```

### Download Invoice

```bash
ksef invoice get <reference-number> --out downloaded.xml
```

### List Invoices

```bash
# Current month
ksef invoice list

# Custom date range
ksef invoice list --date-from 2024-01-01 --date-to 2024-01-31
```

## How Invoice Extraction Works

1. **PDF with text layer**: pdfplumber extracts text; heuristic parser finds invoice fields
2. **Low-confidence or image-only**: Claude API (`claude-opus-4-6`) extracts fields via multimodal analysis
3. **Existing XML**: passed through as-is

If extraction confidence is below 50%, the tool warns you and recommends reviewing the generated XML before sending.

## Development

```bash
# Run tests
pytest tests/ -v

# Install with dev dependencies
pip install -e ".[dev]"
```

## Project Structure

```
ksef/
├── main.py        # CLI entry point
├── config.py      # Config file management (~/.ksef/config.toml)
├── client.py      # KSeF API HTTP client
├── auth.py        # Authentication commands
├── invoice.py     # Invoice commands
├── extractor.py   # PDF/image → invoice data
├── xml_builder.py # Invoice data → FA(2) XML
└── models.py      # Pydantic data models
```

## KSeF API

This tool targets the **production** KSeF API at `https://ksef.mf.gov.pl`.

The FA(2) schema namespace: `http://crd.gov.pl/wzor/2023/06/29/12648/`
