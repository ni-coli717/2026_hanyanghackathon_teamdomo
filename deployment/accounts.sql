-- 계정 프로필 (2026-10-27). Supabase SQL Editor 에서 실행.
-- 로그인은 st.login(카카오·구글) 또는 Supabase Auth(이메일). 프로필은 서버(service_role)만 읽고 쓴다.
create table if not exists public.profiles (
 account_key text primary key,                 -- '<provider>:<sub>'
 provider text not null check (provider in ('kakao','google','email','oidc')),
 email text,
 nickname text not null,
 participant_code text not null unique,        -- observations.participant_id 로 쓰는 짧은 코드
 consents jsonb not null default '[]',
 tutorial_done boolean not null default false,
 home_zone text check (home_zone in ('Z1','Z2','Z3')),
 notify boolean not null default false,
 legacy_code text,                             -- 예전 종이·측정앱 참여 코드(P01 등)를 이 계정에 연결
 withdrawn boolean not null default false,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
alter table public.profiles enable row level security;
revoke all on public.profiles from anon, authenticated;
grant all on public.profiles to service_role;
