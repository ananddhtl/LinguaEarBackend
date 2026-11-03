from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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
    token: str
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
