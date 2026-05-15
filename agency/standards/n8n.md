# Agency Standard: n8n Automations

**Version:** 1.0
**Last updated:** 2026-05-16

How n8n automations are designed and delivered for clients.

## Stack (LOCKED)

| Layer | Technology | Version | Notes |
|-------|-----------|---------|-------|
| Platform | n8n self-hosted | latest stable (1.x) | Cloud только если client request |
| Custom code | JavaScript (n8n Code node) | ES2022+ | TypeScript only if extracted to npm package |
| Triggers | Webhook / Schedule / Watch nodes | — | Webhook with HMAC signature если из internet |
| Storage | n8n built-in (workflows JSON) + Postgres if heavy | — | Не SQLite (n8n не support concurrent workers) |
| Custom nodes | TypeScript node, packaged as npm | n8n-nodes-X | Только если нет existing community node |

## Deliverables

For each n8n workflow we deliver:

```
project-root/
├── workflows/
│   ├── <workflow-name>.json     # exported workflow (n8n format)
│   └── ...
├── credentials/
│   └── README.md                # what credentials need to be configured
├── docs/
│   ├── README.md                # what each workflow does, when it triggers
│   ├── runbook.md               # how to monitor, common failures, recovery
│   └── architecture.md          # data flow diagrams (mermaid)
├── tests/
│   └── manual-test-plan.md      # not auto-tested — manual verification steps
└── .gitignore                   # exclude n8n .env, secrets
```

## Conventions

1. **One workflow = one outcome.** Don't bundle 5 trigger handlers into one giant workflow. Split.
2. **Naming:** `<source>-<action>-<destination>` (e.g. `telegram-newlead-bitrix24`)
3. **Error workflow** обязательно для production: at least notify owner via Telegram on workflow error
4. **Code nodes** — writing in `// JS` mode, не Python (n8n Python is heavier)
5. **No hardcoded credentials** — всё через n8n Credentials store
6. **Comments в Code node:** заголовок что делает + author + date

## Что НЕ использовать

- Long-running operations inside Workflow Execution (split via queue if >2 min)
- Synchronous loops over 1000+ items (use SplitInBatches)
- Code node для большой логики (>200 строк) — extract в custom node

## Performance budget

- Single execution: < 60 sec wall time
- Throughput: 10+ executions/minute on standard self-hosted (1 worker)
- Memory per execution: < 500 MB

## Security

- Webhook URLs — UUID-style paths (n8n auto-generates)
- HMAC signatures для webhook'ов от untrusted sources
- Credentials store зашифрован n8n encryption key (rotate yearly)
- n8n UI за nginx + basic auth + IP allowlist

## Common patterns

### 1. Lead intake → CRM

```
Webhook (HMAC verified) → Validate (Code) → Bitrix24/HubSpot create deal → Telegram notify
```

### 2. Daily digest

```
Schedule (08:00) → Read DB rows → Format markdown → Telegram send to owner
```

### 3. Watch + sync

```
Schedule (every 15 min) → Source API list → Compare with DB → Diff → Apply changes → Slack notify
```

## Deployment

n8n self-hosted via Docker:
```yaml
# docker-compose.yml snippet
services:
  n8n:
    image: n8nio/n8n:latest
    restart: always
    environment:
      - N8N_BASIC_AUTH_ACTIVE=true
      - N8N_BASIC_AUTH_USER=${N8N_USER}
      - N8N_BASIC_AUTH_PASSWORD=${N8N_PASS}
      - N8N_ENCRYPTION_KEY=${N8N_KEY}
      - DB_TYPE=postgresdb
      - DB_POSTGRESDB_HOST=postgres
    volumes:
      - ./n8n_data:/home/node/.n8n
    ports:
      - "5678:5678"
    depends_on:
      - postgres
```

## Monitoring

- n8n Activity > Executions tab — daily glance, look for ERROR
- Error workflow → Telegram → owner (above)
- Если client требует SLA — добавить Healthchecks.io ping в финал каждого scheduled workflow
