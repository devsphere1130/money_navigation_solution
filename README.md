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

## Deploying to Vercel
Create two Vercel projects from this repo: one with root directory `frontend`, one with `backend`.
Set the env vars from each `.env.example` in Vercel. Use a hosted PostgreSQL (Neon, Supabase, Vercel Postgres) for `DATABASE_URL`.
