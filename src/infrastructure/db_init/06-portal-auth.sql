-- =============================================================================
-- Portal Auth — email + password_hash (bcrypt) for trial login
-- =============================================================================
ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(320);
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);

-- Global unique email for portal login (NULLs allowed for legacy seed rows)
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
    ON users (lower(email))
    WHERE email IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_users_email ON users (lower(email));

-- Attach demo email to existing seed admin (password set at API startup in development)
UPDATE users
SET email = 'demo@zenttech.com'
WHERE id = '00000000-0000-0000-0000-000000000002'
  AND email IS NULL;
