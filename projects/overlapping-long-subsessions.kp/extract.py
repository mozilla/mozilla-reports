from datetime import date

def read_from_main_summary(sqlContext):
    df = sqlContext\
      .read.option("mergeSchema", "true")\
      .parquet("s3://telemetry-parquet/main_summary/v3")\
      .select([
          "app_build_id",
          "app_name",
          "app_version",
          "document_id",
          "normalized_channel",
          "client_id",
          "sample_id",
          "subsession_start_date",
          "subsession_length"
          ])

    today = date.today()
    # last_year = today.replace(year = today.year - 1)
    last_year = today.replace(month = 1, day = 1)
    today_str = today.strftime('%Y-%m-%d')
    last_year_str = last_year.strftime('%Y-%m-%d')

    return df\
      .filter(df.sample_id == 42)\
      .filter((df.subsession_start_date > last_year_str)\
        & (df.subsession_start_date < today_str))\
      .drop("sample_id")\
      .na.drop()\
      .dropDuplicates(["document_id"])
