# Sovereign Ops Manager

Telegram bot + FastAPI webhook server for store operations management. Runs on Hugging Face Spaces.

## Architecture

- **FastAPI** on port 7860 (HF Spaces requirement)
- **python-telegram-bot** v20+ with webhook mode
- **Groq** for AI parsing (Llama 3.3 70B)
- **Supabase** for persistence
- **SQLite WAL** fallback queue for transient outages

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_TOKEN` | Yes | Bot token from @BotFather |
| `GROQ_API_KEY` | Yes | Groq API key |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_KEY` | Yes | Supabase anon/service key |
| `WEBHOOK_SECRET` | Yes | Random string for webhook validation |
| `SPACE_URL` | Yes | Full HF Space URL (e.g. `https://welly-code-ops-manager-final.hf.space`) |
| `OPS_BRAIN_MODEL` | No | Groq model override (default: `llama-3.3-70b-versatile`) |
| `OPS_FALLBACK_DB` | No | SQLite fallback path (default: `.ops_fallback.db`) |

## Database Schema

```sql
-- store_reports
create table store_reports (
  id bigint generated always as identity primary key,
  store_id text not null,
  report_date date not null default current_date,
  sales numeric,
  inventory_status text,
  staffing text,
  issues jsonb,
  analysis text,
  actions jsonb,
  created_at timestamptz default now(),
  unique (store_id, report_date)
);

-- operator_logs
create table operator_logs (
  id bigint generated always as identity primary key,
  store_id text not null,
  action_type text not null,
  notes text,
  timestamp timestamptz default now()
);
```

## Local Development

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in values
python main.py
```

## Deployment (HF Spaces)

1. Create a new Space → Docker
2. Add all environment variables as **Secrets**
3. Push this repo to the Space
4. Space auto-builds and runs `python main.py`

## Health Checks

- `GET /` — HTML dashboard
- `HEAD /` — 200 OK (HF router)
- `GET /health` — JSON status
- `GET /healthz` — 200 OK (lightweight)

## Webhook

- Endpoint: `POST /telegram-webhook`
- Header: `X-Telegram-Bot-Api-Secret-Token` must match `WEBHOOK_SECRET`
