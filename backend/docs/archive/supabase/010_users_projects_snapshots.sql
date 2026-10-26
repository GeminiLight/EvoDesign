-- ============================================
-- EvoDiagram Core Relational Schema
-- users / projects / snapshots
-- ============================================

-- postgres extension (only effective on PostgreSQL)
create extension if not exists "uuid-ossp";

-- 1) users
create table if not exists public.users (
  user_id uuid primary key default uuid_generate_v4(),
  username varchar(255),
  email varchar(255) not null unique,
  avatar_url text,
  auth_provider varchar(50) not null default 'email',
  external_id varchar(255),
  password_hash varchar(255),
  last_login_at timestamp,
  created_at timestamp not null default now(),
  updated_at timestamp not null default now(),
  constraint users_auth_provider_check check (auth_provider in ('email', 'google', 'github'))
);

create unique index if not exists users_email_uidx on public.users(email);
create index if not exists users_provider_external_idx on public.users(auth_provider, external_id);

-- 2) projects
create table if not exists public.projects (
  project_id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references public.users(user_id) on delete cascade,
  title varchar(255),
  diagram_type varchar(100),
  domain_tag varchar(100),
  canvas_engine varchar(30) not null default 'excalidraw',
  source_text text,
  source_image text,
  latest_schema jsonb,
  thumbnail_url text,
  created_at timestamp not null default now(),
  updated_at timestamp not null default now(),
  constraint projects_canvas_engine_check check (canvas_engine in ('tldraw', 'excalidraw'))
);

create index if not exists projects_user_updated_idx on public.projects(user_id, updated_at desc);
create index if not exists projects_diagram_type_idx on public.projects(diagram_type);
create index if not exists projects_domain_tag_idx on public.projects(domain_tag);

-- 3) snapshots
create table if not exists public.snapshots (
  snapshot_id uuid primary key default uuid_generate_v4(),
  project_id uuid not null references public.projects(project_id) on delete cascade,
  parent_id uuid,
  schema_blob jsonb not null,
  edit_source varchar(20) not null,
  thought_trace text,
  metrics_scores jsonb,
  timestamp timestamp not null default now(),
  constraint snapshots_edit_source_check check (edit_source in ('AI_GEN', 'AI_REFINE', 'HUMAN'))
);

create index if not exists snapshots_project_timestamp_idx on public.snapshots(project_id, timestamp desc);
create index if not exists snapshots_parent_idx on public.snapshots(parent_id);

-- updated_at auto-update timestamp function
create or replace function public.update_updated_at_column()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_users_updated_at on public.users;
create trigger trg_users_updated_at
before update on public.users
for each row execute procedure public.update_updated_at_column();

drop trigger if exists trg_projects_updated_at on public.projects;
create trigger trg_projects_updated_at
before update on public.projects
for each row execute procedure public.update_updated_at_column();
