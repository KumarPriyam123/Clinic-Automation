-- ClinicQ demo seed. Runs after migrations on `supabase db reset`.
-- Demo clinic: slug 'demo', PIN 123456 (bcrypt), language 'hi', Dr. Demo, fee ₹300.
-- Idempotent: safe to re-run.

insert into clinics (slug, pin_hash, name, doctor_name, specialty, language, fee_inr,
                     wa_phone_number_id)
values (
  'demo',
  '$2b$12$veGEzLyhJ5kIPrg3PBiDdOmhSwBNHmoD3608lCZ1G5kBSLKb.hkgO',  -- bcrypt('123456')
  'Demo Clinic',
  'Dr. Demo',
  'General Physician',
  'hi',
  300,
  '1198540706681830'   -- Meta test number phone_number_id (sandbox)
)
on conflict (slug) do update set wa_phone_number_id = excluded.wa_phone_number_id;

-- Weekly timetable: Mon–Sat (weekday 0..5), morning 09:00–13:00 + evening 17:00–21:00, cap 40.
insert into timetable (clinic_id, weekday, name, start_time, end_time, token_cap)
select c.id, wd, 'morning', time '09:00', time '13:00', 40
from clinics c cross join generate_series(0, 5) as wd
where c.slug = 'demo';

insert into timetable (clinic_id, weekday, name, start_time, end_time, token_cap)
select c.id, wd, 'evening', time '17:00', time '21:00', 40
from clinics c cross join generate_series(0, 5) as wd
where c.slug = 'demo';
