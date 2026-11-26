# Medical kits
MedData Analytics SaaS — MVP
A Flask-based healthcare research data workspace with user accounts, research projects, CSV/Excel uploads, descriptive statistics, missingness, interactive charts, a private admin panel, a two-analysis free allowance, and optional Razorpay checkout for ₹15 analysis credits.
Research-use only: This starter is not a medical device and must not be used for clinical diagnosis or treatment decisions. Upload only data you are authorized to process. Remove patient identifiers first.
Included features
Landing page, signup, login, logout
Project creation and user-owned projects
Private CSV/XLSX/XLS uploads (stored outside static/)
Preview of first 12 rows
Run-analysis usage accounting: 2 free per account, then paid credits
Missing-value counts, descriptive statistics, histogram, top-category bar chart, correlation heatmap
User file download and owner-only dataset file download
Admin dashboard: user list, uploaded dataset metadata, platform totals
Optional Razorpay checkout: order creation and server-side signature verification; adds one credit only after verified payment
SQLite for local development, configurable DB path
Local setup
Python 3.10+ recommended.
# Windows PowerShell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
Edit .env. Set a long random SECRET_KEY, and ADMIN_EMAIL / ADMIN_PASSWORD. Run:
python app.py
Open http://127.0.0.1:5000.
Razorpay test mode
Create a Razorpay account and obtain test keys from its dashboard.
Add RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET to .env.
Install requirements (includes razorpay).
Test checkout using Razorpay's test payment methods. Do not use live keys until you test the payment flow, refund flow, and verification.
The server creates ₹15 (1500 paise) orders, checks the returned signature server-side, prevents a successful order from being credited twice, and then adds one paid analysis credit. For a production payment system, also add webhook reconciliation (e.g., payment captured/failed), refund handling, customer support, unique constraints, and audit logs.
Deployment (Render / similar)
Commit this folder to a private or public GitHub repo, but never commit .env, database files, or uploaded files.
Use a persistent disk for private_uploads/ and the SQLite database for a small test deployment. For production, use managed PostgreSQL and private object storage.
Build command: pip install -r requirements.txt
Start command: gunicorn app:app
Add environment variables from .env.example in the hosting dashboard.
Set COOKIE_SECURE=1 after HTTPS is enabled.
Set a persistent DATABASE_PATH location if your platform requires it.
Important limitations / production checklist
This is an MVP, not production-ready healthcare infrastructure. Before public launch, add:
CSRF/session hardening review, rate limits, brute-force protection, and email verification
File size limits plus malware scanning, CSV/XLSX parsing resource limits, and stricter column/type validation
Tenant-isolation/security tests and privacy review
Database backups, encrypted persistent storage, and data-retention/deletion controls
Admin audit logs and secure admin dataset access workflow
Payment webhook reconciliation, refunds, and payment-state monitoring
Error handling and observability
Research/statistical validation, test coverage, and accessibility checks
Privacy notice, terms, consent, and applicable India DPDP Act compliance review
