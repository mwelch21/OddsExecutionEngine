# The Odds API v4: quota reporting and call costs

Research for issue #54 (child of #52, "Wayfinder: notification layer").
Sources are first-party the-odds-api.com pages, read 2026-10-03. Docs only; no
live calls were made. Note that `theoddsapi.com` and `odds-api.io` are
**different vendors**. Their pages show up in searches and must not be cited.

## TL;DR

| Question | Answer | Confidence |
|---|---|---|
| Quota headers | `x-requests-remaining`, `x-requests-used`, `x-requests-last` | Documented [1][3] |
| On every endpoint? | Yes. Docs say "every API call", including the free `/sports` and `/events` | Documented [1][3] |
| On error responses? | The `OUT_OF_USAGE_CREDITS` docs point you at the headers to monitor usage, but no page says outright that 4xx responses carry them | **Not documented**. Treat them as optional (the code already does) |
| Sport-wide `/odds`, h2h,spreads,totals x us | `markets x regions` = **3** credits; **0** if no events are returned | Documented [1] |
| Single-event `/events/{id}/odds`, same params | `unique markets returned x regions` = **<= 3**, so 0-3 depending on which markets the event has | Documented [1] |
| Free endpoints | `/v4/sports` and `/v4/sports/{sport}/events` cost 0 | Documented [1] |
| Zero credits | Error code `OUT_OF_USAGE_CREDITS`, "limit ... reached for the month" | Code documented [3]; **HTTP status not documented** |
| Reset | "automatically reset on the first of every month" (calendar month, timezone not stated) | Documented [4] |
| Free-tier rate limit | 30 req/s → 429 `EXCEEDED_FREQ_LIMIT`. Stated for paid plans [5]; the error-codes page gives the same 30/s without naming a plan [3] | Documented, but the free tier isn't named |
| Free-tier other limits | 500 credits/month, "Most bookmakers" (not all), **no historical odds** | Documented [2][3] |

## 1. Quota headers

The v4 guide lists the same three headers under each endpoint [1]:

| Header | Meaning (verbatim) |
|---|---|
| `x-requests-remaining` | "The usage credits remaining until the quota resets" |
| `x-requests-used` | "The usage credits used since the last quota reset" |
| `x-requests-last` | "The usage cost of the last API call" |

- `/odds` section: "every API call includes the following response headers" [1].
- `/events/{eventId}/odds` section: "every API response includes the following response headers" [1].
- `/sports` section: "Calls to the /sports endpoint will not affect the quota usage. The following response headers are returned: ..." [1]. **So a free call reports the balance too.**
- Error-codes page, under `OUT_OF_USAGE_CREDITS`: "Usage credits can be monitored by accessing the HTTP response headers, which are returned with every API call" [3].
- Troubleshooting page: "The response headers of each API call contain information on credits used and remaining" [6].

**Gap: errors.** "Every API call" suggests the headers come back on 4xx responses too, but no example or statement confirms it. Unverified secondary reports say a 401 at zero credits does carry `x-requests-remaining: 0`. Design for headers that may be absent.

### Current code (origin/development)

`backend/app/infrastructure/odds_api_provider.py`:

- `_parse_quota` reads `x-requests-last` into `credits_spent` and `x-requests-remaining` into `credits_remaining`, and returns `UpstreamQuota` (`backend/app/domain/models.py`).
- `_read_quota` runs **before** `raise_for_status()`, so a rejected call still reports its quota.
- `_parse_credit_header` maps a missing or unparsable header to `None`, never `0`. That fits the gap above.
- `x-requests-used` is **not read**. It is the only header that lets you work out the total (`used + remaining`) without hardcoding 500.

## 2. Cost per call shape

Billing formulas, verbatim from [1]:

| Endpoint | Formula | Our config (`h2h,spreads,totals`, `us`) |
|---|---|---|
| `GET /v4/sports/{sport}/odds` | "cost = [number of markets **specified**] x [number of regions specified]" | **3** per call, however many events come back |
| `GET /v4/sports/{sport}/events/{eventId}/odds` | "cost = [number of unique markets **returned**] x [number of regions specified]" | **up to 3** for one event; less if a market is missing |
| `GET /v4/sports` | "does not count against the usage quota" | 0 |
| `GET /v4/sports/{sport}/events` | "does not count against the usage quota" | 0 |
| `GET /v4/sports/{sport}/scores` | 1, or 2 with `daysFrom` | n/a |
| `GET .../events/{eventId}/markets`, `.../participants` | 1 | n/a |
| Historical odds / event odds | 10 x markets x regions | not on free tier |

