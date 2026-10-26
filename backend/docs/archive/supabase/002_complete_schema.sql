-- ============================================
-- Smart Excalidraw React - Complete Database Schema
-- ============================================
-- Version: 1.0
-- Created: 2026-02-09
-- Description: Complete Supabase database schema, including users, diagrams, subscriptions, templates, collaborations, and other core features

-- ============================================
-- Extensions
-- ============================================
create extension if not exists "uuid-ossp";
create extension if not exists "pg_trgm";  -- For fuzzy search
create extension if not exists "btree_gin"; -- For JSONB indexing

-- ============================================
-- 1. Profiles (User extended info)
-- ============================================
-- Stores additional user info, supplementing auth.users base info
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  full_name text,
  avatar_url text,
  bio text,
  tier text not null default 'free', -- free, pro, enterprise
  usage_quota_monthly integer not null default 50, -- Monthly generation quota
  usage_quota_used integer not null default 0, -- Used quota
  preferences jsonb default '{}', -- User preferences
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Indexes
create index if not exists profiles_email_idx on public.profiles(email);

-- RLS policies

-- Users can view their own profile
create policy "Users can view own profile" on public.profiles
  for select using (auth.uid() = id);

-- Users can update their own profile
create policy "Users can update own profile" on public.profiles
  for update using (auth.uid() = id);

-- Users can insert their own profile (created via trigger)

-- Trigger: auto-create profile
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, email, full_name, avatar_url)
  values (
    new.id,
    new.email,
    new.raw_user_meta_data->>'full_name',
    new.raw_user_meta_data->>'avatar_url'
  );
  return new;
end;
$$ language plpgsql security definer;

-- Create trigger if it does not exist
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- Updated timestamp trigger
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger update_profiles_updated_at
  before update on public.profiles
  for each row execute procedure public.update_updated_at();

