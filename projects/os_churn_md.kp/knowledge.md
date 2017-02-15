---
title: Linux User Counts are Easy to Overestimate
authors:
- Ryan Harter (:harter)
tags:
- main ping
created_at: 2017-02-14 00:00:00
updated_at: 2017-02-14 20:08:06.097549
tldr: The longitudinal, main_summary, and cross_sectional datasets can yield misleading
  Linux user counts over time
---
# Linux User Counts are Easy to Overestimate

This is primarily a summary of [Bug 1333960](https://bugzilla.mozilla.org/show_bug.cgi?id=1333960) for the public repo.

## Table of Contents
[TOC]

## Problem
I ran into some strangeness when trying to count users for major OS's.
Specifically, my queries consistently showed more Linux users than Mac users 
([example query](https://sql.telemetry.mozilla.org/queries/2374/source#table)).
However, if we take the exact same data and look at users per day we show the opposite trend:
more Mac than Linux users every day ([query](https://sql.telemetry.mozilla.org/queries/2400/source)).

## Solution
It turns out the root of this problem is `client_id` churn.
The queries showing more users on Linux than Darwin
state that we've seen more Linux `client_id`'s than we have Darwin `client_id`'s over time.
But, what if a large portion of those Linux `client_id`'s haven't been active for months? 

Consider [this graph](https://sql.telemetry.mozilla.org/queries/2399/source#4430) showing the most recent ping for each Linux and Mac `client_id`.
There are many more stale Linux `client_id`'s.
If it's hard to see look at [this graph](https://bug1333960.bmoattachments.org/attachment.cgi?id=8830740&t=62USxvVHZrR5w3yO8bLvEH) for a clearer image based off of the same data.

## TLDR
In short, consider your time window when trying to count users with `client_id`s.
`client_id` churn is a growing problem as you expand your window.
