# Money Navigating Solutions – SIP Calculator

- `frontend/` – React (Vite) app
- `backend/` – Django REST API (PostgreSQL, JWT auth)

## Frontend
```
cd frontend
npm install
npm run dev
```
Set `VITE_API_BASE_URL` in `frontend/.env` (see `.env.example`).

## Backend
```
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # then edit DATABASE_URL
python manage.py makemigrations accounts
python manage.py migrate
python manage.py createsuperuser   # this is your advisor login (email + password)
python manage.py runserver
```

The Fund Analyzer uses Django's in-process cache for local development. Set
`REDIS_URL` (for example, `redis://localhost:6379/0`) in a deployed backend to
share cached AMFI/MFAPI responses across workers. Install the backend
requirements after updating them so the Redis cache backend is available.

### Highest Overlap monthly holdings

The analyzer identifies each scheme and AMC from AMFI's NAV list, then reads
monthly equity holdings from official AMC portfolio files. SBI's official
monthly portfolio listing is fetched automatically. HDFC, PPFAS and Nippon
disclosure pages are also supported when they expose direct Excel links.
For HDFC Flexi Cap Fund, if the listing page returns 403, the analyzer checks
the ordinary public Excel URLs on `files.hdfcfund.com`. It validates the fund
name and reporting date inside the downloaded workbook before caching the
equity stock holdings. REIT/InvIT units and derivatives are excluded.
The card tries the newest common month first, then older months within a
six-month lookback when a workbook is missing, blocked or invalid. It checks
the reporting date printed inside each workbook and never pairs different
months. Parsed holdings are cached for 180 days; a cached month can still be
used if an AMC page later blocks downloads. If no valid common month is
available, the card names the fund whose monthly holdings are missing.

An advisor with a staff account can import an official monthly `.xlsx`, `.xls`
or `.csv` disclosure file through the API. For example, after downloading the
HDFC Flexi Cap Fund September 2026 workbook from HDFC's disclosure page:

```powershell
curl.exe -X POST http://localhost:8000/api/overlap/import `
  -H "Authorization: Bearer YOUR_STAFF_ACCESS_TOKEN" `
  -F "scheme_code=118955" `
  -F "portfolio_date=2026-09-30" `
  -F "file=@C:\path\to\hdfc-flexi-cap-september-2026.xlsx"
```

Use the workbook's actual reporting date; the import checks it against the
date printed inside the file. A staff access token is returned by
`POST /api/auth/login/`. The import validates the scheme against AMFI and
stores parsed equity ISIN weights in Django's cache for 70 days. On a deployed
backend, configure `REDIS_URL` so imported holdings remain available across
workers and restarts. The uploaded workbook itself is not stored in the app
database.

## Deploying to Vercel
Create two Vercel projects from this repo: one with root directory `frontend`, one with `backend`.
Set the env vars from each `.env.example` in Vercel. Use a hosted PostgreSQL (Neon, Supabase, Vercel Postgres) for `DATABASE_URL`.
