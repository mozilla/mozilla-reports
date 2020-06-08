SELECT
    submission_timestamp,
    client_info.client_id,
    client_info.device_model,
    client_info.app_display_version,
    ping_info.seq,
    `moz-fx-data-shared-prod`.udf.get_key(ping_info.experiments, @slug) AS branch,
    metrics.string.gfx_status_compositor_last_seen,
    metrics.timing_distribution.geckoview_page_load_time,
    metrics.timing_distribution.gfx_checkerboard_potential_duration,
    metrics.timing_distribution.gfx_composite_time,
    metrics.timing_distribution.gfx_content_full_paint_time,
    metrics.timing_distribution.gfx_content_paint_time,
    metrics.custom_distribution.gfx_content_frame_time_from_vsync,
    metrics.timing_distribution.gfx_webrender_render_time,
    metrics.labeled_counter.crash_metrics_crash_count,
    metrics.labeled_counter.metrics_search_count,
    metrics.custom_distribution.gfx_content_frame_time_from_paint,
FROM `moz-fx-data-shared-prod`.org_mozilla_fenix.metrics m
WHERE
    DATE(submission_timestamp) >= @experiment_start
    AND DATE(submission_timestamp) < @experiment_end
    AND `moz-fx-data-shared-prod`.udf.get_key(ping_info.experiments, @slug) IS NOT NULL
