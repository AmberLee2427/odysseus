# Logseq Integration

Odysseus uses a file-based Logseq graph as its durable knowledge and document
artifact layer. Editor documents store their canonical body and metadata in
Logseq-compatible Markdown; SQLite retains operational identity, ownership,
chat linkage, and revision bookkeeping only. Email drafts remain operational
documents and are not written into the graph.

Existing editor documents migrate lazily when opened or edited. New document
artifacts are written directly to:

```text
pages/artifacts/<document-id>.md
```

Revision bodies are stored below `logseq/odysseus-versions/`, rather than
duplicated in SQLite.

## Graph Directory

By default, Odysseus stores the graph in `data/logseq-graph`. The directory is
created with standard Logseq `pages/`, `journals/`, and `logseq/` folders.

To use an existing graph, set:

```bash
ODYSSEUS_LOGSEQ_GRAPH_DIR=/workspace/knowledge
```

For Docker deployments, the graph must be visible inside the container. The
default Compose workspace mount makes host directories under the configured
workspace available below `/workspace`.

Do not point this setting at the checked-in `logseq/` directory. That directory
contains the Logseq application source code, not a knowledge graph.

## API

The shared graph API is admin-only during this phase:

- `GET /api/logseq/status`
- `GET /api/logseq/pages?query=&tag=&limit=`
- `GET /api/logseq/pages/{title}`
- `PUT /api/logseq/pages/{title}`
- `POST /api/logseq/pages/{title}/append`
- `GET /api/logseq/pages/{title}/backlinks`

Writes are atomic. Markdown remains the source of truth, and the integration
understands page properties, `#tags`, `[[page links]]`, journals, and backlinks.

## Agent Tool

Admins have a `manage_logseq` agent tool with these actions:

- `status`
- `list`
- `search`
- `read`
- `write`
- `append`
- `backlinks`

The tool is blocked for non-admin users and while the agent is in plan mode.

It appears under **Knowledge** in the Admin built-in tool settings and in the
Personal Assistant tool-access picker. The default scheduled assistant is
automatically granted access to it.

## Housekeeping

Existing built-in tidy runs remain deliberately scoped:

- Editor Documents Tidy reads graph-backed editor artifacts through the
  document index and affects only those indexed documents.
- Agent Memory Tidy affects only compact agent memories.
- Research Tidy affects only broken research JSON files.

General graph pages that are not indexed editor documents are not touched.
Automated cleanup of orphaned graph pages remains deferred pending an explicit
deletion policy.

## Deferred

This phase does not include collaborative editing, graph visualization, or
per-user graph permissions.
