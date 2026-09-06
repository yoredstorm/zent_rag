-- MFA TOTP para usuarios de plataforma (FASE 07)
CREATE TABLE IF NOT EXISTS mfa_totp (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    secret_enc TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT false,
    confirmed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);