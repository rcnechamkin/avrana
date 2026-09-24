-- A connection's FIRST successful scan is a baseline: it records what the account already
-- owns without importing any of it. Auto/ask handling only applies to purchases that appear
-- in a LATER scan. Without this, a first scan that lands while sync_mode='auto' (e.g. the
-- connect-time scan failed and the first successful scan is a scheduled one) would treat the
-- entire back catalogue as brand-new purchases and queue all of it — breaking the promise
-- that connecting never auto-downloads.
ALTER TABLE connection ADD COLUMN baselined INTEGER NOT NULL DEFAULT 0;

-- Existing connections have already had their catalogue seen, so they are already baselined;
-- only genuinely new purchases should auto-queue for them going forward.
UPDATE connection SET baselined = 1 WHERE last_scan_at IS NOT NULL;
