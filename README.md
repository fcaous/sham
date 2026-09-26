# Crypto Discord Bot — Python + Supabase + Render

## Features

- `/checktx` with network selection for BTC, LTC, ETH, SOL, BNB and TRON
- `/ltc`, `/btc`, `/eth`, `/sol`, `/usdt`, `/bnb`, `/xrp`, `/doge`, `/trx`, `/ton`, `/ada`, `/dot`, `/avax`, `/matic`, `/pol`, `/link`, `/shib`
- Wallet configuration through Discord buttons + modals
- Per-user wallet storage in Supabase
- `/upi`
- `/calculate`
- `/info`
- `/help`
- No JavaScript required

## 1. Create the Supabase table

Open Supabase SQL Editor and run `supabase.sql`.

## 2. Discord application

In the Discord Developer Portal:

1. Create an application.
2. Add a bot/user-install capable application.
3. Generate/copy the bot token.
4. Enable the application commands scope.
5. Install the application to your account/server as desired.

Keep the bot token secret.

## 3. Environment variables

Copy `.env.example` to `.env` for local testing and fill in:

- `DISCORD_TOKEN`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `UPI_IMAGE_URL`

For Render, create the same variables in the service's Environment settings.

`SUPABASE_KEY` should be the server-side service-role key. Never put it in frontend code or expose it publicly.

## 4. Local run

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
python bot.py
```

## 5. Render

This is a background worker, not a web service.

You can deploy from this repository with `render.yaml`, or manually create a Python Worker:

Build:
`pip install -r requirements.txt`

Start:
`python bot.py`

Set the environment variables.

## Important note about /checktx

The included `/checktx` command validates the hash and generates the correct public explorer URL. It does NOT claim confirmation status from an external provider.

For actual live data such as:

- confirmed/unconfirmed
- block/slot
- confirmations
- amount
- sender/receiver
- token transfers

connect each chain to an RPC/indexer provider. This is deliberately separated so you can add your preferred providers/API keys without changing the wallet system.
