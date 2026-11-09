# Total Sessions

System Console > Site Statistics shows **Total Sessions** only when the server is licensed. On this lab that panel is fed by the `extra_counts` analytics call, and the number is a count of session rows that have not expired.

## What the UI calls

The widget is `StatisticCount` id `totalSessions`. The title string is `analytics.system.totalSessions` ("Total Sessions"). It is rendered only when `isLicensed` is true.

- `webapp/channels/src/components/analytics/system_analytics/system_analytics.tsx` (v11.7.15, around the `totalSessions` widget)
- The value is `stats[StatTypes.TOTAL_SESSIONS]`
- The reducer maps the API row name `session_count` onto that key: `webapp/channels/src/packages/mattermost-redux/src/reducers/entities/admin.ts` (`case 'session_count'`)

The public description matches the query. From the statistics doc: "The number of active user sessions connected to your system. Expired sessions are not counted."

https://docs.mattermost.com/administration-guide/manage/statistics

## The API

`GET /api/v4/analytics/old?name=extra_counts`

`server/channels/app/analytics.go`, `getExtraCountsAnalytics`, asks the session store for that row:

```go
sessionsCount, err = a.Srv().Store().Session().AnalyticsSessionCount()
```

The row name in the JSON is `session_count`. `name=standard` does not include it. That is why a first look at the default analytics payload does not show Total Sessions.

## The SQL

`server/channels/store/sqlstore/session_store.go`, `AnalyticsSessionCount`, v11.7.15 lines 357-369:

```sql
SELECT
    COUNT(*)
FROM
    Sessions
WHERE ExpiresAt > ?
```

The bound value is `model.GetMillis()`, the current Unix time in milliseconds. `ExpiresAt` is stored in the same unit. A row with `ExpiresAt = 0` is not counted, because 0 is not greater than the current time. Expired sessions fail the comparison and drop out. There is no join and no filter on user, device, or team. One login can create more than one row, so the number is sessions, not distinct users.

Postgres on this cluster, same predicate:

```sql
SELECT COUNT(*)
FROM sessions
WHERE expiresat > (EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::bigint;
```

Checked against the live server while it was quiet: the API `session_count` and this SQL both returned 13. Later reads were 19, then 23, after more logins. The count moves with new sessions. The check is that the two numbers are equal at the same moment, not that the number stays put.

## How to reproduce the check

With the port-forward up and an admin session:

```bash
curl -sS -H "Authorization: Bearer $TOKEN" \
  'http://127.0.0.1:8065/api/v4/analytics/old?name=extra_counts'
kubectl -n mattermost exec postgres-0 -- \
  psql -U mmuser -d mattermost -c \
  "SELECT COUNT(*) FROM sessions WHERE expiresat > (EXTRACT(EPOCH FROM clock_timestamp())*1000)::bigint;"
```
