-- Exact calendar-day D1/D7 return, Asia/Shanghai, installation-level.
-- All historical actions are required to identify the first observed use.
-- Only mature cohorts are in each denominator. Missing uploads remain a limitation.
WITH activity AS (
    SELECT distinct_id, toDate(timestamp, 'Asia/Shanghai') AS day
    FROM events WHERE (properties.is_test IS NULL OR properties.is_test = false) AND event IN ('fill_clicked', 'reply_copied')
    GROUP BY distinct_id, day
), users AS (
    SELECT distinct_id, min(day) AS first_day, groupArray(day) AS days
    FROM activity GROUP BY distinct_id
)
SELECT first_day, count() AS cohort_size,
    if(first_day + 1 <= toDate(now(), 'Asia/Shanghai') - 1,
       100.0 * countIf(has(days, first_day + 1)) / count(), NULL) AS d1_pct,
    if(first_day + 7 <= toDate(now(), 'Asia/Shanghai') - 1,
       100.0 * countIf(has(days, first_day + 7)) / count(), NULL) AS d7_pct
FROM users GROUP BY first_day ORDER BY first_day
