# Co-Scientist

Personal research orchestration inspired by the Co-Scientist paper, but built for your workflow:
Antigravity CLI first, Gemini 3.5 Flash with medium thinking by default, and astronomy/microlensing
as the home domain.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

## Dry Run

Inspect the planned prompts without calling Antigravity:

```bash
.venv/bin/cosci run "How could finite-source effects bias binary-lens microlensing parallax estimates?" --dry-run
```

## Auth

The default backend rides on the logged-in Antigravity CLI (`agy`) so subscription/login auth stays
inside Google's tool.

Check local auth:

```bash
.venv/bin/cosci auth
```

If you want the SDK/API path instead, use `--backend sdk`. That path supports Gemini API-key auth
or Vertex config; it does not currently expose Google AI subscription/OAuth quota to Python.

SDK with an API key:

```bash
export GEMINI_API_KEY=...
.venv/bin/cosci run "Find plausible microlensing modelling systematics" --backend sdk
```

SDK with Vertex:

```bash
.venv/bin/cosci run "Find plausible microlensing modelling systematics" \
  --backend sdk --vertex --project YOUR_PROJECT --location us-central1
```

## Run

```bash
.venv/bin/cosci run "Find plausible microlensing modelling systematics in high-cadence Roman light curves" --rounds 2
```

State is stored in `.cosci/cosci.sqlite3`.

## Literature

ADS is used when `ADS_API_TOKEN` is set in `.env`; otherwise `--literature-provider auto`
falls back to arXiv.

```bash
.venv/bin/cosci literature "Roman microlensing detector persistence caustic crossing" --provider ads
```

Use literature grounding in a run:

```bash
.venv/bin/cosci run "Find plausible Roman microlensing detector systematics" \
  --literature \
  --literature-provider auto \
  --literature-results 5
```

Disable it:

```bash
.venv/bin/cosci run "Find plausible Roman microlensing detector systematics" --no-literature
```
