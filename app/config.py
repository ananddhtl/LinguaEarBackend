from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3(cls, url: str) -> str:
        """Hosts hand out plain `postgres://` or `postgresql://` URLs, which SQLAlchemy would read as the
        older psycopg2 driver. This app uses psycopg 3, so name it explicitly."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "linguaear-api"
    jwt_audience: str = "linguaear-app"
    access_token_minutes: int = 15
    refresh_token_days: int = 1
    remember_me_days: int = 30

    # AI provider. The key lives only here, never in the app.
    groq_api_key: str | None = None
    groq_text_model: str = "openai/gpt-oss-20b"
    groq_vision_model: str = "qwen/qwen3.8-27b"
    groq_whisper_model: str = "whisper-large-v3"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Per-user daily caps (the day rolls over at 00:00 UTC) and limits
    limit_analyze_per_day: int = 20  # spoken phrase -> tutor analysis
    limit_game_per_day: int = 30  # game replies
    limit_scan_per_day: int = 10  # camera scans
    limit_transcribe_per_day: int = 40  # speech to text (tutor and game share it)
    max_saved_phrases: int = 100
    ai_calls_per_minute: int = 10  # burst limit across all AI calls
    max_audio_bytes: int = 5_000_000
    max_prompt_chars: int = 20_000
    max_image_chars: int = 1_500_000  # base64 length of a scan photo
    max_output_tokens: int = 1500

    # Brevo's web API sends mail over HTTPS, which hosts that block SMTP ports still allow. It wins over SMTP when set.
    brevo_api_key: str | None = None

    # Set this to a long random value to switch on GET /health/email, which tests the mail connection.
    diagnostics_token: str | None = None

    # Support. Tickets are emailed here; with no address set, the SMTP account's own inbox is used.
    support_email: str | None = None
    max_tickets_per_day: int = 5

    # Email verification by 6-digit code
    verification_code_minutes: int = 10
    verification_resend_seconds: int = 60
    verification_max_attempts: int = 5
    require_verified_for_access: bool = True  # AI features and saving need a verified email
    log_email_bodies: bool = False  # development: also print each email (and its code) in the server log

    # Subscriptions. After the free trial, AI features and saving need an active plan.
    billing_enforced: bool = True  # False in local development lifts the paywall
    trial_days: int = 7
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_standard: str | None = None  # Price ids from the Stripe dashboard
    stripe_price_pro: str | None = None
    price_label_standard: str = "4.99 EUR / month"  # shown on the paywall; the real price is set in Stripe
    price_label_pro: str = "9.99 EUR / month"
    public_base_url: str = "http://localhost:8765"  # where Stripe sends people back to after checkout
    # Pro limits (Standard uses the limit_* values above; the trial counts as Standard)
    pro_limit_analyze_per_day: int = 60
    pro_limit_game_per_day: int = 90
    pro_limit_scan_per_day: int = 30
    pro_limit_transcribe_per_day: int = 120
    pro_max_saved_phrases: int = 500

    # Score rules
    points_per_correct_answer: int = 10
    perfect_quiz_bonus: int = 10  # extra when every answer in a quiz of 3+ questions is right
    max_game_points_per_event: int = 20
    points_per_level: int = 100

    # One-time tokens (emailed links)
    verify_email_hours: int = 24
    reset_password_minutes: int = 30
    require_verified_email: bool = False  # True: login returns 403 until the email is verified

    # Email. With no smtp_host, emails are logged to the console instead of sent (dev mode).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "LinguaEar <no-reply@linguaear.app>"
    frontend_url: str = "http://localhost:8081"  # base for the links inside emails


settings = Settings()
