-- Save each SELECT as a separate PostHog SQL insight.
SELECT
    uniqExactIf(properties.suggestion_id, properties.status = 'success') AS succeeded,
    uniqExact(properties.suggestion_id) AS finished,
    100.0 * succeeded / nullIf(finished, 0) AS generation_success_pct
FROM events WHERE (properties.is_test IS NULL OR properties.is_test = false) AND event = 'generation_finished';

SELECT
    uniqExactIf(properties.attempt_id, properties.status = 'executed_unverified') AS executed,
    uniqExact(properties.attempt_id) AS finished,
    100.0 * executed / nullIf(finished, 0) AS execution_complete_pct
FROM events WHERE (properties.is_test IS NULL OR properties.is_test = false) AND event = 'fill_execution_finished';

SELECT quantile(0.5)(toFloat(properties.duration_ms)) AS p50_ms,
       quantile(0.95)(toFloat(properties.duration_ms)) AS p95_ms
FROM events WHERE (properties.is_test IS NULL OR properties.is_test = false) AND event = 'suggestion_exposed';
