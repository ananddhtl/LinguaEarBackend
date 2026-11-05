from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_.]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = False


Password = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    email_verified: bool
    full_name: str | None
    bio: str | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MessageResponse(BaseModel):
    message: str


class TokenRequest(BaseModel):
    token: str


class EmailRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")
    new_password: str = Password


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Password


class DeleteAccountRequest(BaseModel):
    password: str


class ProfileUpdate(BaseModel):
    """All fields optional; only the ones sent are changed."""

    username: str | None = Field(default=None, min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_.]+$")
    full_name: str | None = Field(default=None, max_length=100)
    bio: str | None = Field(default=None, max_length=500)
    email: EmailStr | None = None


class Article(BaseModel):
    word: str = Field(max_length=100)
    gender: str = Field(max_length=10)


class CompoundPart(BaseModel):
    text: str = Field(max_length=60)
    meaning: str = Field(default="", max_length=100)


class Compound(BaseModel):
    word: str = Field(max_length=120)
    parts: list[CompoundPart] = Field(min_length=2, max_length=12)
    meaning: str = Field(default="", max_length=200)


class VerifyCodeRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class CodeSent(BaseModel):
    sent: bool
    retry_after: int  # seconds until another code can be requested


class QuizQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=2, max_length=5)
    answer_index: int = Field(ge=0)
    explanation: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def _answer_in_range(self):
        if self.answer_index >= len(self.options):
            raise ValueError("answer_index must point at one of the options")
        if any(len(o) > 200 for o in self.options):
            raise ValueError("options are limited to 200 characters")
        return self


class QuizScore(BaseModel):
    quiz_score: int = Field(ge=0, le=20)
    quiz_total: int = Field(ge=1, le=20)

    @model_validator(mode="after")
    def _score_within_total(self):
        if self.quiz_score > self.quiz_total:
            raise ValueError("quiz_score cannot exceed quiz_total")
        return self


class AnalysisCreate(BaseModel):
    transcript: str = Field(min_length=1, max_length=2000)
    source: Literal["speech", "scan"] = "speech"
    translation: str = Field(default="", max_length=2000)
    explanation: str = Field(default="", max_length=6000)
    tone: str = Field(default="", max_length=100)
    grammar: str = Field(default="", max_length=4000)
    quiz: str = Field(default="", max_length=4000)
    articles: list[Article] = Field(default_factory=list, max_length=50)
    compounds: list[Compound] = Field(default_factory=list, max_length=20)
    quiz_questions: list[QuizQuestion] = Field(default_factory=list, max_length=5)
    quiz_score: int | None = Field(default=None, ge=0, le=20)
    quiz_total: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def _score_pair(self):
        if (self.quiz_score is None) != (self.quiz_total is None):
            raise ValueError("send quiz_score and quiz_total together")
        if self.quiz_score is not None and self.quiz_score > self.quiz_total:
            raise ValueError("quiz_score cannot exceed quiz_total")
        return self


class AnalysisOut(AnalysisCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class QuizScoreEvent(BaseModel):
    correct: int = Field(ge=0, le=20)
    total: int = Field(ge=1, le=20)
    analysis_id: int | None = None  # the saved phrase, when there is one

    @model_validator(mode="after")
    def _correct_within_total(self):
        if self.correct > self.total:
            raise ValueError("correct cannot exceed total")
        return self


class GameScoreEvent(BaseModel):
    points: int = Field(ge=0, le=100)  # the server caps this further


class ScoreAwarded(BaseModel):
    points: int
    total_points: int


class ScoreSummary(BaseModel):
    total_points: int
    level: int
    level_points: int  # points earned inside the current level
    level_size: int
    streak_days: int
    today_points: int


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    # Plain text, or a list of parts like {"type": "text", ...} / {"type": "image_url", ...}.
    content: str | list[dict]


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=12)
    json_mode: bool = False
    temperature: float = Field(default=0.3, ge=0, le=1)


class QuotaItem(BaseModel):
    used: int
    limit: int


class UsageSummary(BaseModel):
    resets_at: datetime
    tier: str
    limits: dict[str, QuotaItem]
    saved_phrases: QuotaItem


class PlanInfo(BaseModel):
    tier: Literal["standard", "pro"]
    price_label: str
    analyze_per_day: int
    game_per_day: int
    scan_per_day: int
    transcribe_per_day: int
    saved_phrases: int


class BillingStatus(BaseModel):
    access: bool
    state: Literal["free", "trial", "subscribed", "expired"]
    tier: Literal["standard", "pro"] | None
    subscription_status: str | None
    trial_ends_at: datetime | None
    trial_days_left: int | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    enforced: bool
    plans: list[PlanInfo]