-- ============================================
-- 2. Diagrams (Diagram data)
-- ============================================
-- Stores user-generated diagrams
create table if not exists public.diagrams (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references auth.users(id) on delete cascade,
  request_id text not null, -- Request ID
  diagram_id text not null, -- Diagram unique identifier
  prompt text not null, -- User input prompt
  diagram_type text not null, -- flow, architecture, sequence, er, mindmap, network, automated
  style text not null, -- neutral, playful, technical, minimal
  summary text, -- Diagram summary
  excalidraw_payload jsonb, -- Excalidraw JSON data
  tldraw_snapshot jsonb, -- TLDraw snapshot
  preview_image_url text, -- Preview image URL (stored in R2/S3)
  is_public boolean not null default false, -- Whether public
  is_template boolean not null default false, -- Whether used as template
  tags text[] default '{}', -- Tags array
  metadata jsonb default '{}', -- Extra metadata
  view_count integer not null default 0, -- View count
  fork_count integer not null default 0, -- Fork count
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Indexes
create index if not exists diagrams_user_id_idx on public.diagrams(user_id);
create index if not exists diagrams_type_idx on public.diagrams(diagram_type);
create index if not exists diagrams_is_public_idx on public.diagrams(is_public);
create index if not exists diagrams_created_at_idx on public.diagrams(created_at desc);
create index if not exists diagrams_tags_idx on public.diagrams using gin(tags);
create index if not exists diagrams_prompt_idx on public.diagrams using gin(to_tsvector('english', prompt));

-- RLS policies
alter table public.diagrams enable row level security;

-- Users can insert their own diagrams
create policy "Users can insert own diagrams" on public.diagrams
  for insert with check (auth.uid() = user_id);

-- Users can view their own diagrams
create policy "Users can view own diagrams" on public.diagrams
  for select using (auth.uid() = user_id);

-- Users can update their own diagrams
create policy "Users can update own diagrams" on public.diagrams
  for update using (auth.uid() = user_id);

-- Users can delete their own diagrams
create policy "Users can delete own diagrams" on public.diagrams
  for delete using (auth.uid() = user_id);

-- Everyone can view public diagrams
create policy "Public diagrams are viewable by everyone" on public.diagrams
  for select using (is_public = true);

-- Updated timestamp trigger
create trigger update_diagrams_updated_at
  before update on public.diagrams
  for each row execute procedure public.update_updated_at();

-- ============================================
-- 3. Subscriptions (Subscription info)
-- ============================================
-- Stores user subscription status
create table if not exists public.subscriptions (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  status text not null default 'free', -- free, trial, active, past_due, canceled, unpaid
  price_id text, -- Stripe Price ID
  product_name text, -- Product name (Pro, Enterprise)
  current_period_start timestamptz, -- Current period start
  current_period_end timestamptz, -- Current period end
  cancel_at_period_end boolean not null default false, -- Cancel at period end
  stripe_customer_id text, -- Stripe Customer ID
  stripe_subscription_id text unique, -- Stripe Subscription ID
  cancel_url text, -- Cancel subscription URL
  update_url text, -- Update subscription URL
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Indexes
create index if not exists subscriptions_user_id_idx on public.subscriptions(user_id);
create index if not exists subscriptions_status_idx on public.subscriptions(status);
create index if not exists subscriptions_stripe_customer_idx on public.subscriptions(stripe_customer_id);

-- RLS policies
alter table public.subscriptions enable row level security;

-- Users can view their own subscription
create policy "Users can view own subscription" on public.subscriptions
  for select using (auth.uid() = user_id);

-- Updated timestamp trigger
create trigger update_subscriptions_updated_at
  before update on public.subscriptions
  for each row execute procedure public.update_updated_at();

-- ============================================
-- 4. Diagram Templates (Diagram template library)
-- ============================================
-- Stores system presets and user-contributed diagram templates
create table if not exists public.diagram_templates (
  id uuid primary key default uuid_generate_v4(),
  name text not null,
  description text,
  diagram_type text not null, -- flow, architecture, sequence, er, mindmap, network
  category text not null, -- business, engineering, education, design, other
  excalidraw_payload jsonb, -- Template Excalidraw data
  tldraw_snapshot jsonb, -- Template TLDraw data
  preview_image_url text, -- Preview image URL
  is_featured boolean not null default false, -- Whether featured
  is_official boolean not null default true, -- Whether official template
  usage_count integer not null default 0, -- Usage count
  created_by uuid references auth.users(id), -- Creator (NULL means official)
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Indexes
create index if not exists diagram_templates_type_idx on public.diagram_templates(diagram_type);
create index if not exists diagram_templates_category_idx on public.diagram_templates(category);
create index if not exists diagram_templates_is_featured_idx on public.diagram_templates(is_featured);

-- RLS policies
alter table public.diagram_templates enable row level security;

-- Everyone can view templates
create policy "Templates are viewable by everyone" on public.diagram_templates
  for select using (true);

-- Authenticated users can create custom templates
create policy "Authenticated users can create templates" on public.diagram_templates
  for insert with check (auth.uid() = created_by);

-- Updated timestamp trigger
create trigger update_diagram_templates_updated_at
  before update on public.diagram_templates
  for each row execute procedure public.update_updated_at();

-- ============================================
-- 5. Collaborations (Collaboration permissions)
-- ============================================
-- Manages diagram collaboration permissions
create table if not exists public.collaborations (
  id uuid primary key default uuid_generate_v4(),
  diagram_id uuid not null references public.diagrams(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'viewer', -- viewer, editor, owner
  invited_by uuid not null references auth.users(id),
  created_at timestamptz not null default now()
);

-- Indexes
create index if not exists collaborations_diagram_id_idx on public.collaborations(diagram_id);
create index if not exists collaborations_user_id_idx on public.collaborations(user_id);
create unique index if not exists collaborations_diagram_user_idx on public.collaborations(diagram_id, user_id);

-- RLS policies
alter table public.collaborations enable row level security;

-- Users can view their own collaborations
create policy "Users can view own collaborations" on public.collaborations
  for select using (auth.uid() = user_id);

-- Users can view collaborations on their own diagrams
create policy "Users can view collaborations on own diagrams" on public.collaborations
  for select using (
    auth.uid() = invited_by
    or exists (
      select 1 from public.diagrams
      where diagrams.id = collaborations.diagram_id
      and diagrams.user_id = auth.uid()
    )
  );

-- ============================================
-- 6. Usage Logs (Usage logs)
-- ============================================
-- Records user API usage for billing and quota management
create table if not exists public.usage_logs (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references auth.users(id) on delete cascade,
  action_type text not null, -- generate_diagram, optimize_arrows, measure_difficulty
  resource_type text not null, -- diagram, api_call
  resource_id text, -- Associated resource ID
  metadata jsonb default '{}', -- Extra info (e.g. token usage, duration)
  created_at timestamptz not null default now()
);

-- Indexes
create index if not exists usage_logs_user_id_idx on public.usage_logs(user_id);
create index if not exists usage_logs_action_type_idx on public.usage_logs(action_type);
create index if not exists usage_logs_created_at_idx on public.usage_logs(created_at desc);

-- RLS policies
alter table public.usage_logs enable row level security;

-- Users can view their own usage logs
create policy "Users can view own usage logs" on public.usage_logs
  for select using (auth.uid() = user_id);

-- ============================================
-- 7. Views
-- ============================================

-- Diagram statistics view
create or replace view public.diagram_stats as
select
  d.user_id,
  count(*) as total_diagrams,
  count(*) filter (where d.is_public = true) as public_diagrams,
  count(*) filter (where d.is_template = true) as template_diagrams,
  sum(d.view_count) as total_views,
  sum(d.fork_count) as total_forks,
  max(d.created_at) as last_created_at
from public.diagrams d
group by d.user_id;

-- User quota view
create or replace view public.user_quota as
select
  p.id as user_id,
  p.tier,
  p.usage_quota_monthly,
  p.usage_quota_used,
  p.usage_quota_monthly - p.usage_quota_used as remaining_quota,
  s.status as subscription_status,
  s.current_period_end,
  s.current_period_start
from public.profiles p
left join public.subscriptions s on p.id = s.user_id;

-- ============================================
-- 8. Functions
-- ============================================

-- Check and deduct quota
create or replace function public.check_and_deduct_quota(
  p_user_id uuid,
  p_amount integer default 1
)
returns boolean as $$
declare
  v_quota_monthly integer;
  v_quota_used integer;
  v_tier text;
begin
  -- Get user quota info
  select usage_quota_monthly, usage_quota_used, tier
  into v_quota_monthly, v_quota_used, v_tier
  from public.profiles
  where id = p_user_id;

  -- Enterprise users are not subject to quota limits
  if v_tier = 'enterprise' then
    return true;
  end if;

  -- Check if quota is sufficient
  if v_quota_used + p_amount > v_quota_monthly then
    return false;
  end if;

  -- Deduct quota
  update public.profiles
  set usage_quota_used = usage_quota_used + p_amount
  where id = p_user_id;

  return true;
end;
$$ language plpgsql security definer;

-- Search diagrams (full-text search)
create or replace function public.search_diagrams(
  p_search_query text,
  p_diagram_type text default null,
  p_limit integer default 20
)
returns table (
  id uuid,
  diagram_id text,
  prompt text,
  diagram_type text,
  preview_image_url text,
  is_public boolean,
  user_id uuid,
  created_at timestamptz
) as $$
begin
  return query
  select
    d.id,
    d.diagram_id,
    d.prompt,
    d.diagram_type,
    d.preview_image_url,
    d.is_public,
    d.user_id,
    d.created_at
  from public.diagrams d
  where
    d.is_public = true
    and (p_diagram_type is null or d.diagram_type = p_diagram_type)
    and (
      to_tsvector('english', d.prompt) @@ plainto_tsquery('english', p_search_query)
      or d.tags && array[p_search_query]
      or d.diagram_id ilike '%' || p_search_query || '%'
    )
  order by d.created_at desc
  limit p_limit;
end;
$$ language plpgsql security definer;

-- ============================================
-- 9. Sample Data
-- ============================================

-- Insert official templates
insert into public.diagram_templates (name, description, diagram_type, category, is_featured, preview_image_url, excalidraw_payload)
values
  ('Flowchart Template', 'Basic flowchart template', 'flow', 'business', true, null, '{"elements": []}'::jsonb),
  ('Architecture Diagram', 'System architecture diagram template', 'architecture', 'engineering', true, null, '{"elements": []}'::jsonb),
  ('Sequence Diagram', 'Sequence diagram template', 'sequence', 'engineering', true, null, '{"elements": []}'::jsonb),
  ('Mind Map Template', 'Mind map template', 'mindmap', 'education', true, null, '{"elements": []}'::jsonb)
on conflict do nothing;

-- ============================================
-- 10. Grant Permissions
-- ============================================

-- Grant authenticated users permission to execute functions
grant usage on schema public to authenticated;
grant execute on function public.check_and_deduct_quota to authenticated;
grant execute on function public.search_diagrams to authenticated;

-- ============================================
-- End of Schema
-- ============================================