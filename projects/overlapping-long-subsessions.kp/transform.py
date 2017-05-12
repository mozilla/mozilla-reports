from collections import namedtuple
from utils import seconds_to_days, days_diff_from_strs
from math import floor

def long_to_wide(sqlContext, df, columns):
    df.createOrReplaceTempView("temp")
    return sqlContext.sql(
    """
         SELECT {0},
         FIRST(normalized_channel) as normalized_channel,
         COLLECT_LIST(subsession_start_date) as subsession_start_date,
         COLLECT_LIST(subsession_length) as subsession_length
         FROM
         (
           SELECT *
           FROM temp
           ORDER BY subsession_start_date
         ) as sorted
         GROUP BY {0}
      """.format(','.join(columns)))

# intermediate classes to help with issues with too many tuples
SubsessionData = namedtuple('SubsessionData',
    ['subsession_start_date',
    'subsession_length'])

def find_overlaps(wide_df):
    zipped = zip(wide_df.subsession_start_date, wide_df.subsession_length)

    data = [SubsessionData(*tup) for tup in zipped]
    prev = data[0]
    overlaps = 0

    for cur in data[1:]:
        prev_subsession_length_days = \
            floor(seconds_to_days(prev.subsession_length))
        if prev_subsession_length_days > 0:
            days_diff = days_diff_from_strs(prev.subsession_start_date,
                cur.subsession_start_date)
            if days_diff < prev_subsession_length_days:
                overlaps += 1
        prev = cur

    # must replace, b.c. we return an arbitrary long tuple based on what we have aggregated by
    perc_overlaps = (overlaps / float(len(wide_df.subsession_length))) * 100
    return wide_df[:-2] + (perc_overlaps, )