class CheckoutRequest(BaseModel):
    tier: Literal["standard", "pro"]
    # Where to send the browser when payment is done, e.g. linguaear://billing/return
    return_url: str | None = Field(default=None, max_length=300)


class PortalRequest(BaseModel):
    return_url: str | None = Field(default=None, max_length=300)


class UrlResponse(BaseModel):
    url: str


TicketCategory = Literal["bug", "account", "billing", "feature", "other"]


class TicketCreate(BaseModel):
    category: TicketCategory
    subject: str = Field(min_length=3, max_length=120)
    message: str = Field(min_length=10, max_length=2000)


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: TicketCategory
    subject: str
    message: str
    status: Literal["open", "closed"]
    created_at: datetime


class NotificationPrefs(BaseModel):
    practice_reminders: bool
    product_updates: bool
    billing_emails: bool


Level = Literal["beginner", "intermediate", "professional"]


class KeyPhrase(BaseModel):
    de: str = Field(max_length=200)
    en: str = Field(max_length=200)


class ScenarioIn(BaseModel):
    slug: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=2, max_length=240)
    category: str = Field(min_length=2, max_length=30)
    icon: str = Field(default="chatbubbles-outline", max_length=40)
    tint: str = Field(default="#6366F1", pattern=r"^#[0-9A-Fa-f]{6}$")
    persona: str = Field(min_length=20, max_length=2000)
    openings: dict[Level, str]
    key_phrases: list[KeyPhrase] = Field(default_factory=list, max_length=12)
    sort_order: int = 100
    published: bool = False

    @model_validator(mode="after")
    def _openings_complete(self):
        missing = [lv for lv in ("beginner", "intermediate", "professional") if not self.openings.get(lv, "").strip()]
        if missing:
            raise ValueError(f"an opening line is needed for: {', '.join(missing)}")
        return self


class ScenarioPatch(BaseModel):
    """Every field optional; only the ones sent change."""

    title: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, min_length=2, max_length=240)
    category: str | None = Field(default=None, min_length=2, max_length=30)
    icon: str | None = Field(default=None, max_length=40)
    tint: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    persona: str | None = Field(default=None, min_length=20, max_length=2000)
    openings: dict[Level, str] | None = None
    key_phrases: list[KeyPhrase] | None = Field(default=None, max_length=12)
    sort_order: int | None = None
    published: bool | None = None


class ScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    description: str
    category: str
    icon: str
    tint: str
    persona: str
    openings: dict[str, str]
    key_phrases: list[KeyPhrase]
    sort_order: int
    published: bool


class LevelOut(BaseModel):
    id: str
    label: str
    cefr: str
    description: str
    rules: str


class ScenarioList(BaseModel):
    levels: list[LevelOut]
    scenarios: list[ScenarioOut]


class ScenarioRequestIn(BaseModel):
    title: str = Field(min_length=3, max_length=80)
    description: str = Field(min_length=10, max_length=500)


class ScenarioRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    status: Literal["pending", "approved", "rejected"]
    admin_note: str
    created_at: datetime


class ScenarioRequestAdminOut(ScenarioRequestOut):
    user_id: int
    username: str | None = None


class ScenarioRequestReview(BaseModel):
    status: Literal["pending", "approved", "rejected"]
    admin_note: str = Field(default="", max_length=300)


# ---- Admin: users, tickets, stats ----


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    full_name: str | None
    email_verified: bool
    is_active: bool
    is_admin: bool
    created_at: datetime
    trial_ends_at: datetime | None
    plan: str | None = None  # standard | pro while they have access, otherwise null


class AdminUserList(BaseModel):
    total: int
    users: list[AdminUserOut]


class AdminUserDetail(AdminUserOut):
    billing: dict
    usage: dict
    points: int
    saved_phrases: int
    tickets: int


class AdminUserPatch(BaseModel):
    is_active: bool | None = None
    is_admin: bool | None = None
    email_verified: bool | None = None
    extend_trial_days: int | None = Field(default=None, ge=1, le=365)


class AdminTicketOut(TicketOut):
    user_id: int
    username: str | None = None
    email: str | None = None
    updated_at: datetime


class TicketReplyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message: str
    created_at: datetime


class AdminTicketDetail(AdminTicketOut):
    replies: list[TicketReplyOut]


class TicketStatusPatch(BaseModel):
    status: Literal["open", "closed"]


class TicketReplyIn(BaseModel):
    message: str = Field(min_length=2, max_length=5000)