Other cost rules [1]:

- `/odds`: "If no events are returned, the request will not count against the usage quota."
- `bookmakers` param: "Every group of 10 bookmakers is the equivalent of 1 region."
- The guide says the main `/odds` endpoint is "simpler to integrate and more cost-effective" for featured markets.

**What this means here.** A sport-wide call costs 3 credits and refreshes every event in the sport. A per-event call costs up to 3 credits and refreshes one event. It is never more expensive than the sport-wide call, and it is cheaper only when that event lacks some of the markets. Refreshing N events one at a time costs up to 3N, so a sport-wide call is better as soon as you need two or more events from the same sport. On 500/month, either call shape gives about 166 full refreshes.

## 3. Behaviour at zero credits

From the error-codes page [3]:

> **OUT_OF_USAGE_CREDITS**: The usage credit limit of the subscription has been reached for the month.

- **HTTP status: not stated** on any first-party page. The same page does give 429 for `EXCEEDED_FREQ_LIMIT`. Unverified third-party reports say 401. Classify by the `error_code`, not the status.
- **Body: not documented.** The page lists error-code names only, with no JSON example. Parse defensively (look for an `error_code` field, and fall back to the raw text).
- No overage and no soft cap is documented. The only remedy given is to track usage or upgrade in the accounts portal [3][6].

## 4. Reset cadence

- FAQ: "Usage credits are automatically reset on the first of every month." [4] That is a calendar-month reset. **No timezone is given**, so assume UTC and verify with `x-requests-used` after the 1st.
- Downgrade: "Credits are reset to the new plan's quota" at the end of the billing cycle. Upgrade: "Credits become available immediately." [7] Paid billing renews "on the same day of the month that the subscription started" [2]. That is the billing date, not the free-tier credit reset.
- Rollover of unused credits is not mentioned anywhere. Assume none.

## 5. Free tier (Starter, 500/month)

From the plan card on the homepage [2]:

- "500 credits per month", "All sports", "Most bookmakers" (paid tiers say "All bookmakers"), "All betting markets".
- "Historical Odds" is struck through (`<s>`) on Starter, which matches the error code `HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN` [3].

Rate limit:

- "The current rate limit is 30 requests per second on paid usage plans." [5]
- `EXCEEDED_FREQ_LIMIT`: "rate-limited (HTTP status code 429) ... The rate limit is currently 30 API calls per second." [3] No plan is named.
- 429s can happen below the limit during traffic scale-up. The advice is to retry "after a couple of seconds" [3][5].
- No first-party page gives a separate free-tier rate limit. Credits are the binding limit. A manual-refresh app never gets near 30/s.

## Implications for the notification layer (#52)

1. Low-credit alerts can use `credits_remaining` from any call, including free `/sports` and `/events` calls. Checking the balance costs nothing.
2. Read `x-requests-used` too, so the total can be derived rather than assumed to be 500.
3. A zero-credit alert should key off `OUT_OF_USAGE_CREDITS` in the body, because the status code is not documented.
4. Clear the alert after the 1st of the month (calendar month, timezone unconfirmed).
5. A missing header means unknown, not zero. The current parser already does this.

## Sources

1. The Odds API v4 docs: https://the-odds-api.com/liveapi/guides/v4/ (sections: GET sports, GET odds, GET events, GET event odds, Rate Limiting)
2. Pricing, homepage plan cards: https://the-odds-api.com/
3. API error codes: https://the-odds-api.com/liveapi/guides/v4/api-error-codes.html
4. FAQs, "When are usage credits reset?": https://the-odds-api.com/manage/faqs.html
5. Rate limit guide: https://the-odds-api.com/guide/rate-limit.html
6. Troubleshooting unexpected usage: https://the-odds-api.com/manage/troubleshoot-unexpected-usage.html
7. Upgrade / downgrade / cancel: https://the-odds-api.com/manage/upgrade-downgrade-cancel-a-subscription.html
