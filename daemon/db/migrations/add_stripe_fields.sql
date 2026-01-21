-- Migration: Add Stripe subscription tracking fields
-- Run this migration to add Stripe customer and subscription IDs to User table

ALTER TABLE User ADD COLUMN stripe_customer_id TEXT;
ALTER TABLE User ADD COLUMN stripe_subscription_id TEXT;
ALTER TABLE User ADD COLUMN subscription_status TEXT DEFAULT 'active';

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_user_stripe_customer ON User(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_user_stripe_subscription ON User(stripe_subscription_id);

