library(boot)
library(broom)
library(dplyr)
library(ggplot2)
library(readr)

summary = read_csv(
  "20200219_fenix_webrender_summary.csv.gz",
  col_types=cols(
    .default = col_double(),
    fatal_native_code_crash = col_integer(),
    nonfatal_native_code_crash = col_integer(),
    enrollment_timestamp = col_datetime("%Y-%m-%d %H:%M:%OS %Z"),
    device_model = col_character(),
    branch = col_character(),
    min_branch = col_character(),
    min_device_model=col_character(),
    consistent_compositor = col_logical(),
    max_app_display_version = col_character()
  )
)

compute_means = function(df) {
  df %>%
    mutate(
      branch=factor(branch, c("disable_webrender", "enable_webrender"), c("Disabled", "Enabled")),
      page_load_time_mean_s=page_load_time_sum/page_load_count / 1e9,
      checkerboard_potential_duration_mean_ms=checkerboard_potential_duration_sum/checkerboard_potential_duration_count / 1e6,
      checkerboard_potential_duration_sum_s = coalesce(checkerboard_potential_duration_sum, 0) / 1e9,
      composite_time_mean_ms=gfx_composite_time_sum/gfx_composite_count / 1e6,
      content_full_paint_time_mean_ms=gfx_content_full_paint_time_sum/gfx_content_full_paint_count / 1e6,
      content_paint_time_mean_ms=gfx_content_paint_time_sum/gfx_content_paint_count / 1e6,
      gfx_content_frame_time_from_vsync_mean=gfx_content_frame_time_from_vsync_sum/gfx_content_frame_count,
      gfx_content_frame_time_from_paint_mean=gfx_content_frame_time_from_paint_sum/gfx_content_frame_time_from_paint_count
    )
}

all_consistency = summary %>%
  group_by(client_index) %>%
  summarize_at(vars(contains("sum"), contains("count"), starts_with("n_")), sum) %>%
  left_join(summary %>% distinct(client_index, branch), on="client_index") %>%
  mutate(only_consistent="All pings") %>%
  compute_means

only_consistent = summary %>%
  filter(consistent_compositor) %>%
  mutate(only_consistent="Consistent compositor_last_seen") %>%
  compute_means

inconsistent = summary %>%
  filter(!consistent_compositor) %>%
  mutate(only_consistent="Inconsistent/null compositor_last_seen") %>%
  compute_means

grouped_by_consistency = bind_rows(
  all_consistency,
  only_consistent,
  inconsistent
)

N_BOOTSTRAP_SAMPLES = 10000
N_CORES = 4

do_boot = function(data, func, col_name) {
  boot(
    data=data,
    statistic=function(df, i) {
      subset = df[i, c("branch", col_name)]
      subset$treatment = subset$branch == "Enabled"
      treatment_value = func(subset[subset$treatment, col_name][[col_name]])
      control_value = func(subset[!subset$treatment, col_name][[col_name]])
      # print(c(treatment_value, control_value))
      c(
        treatment=treatment_value,
        control=control_value,
        difference=treatment_value-control_value,
        ratio=coalesce(treatment_value/control_value, 0)
      )
    },
    R=N_BOOTSTRAP_SAMPLES,
    strata=data$branch,
    simple=TRUE,
    parallel="multicore",
    ncpus=N_CORES
  )
}

metric = function(col, f, label=NULL) {
  function_name = deparse(substitute(f))
  if(is.null(label)) {
    label = paste(col, function_name, sep=".")
  }
  list(col=col, f=f, label=label)
}

safe_median = function(x) median(x, na.rm=TRUE)

to_boot = list(
  metric("page_load_time_mean_s", safe_median),
  metric("checkerboard_potential_duration_sum_s", median),
  metric("composite_time_mean_ms", safe_median),
  metric("content_full_paint_time_mean_ms", safe_median),
  metric("content_paint_time_mean_ms", safe_median),
  metric("gfx_content_frame_time_from_vsync_mean", safe_median),
  metric("gfx_content_frame_time_from_paint_mean", safe_median)
)

boot_each = function(l, df, groups) {
  cat(paste0(l$col, "\n"))
  df %>%
    group_by_at(groups) %>%
    do(do_boot(., l$f, l$col) %>% tidy(conf.int=TRUE)) %>%
    ungroup %>%
    mutate(metric=l$label)
}

booted = lapply(to_boot, boot_each, grouped_by_consistency, c("only_consistent")) %>% bind_rows

write_csv(booted, "bootstraps.csv")
