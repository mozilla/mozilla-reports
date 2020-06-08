CREATE TEMPORARY FUNCTION values_count(v ARRAY<STRUCT<key STRING, value INT64>>) AS (
    (SELECT SUM(value) FROM UNNEST(v))
);

CREATE TEMPORARY FUNCTION get_key(kva ARRAY<STRUCT<key STRING, value INT64>>, keyname STRING) AS (
    `moz-fx-data-shared-prod`.udf.get_key(kva, keyname)
);

WITH ordered AS (
    SELECT
        * EXCEPT (branch),
        branch.branch,
        ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY seq) AS idx
    FROM `moz-fx-data-bq-data-science`.tdsmith.20200219_fenix_webrender
    WHERE (
        (branch.branch = 'disable_webrender' AND gfx_status_compositor_last_seen = 'opengl') OR
        (branch.branch = 'enable_webrender' AND gfx_status_compositor_last_seen = 'webrender')
    )
)

, first_ping AS (
    SELECT
        client_id,
        submission_timestamp AS enrollment_timestamp,
        device_model,
        branch
    FROM ordered
    WHERE idx = 1
)

, per_user AS (
    SELECT
        client_id,

        ((branch.branch = 'disable_webrender' AND gfx_status_compositor_last_seen = 'opengl') OR
        (branch.branch = 'enable_webrender' AND gfx_status_compositor_last_seen = 'webrender')) AS consistent_compositor,

        MIN(branch.branch) AS min_branch,
        MIN(device_model) AS min_device_model,
        MAX(app_display_version) AS max_app_display_version,

        COUNT(*) AS n_pings,

        SUM(geckoview_page_load_time.sum) AS page_load_time_sum,
        SUM(values_count(geckoview_page_load_time.values)) AS page_load_count,

        SUM(gfx_checkerboard_potential_duration.sum) AS checkerboard_potential_duration_sum,
        SUM(values_count(gfx_checkerboard_potential_duration.values)) AS checkerboard_potential_duration_count,

        SUM(gfx_composite_time.sum) AS gfx_composite_time_sum,
        SUM(values_count(gfx_composite_time.values)) AS gfx_composite_count,

        SUM(gfx_content_full_paint_time.sum) AS gfx_content_full_paint_time_sum,
        SUM(values_count(gfx_content_full_paint_time.values)) AS gfx_content_full_paint_count,

        SUM(gfx_content_paint_time.sum) AS gfx_content_paint_time_sum,
        SUM(values_count(gfx_content_paint_time.values)) AS gfx_content_paint_count,

        SUM(gfx_content_frame_time_from_vsync.sum) AS gfx_content_frame_time_from_vsync_sum,
        SUM(values_count(gfx_content_frame_time_from_vsync.values)) AS gfx_content_frame_count,

        SUM(gfx_content_frame_time_from_paint.sum) AS gfx_content_frame_time_from_paint_sum,
        SUM(values_count(gfx_content_frame_time_from_paint.values)) AS gfx_content_frame_time_from_paint_count,

        SUM(get_key(crash_metrics_crash_count, "uncaught_exception")) AS uncaught_exception_count,
        SUM(get_key(crash_metrics_crash_count, "caught_exception")) AS caught_exception_count,
        SUM(get_key(crash_metrics_crash_count, "fatal_native_code_crash")) AS fatal_native_code_crash,
        SUM(get_key(crash_metrics_crash_count, "nonfatal_native_code_crash")) AS nonfatal_native_code_crash,

        SUM(values_count(metrics_search_count)) AS n_searches,
    FROM `moz-fx-data-bq-data-science`.tdsmith.20200219_fenix_webrender
    GROUP BY client_id, consistent_compositor
)

SELECT
    * EXCEPT (client_id, consistent_compositor, branch, device_model),
    COALESCE(first_ping.branch, min_branch) AS branch,
    COALESCE(first_ping.device_model, min_device_model) AS device_model,
    COALESCE(consistent_compositor, FALSE) AS consistent_compositor,
    DENSE_RANK() OVER (ORDER BY client_id) AS client_index
FROM
    per_user
    LEFT JOIN first_ping
    USING (client_id)
