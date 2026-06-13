# Using CoSci Through An Agent

CoSci is available to agents as a local MCP server. You do not need to remember
the CLI options. Ask the agent for the scientific thing you want, and it can call
CoSci tools in the background.

CoSci is tuned for astronomy, especially gravitational microlensing modelling.

## What To Ask

### Run A Co-Scientist Pass

Use this when you want hypotheses, rankings, critiques, and next modelling
steps.

Example prompts:

```text
Use cosci to find plausible systematics in Roman high-cadence microlensing light curves.
```

```text
Run a quick cosci pass on whether finite-source effects could bias binary-lens parallax estimates.
```

```text
Use cosci with ADS grounding to generate hypotheses for xallarap false positives in KMTNet events.
```

The agent should call:

```text
run_microlensing_coscientist
```

### Search Literature

Use this when you only want papers or grounding, not the full hypothesis loop.

Example prompts:

```text
Use cosci to search ADS for Roman microlensing detector systematics.
```

```text
Find papers on caustic-crossing binary microlensing and summarize the useful ones.
```

The agent should call:

```text
search_microlensing_literature
```

### Ask A One-Off Question

Use this for a single Antigravity-backed answer without the full orchestration.

Example prompts:

```text
Ask cosci whether this microlensing degeneracy sounds physically plausible.
```

```text
Ask cosci to critique this modelling idea in one paragraph.
```

The agent should call:

```text
ask_coscientist
```

## Depth

CoSci has three run depths:

- `quick`: first-pass exploration; default.
- `normal`: more serious follow-up.
- `deep`: expensive/exhaustive; ask for this explicitly.

Example:

```text
Run a normal-depth cosci pass on Roman WFI detector persistence as a source of false planetary anomalies.
```

```text
Run a deep cosci pass on binary-lens orbital motion versus xallarap degeneracies.
```

If you do not specify depth, the agent should use `quick`.

## Literature Grounding

CoSci can use:

- ADS, if the local ADS token is available.
- arXiv, as fallback or when requested.
- no literature, if you want a pure brainstorming pass.

Examples:

```text
Use cosci with ADS grounding.
```

```text
Use cosci with arXiv only.
```

```text
Run cosci without literature, just brainstorm mechanisms.
```

Default is `auto`, which tries ADS first.

## What You Get Back

A full CoSci run returns:

- a `run_id`
- ranked hypotheses with scores
- claims
- proposed tests
- risks/failure modes
- citations when available
- a meta-review with the most promising direction and next modelling task

The hypotheses are proposals, not facts. Treat them as candidates for modelling,
simulation, or literature checking.

## Good Prompts

Specific prompts work best:

```text
Use cosci to generate hypotheses for why Roman high-magnification events might show false low-q central caustic anomalies from detector or cadence effects.
```

```text
Run cosci on degeneracies between terrestrial parallax, xallarap, and binary-lens orbital motion in long-timescale microlensing events.
```

```text
Search cosci literature for Roman WFI undersampling, intra-pixel sensitivity, and microlensing photometry systematics.
```

```text
Use cosci to critique whether finite-source limb darkening could absorb detector persistence residuals during caustic crossings.
```

## How To Steer It

You can tell the agent:

```text
Make this quick.
```

```text
Use normal depth.
```

```text
Use ADS only.
```

```text
Do not use literature.
```

```text
Focus on KMTNet rather than Roman.
```

```text
Prioritize falsifiable simulation tests.
```

```text
Be skeptical of detector explanations and look for astrophysical degeneracies.
```

## Local Notes

The agent-facing MCP tools are:

```text
run_microlensing_coscientist
search_microlensing_literature
ask_coscientist
coscientist_status
```

The local MCP server is already registered as `cosci`.

