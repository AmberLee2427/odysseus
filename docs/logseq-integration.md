# Logseq Integration

Odysseus can use a file-based Logseq graph as a shared knowledge layer. This
first integration does not replace the existing notes, documents, tasks, or
operational database.

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

## Deferred

This phase does not include collaborative editing, migrations from existing
notes/documents, project-aware context loading, graph visualization, or
per-user graph permissions.
