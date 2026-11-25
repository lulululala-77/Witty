-- PostHog HogQL: batch-level conversion, one row per installation + suggestion.
-- For the initial pilot this reads all collected data. Add a cohort/date filter
-- on first_exposure rather than truncating action events across midnight.
WITH batches AS (
    SELECT distinct_id, properties.suggestion_id AS suggestion_id,
        minIf(timestamp, event = 'suggestion_exposed') AS first_exposure,
        countIf(event = 'suggestion_exposed') > 0 AS exposed,
        countIf(event = 'fill_clicked') > 0 AS filled,
        countIf(event = 'reply_copied') > 0 AS copied,
        countIf(event = 'suggestion_left') > 0 AS left_seen
    FROM events
    WHERE (properties.is_test IS NULL OR properties.is_test = false) AND event IN ('suggestion_exposed', 'fill_clicked', 'reply_copied', 'suggestion_left')
      AND properties.suggestion_id != ''
    GROUP BY distinct_id, suggestion_id
)
SELECT count() AS exposed_batches,
    round(100.0 * countIf(filled) / nullIf(count(), 0), 2) AS fill_click_pct,
    round(100.0 * countIf(copied) / nullIf(count(), 0), 2) AS copy_pct,
    round(100.0 * countIf(filled OR copied) / nullIf(count(), 0), 2) AS action_pct,
    round(100.0 * countIf(left_seen AND NOT filled AND NOT copied) / nullIf(count(), 0), 2) AS no_action_leave_pct
FROM batches WHERE exposed
