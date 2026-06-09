-- Security advisor: rls_policy_always_true (lint 0024)
-- These policies used WITH CHECK (true) / USING (true) with no role
-- restriction. The service role bypasses RLS entirely, so they never gated
-- service-key access — they only opened these writes to anon/authenticated.
-- All access to bug_reports and sync_operations goes through edge functions
-- using the service role key, so the policies can simply be dropped.

DROP POLICY IF EXISTS "Allow service role inserts on bug_reports" ON public.bug_reports;
DROP POLICY IF EXISTS "Service role can insert sync_operations" ON public.sync_operations;
DROP POLICY IF EXISTS "Service role can update sync_operations" ON public.sync_operations;
