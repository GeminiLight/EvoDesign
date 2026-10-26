create extension if not exists "uuid-ossp";

create table if not exists public.diagrams (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references auth.users(id) on delete cascade,
  request_id text not null,
  diagram_id text not null,
  prompt text not null,
  diagram_type text not null,
  style text not null,
  summary text,
  excalidraw_payload jsonb,
  tldraw_snapshot jsonb,
  created_at timestamptz not null default now()
);

create index if not exists diagrams_user_id_idx on public.diagrams(user_id);

alter table public.diagrams enable row level security;

create policy "Users can insert own diagrams" on public.diagrams
  for insert with check (auth.uid() = user_id);

create policy "Users can view own diagrams" on public.diagrams
  for select using (auth.uid() = user_id);

create table if not exists public.subscriptions (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  status text not null default 'free',
  price_id text,
  current_period_end timestamptz,
  stripe_customer_id text,
  stripe_subscription_id text unique,
  updated_at timestamptz not null default now()
);

create index if not exists subscriptions_user_id_idx on public.subscriptions(user_id);

alter table public.subscriptions enable row level security;

create policy "Users can view own subscription" on public.subscriptions
  for select using (auth.uid() = user_id);
