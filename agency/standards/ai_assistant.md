# Agency Standard: AI Assistant (RAG/Tool-use)

**Version:** 1.0
**Last updated:** 2026-05-16

How custom AI assistants are built for clients — from a chatbot on website to
an internal Slack bot that knows company knowledge base.

## Stack (LOCKED)

| Layer | Technology | Version | Notes |
|-------|-----------|---------|-------|
| Backend | FastAPI | 0.115+ | async, OpenAPI auto-gen |
| LLM client | anthropic-sdk | >=0.40,<1 | Claude as primary; OpenAI/local — only if client requires |
| Vector DB | Qdrant | 1.7+ self-hosted | Pinecone only if client buys |
| Embeddings | text-embedding-3-large (OpenAI) или local Sentence-Transformers | latest | Choice in `docs/ARCHITECTURE.md` |
| Document processing | unstructured + pypdf + python-docx | latest | For knowledge base ingestion |
| Frontend (web chat) | vanilla JS + WebSocket | — | Don't bundle React unless client SPA |
| Auth | API key for B2B / OAuth для consumer | — | |
| Storage | Postgres | 15+ | For chat history, metadata. SQLite OK for MVP |
| Deployment | Docker + nginx | — | Standard pattern |

## Folder structure

```
project-root/
├── app/
│   ├── main.py                    # FastAPI entry
│   ├── api/
│   │   ├── chat.py                # POST /api/chat — main endpoint
│   │   ├── health.py
│   │   └── ingest.py              # POST /api/ingest — KB upload
│   ├── core/
│   │   ├── config.py              # pydantic-settings
│   │   ├── llm.py                 # Claude wrapper with retries
│   │   └── vectorstore.py         # Qdrant client wrapper
│   ├── rag/
│   │   ├── chunker.py             # split docs into chunks
│   │   ├── retriever.py           # search vector DB
│   │   └── reranker.py            # optional: re-rank top-K
│   ├── tools/                     # for tool-use scenarios
│   │   ├── __init__.py
│   │   ├── search_kb.py
│   │   └── *.py
│   ├── prompts/
│   │   ├── system.md              # base system prompt
│   │   └── *.md                   # per-feature prompts
│   ├── db/
│   │   ├── models.py              # SQLAlchemy / SQLModel
│   │   └── migrations/
│   └── ui/                        # if web chat frontend included
│       ├── index.html
│       └── chat.js
├── tests/
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Conventions

1. **Streaming responses by default** — use SSE (Server-Sent Events) или WebSocket для chat. Не блокирующие POST.
2. **Citations** — каждый ответ assistant должен включать sources from KB (если были использованы).
3. **System prompt в `app/prompts/system.md`** — не hardcoded в коде. Edit в одном месте.
4. **Tool-use** — через Anthropic native tools API, не через cluttering prompt.
5. **Retries** — exponential backoff на rate-limit, max 3 попытки.
6. **Token limits** — caller обязан передавать `max_tokens`. Default 1024.
7. **Logging** — token usage per request в Postgres `chat_messages` таблицу для биллинга.

## Performance budget

- Embedding 1 doc: < 5 sec for 10-page PDF
- Vector search (top-10): < 100 ms
- LLM first token: < 2 sec
- LLM full response (typical): < 15 sec for 500-token answer
- Concurrent users: 50+ (depends on Claude rate limits)

## Что НЕ использовать

- LangChain (heavy, opinionated, frequent breaking changes — write the loop yourself in 50 lines)
- LlamaIndex для production (хорошо для prototyping, но complex для prod)
- ChromaDB (single-user, не scales) — only for laptop demos
- Redis for chat history (используем Postgres — durability)

## Security & privacy

- Все user inputs → log в Postgres (для аудита и debug)
- НЕ передавать в LLM personal data клиентов клиента (PII redaction layer если нужно)
- API keys и Qdrant URLs — только в `.env`, никогда в коде
- Rate limit на API key уровне (50 req/min standard)
- WebSocket auth via JWT в query param (не cookie — чтобы CORS не блокировал)

## Knowledge base ingestion pipeline

```
Upload (PDF/DOCX/MD) → unstructured.partition → chunks (500 tokens, 50 overlap)
→ embedding → Qdrant upsert (collection per project)
```

## Standard chat endpoint

```python
@app.post("/api/chat")
async def chat(req: ChatRequest, user: User = Depends(get_user)):
    # 1. Retrieve relevant KB chunks
    chunks = await retriever.search(req.message, top_k=5, filter={"project": user.project})
    # 2. Build context
    system_prompt = load_system_prompt() + format_kb_context(chunks)
    # 3. Stream Claude response
    async def stream():
        async for token in llm.stream(system_prompt, req.history, req.message, tools=TOOLS):
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")
```

## Common assistant types

1. **Customer support chat** — answer FAQ from KB + handoff to human if confidence low
2. **Internal knowledge bot** (Slack/Telegram) — query company docs
3. **Sales lead qualifier** — chat at landing → score lead → CRM
4. **Document analyzer** — upload → extract structured data → return JSON

## Что в documentation для клиента

- `docs/architecture.md` — диаграммы flow
- `docs/runbook.md` — как мониторить, рестартовать, обновлять KB
- `docs/api.md` — для интеграторов клиента (если REST/WS)
- `docs/cost-model.md` — оценка cost per 1000 messages
