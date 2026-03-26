# Tilto

Tilto is an AI-powered career guidance platform that helps users identify professional development paths through an intelligent quiz and personalized analysis system.

## Features

- **Career Orientation Quiz** — A 5-10 minute quiz that analyzes a user's professional situation and delivers 3 concrete career paths within 24 hours
- **Hybrid AI + Human Analysis** — Combines Claude AI analysis with expert human review for high-quality, actionable insights
- **Audio Capsules** — Learning modules with audio transcription support
- **Coaching Sessions** — Booking integration via YouCanBookMe
- **Admin Dashboard** — Manage users, orders, bookings, and product deliverables
- **Multi-language Support** — French and English (Flask-Babel)
- **Two-Factor Authentication** — TOTP-based 2FA for account security
- **Stripe Payments** — Full payment and subscription management

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Flask 2.2.5, Python 3.10, Gunicorn |
| Database | MySQL (Flask-MySQLdb, SQLAlchemy) |
| Frontend | Jinja2, HTML/CSS/JS, Flask-Assets |
| AI | Anthropic Claude (analysis), OpenAI Whisper (audio transcription) |
| Cloud | Google Cloud Platform (Cloud Run, Cloud SQL, Cloud Storage, Cloud Tasks, Secret Manager) |
| Payments | Stripe |
| Email | Brevo (SendGrid) |
| Monitoring | OpenTelemetry, Google Cloud Logging & Trace |

## Project Structure

```
tilto/
├── app.py                  # Flask application factory & route registration
├── wsgi.py                 # Gunicorn entry point
├── config.py               # Configuration (GCP secrets, env vars)
├── extensions.py           # Flask extension initialization
├── forms.py                # WTForms definitions
├── utils.py                # Utility functions
├── routes/                 # Blueprint modules
│   ├── auth.py             # Authentication (signup, login, 2FA, OAuth)
│   ├── quiz.py             # Quiz delivery and progress tracking
│   ├── quiz_analysis.py    # Analysis result retrieval
│   ├── dashboard.py        # Admin/user dashboard
│   ├── audio_capsule.py    # Audio learning modules
│   ├── tokens.py           # Token management and access control
│   ├── async_analysis.py   # Background analysis generation
│   └── ...                 # Other route blueprints
├── models/                 # Data models
│   ├── user_model.py       # User ORM model
│   ├── db_init.py          # Database schema (40+ tables)
│   └── db_loader.py        # CSV import and data loading
├── services/               # Business logic
│   ├── quiz_analysis_service.py   # Core AI analysis logic
│   ├── email_service.py           # Email sending (Brevo)
│   ├── anonymization_client.py    # PII anonymization
│   ├── slack_service.py           # Slack notifications
│   ├── youcanbook_service.py      # Booking integration
│   └── ...                        # Other services
├── templates/              # Jinja2 HTML templates
│   ├── base.html           # Base layout
│   ├── pages/              # Main pages
│   ├── auth/               # Authentication pages
│   ├── quiz/               # Quiz pages
│   ├── dashboard/          # Dashboard pages
│   ├── emails/             # Email templates
│   └── components/         # Reusable components
├── static/                 # Client assets (CSS, JS, images)
├── translations/           # i18n files (FR/EN)
├── decorators/             # Custom Flask decorators
├── data/                   # Data files
├── scripts/                # Utility scripts
├── Dockerfile              # Docker image definition
├── cloudbuild.yaml         # Google Cloud Build pipeline
├── requirements.txt        # Python dependencies
└── stripe_products.json    # Stripe product catalog
```

## Getting Started

### Prerequisites

- Python 3.10+
- MySQL database
- API keys for: Anthropic (Claude), Stripe, and optionally OpenAI, Brevo, Slack

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd tilto

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Create a `.env` file at the project root with the following variables:

**Required:**

```env
# Database
DB_HOST=localhost
DB_PORT=3306
DB_NAME=tilto
DB_USER=your_db_user
DB_PASSWORD=your_db_password

# Flask
SECRET_KEY=your_secret_key

# AI Analysis
ANTHROPIC_API_KEY=your_anthropic_key
```

**Optional (for full features):**

```env
# Payments
STRIPE_PUBLIC_KEY=your_stripe_public_key
STRIPE_SECRET_KEY=your_stripe_secret_key
STRIPE_WEBHOOK_SECRET=your_stripe_webhook_secret

# Audio transcription
OPENAI_API_KEY=your_openai_key

# Email (Brevo)
MAIL_SERVER=smtp-relay.brevo.com
MAIL_USERNAME=your_brevo_username
MAIL_PASSWORD=your_brevo_password

# Google Cloud
GOOGLE_CLOUD_PROJECT=your_gcp_project
GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json

# Slack notifications
SLACK_WEBHOOK_URL=your_slack_webhook_url

# Booking
YOUCANBOOK_BASE_URL=your_ycb_url
YOUCANBOOK_SUBDOMAIN=your_ycb_subdomain

# Anonymization
ANONYMIZATION_SERVICE_URL=your_anonymization_url

# Analytics (optional)
GOOGLE_ANALYTICS_ID=your_ga_id
```

### Running Locally

```bash
# Development server
flask run

# Production-like (with Gunicorn)
gunicorn wsgi:application --workers 2 --threads 4 --bind 0.0.0.0:8080
```

The application will be available at `http://localhost:5000` (Flask) or `http://localhost:8080` (Gunicorn).

### Docker

```bash
# Build
docker build -t tilto:latest .

# Run
docker run -p 8080:8080 \
  -e DB_HOST=your_db_host \
  -e DB_USER=your_db_user \
  -e DB_PASSWORD=your_db_password \
  -e ANTHROPIC_API_KEY=your_key \
  tilto:latest
```

## Deployment

The project is configured for deployment on **Google Cloud Run** via Cloud Build:

```bash
gcloud builds submit --config cloudbuild.yaml
```

The `cloudbuild.yaml` pipeline builds the Docker image, pushes it to Container Registry, and deploys to Cloud Run. In production, secrets are managed through Google Cloud Secret Manager.

## Key Routes

| Route | Description |
|---|---|
| `/` | Homepage |
| `/bilan-carriere-express` | Career quiz landing page |
| `/quiz` | Quiz API endpoint |
| `/orientation` | Analysis results page |
| `/coaching-carriere-express` | Coaching services page |
| `/capsule_audio` | Audio learning modules |
| `/dashboard` | User/admin dashboard |
| `/signup`, `/login` | Authentication |
| `/privacy_policy`, `/terms_of_service` | Legal pages |

## Security

- CSRF protection (Flask-WTF)
- Content Security Policy headers (Flask-Talisman)
- Rate limiting (Flask-Limiter)
- CORS management (Flask-CORS)
- Two-factor authentication (PyOTP)
- PII anonymization via external service
- Google Cloud DLP integration

## License

This project is licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0)](LICENSE). You are free to use, modify, and distribute this code, but any modified version that is deployed as a service must also be open-sourced under the same license.
