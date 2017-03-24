import dateutil.parser as dtpr
from math import floor

DAY_IN_SECONDS = 60. * 60 * 24

def days_diff_from_strs(date_str1, date_str2):
    # tzinfo = NONE credit: Ian source: SO
    datetime1 = dtpr.parse(date_str1).replace(tzinfo=None)
    datetime2 = dtpr.parse(date_str2).replace(tzinfo=None)
    days = (datetime2 - datetime1).days
    return days

def seconds_to_days(seconds):
    return seconds / DAY_IN_SECONDS
