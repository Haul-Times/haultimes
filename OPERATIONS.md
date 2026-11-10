# HaulTimes operations

## How it runs (no computer or Claude chat needed)
- **Cloudflare Worker `haultimes-build-timer`** (cron `*/10 * * * *`) asks GitHub to run **Update HaulTimes** every 10 minutes. GitHub's own `cron` in `update.yml` is a backup.
- Each run: collect feeds → rules filter + dedupe → (optional) summaries → build site → Facebook queue → commit. Cloudflare Pages deploys the commit.
- The masthead badge reads `/api/status`, which compares the last *successful* check in `status.json` with the server clock:
  - **UPDATING**: last success ≤ 25 min ago (10-min schedule). A 15-minute schedule uses 30 min.
  - **UPDATES DELAYED**: older than that; the last successful time stays visible.
  - **STATUS UNAVAILABLE**: no status data.
  - A check is "successful" when ≥ 60% of sources answer and at least one Canadian source answers. A check with no new stories still counts.

## Switches (`config.json`)
| Setting | Effect |
|---|---|
| `pause_new_stories: true` | Master pause: sources are still checked, nothing new is published |
| `pause_summaries: true` | No summary calls; headlines keep publishing |
| `summaries_mode` | `trial` (write + check, keep hidden), `publish` (show summaries that pass), `off` |
| `ai_daily_usd`, `ai_monthly_usd` | Estimated spending caps. At the cap, summaries pause and headlines continue. Never raised automatically |
| `collect_interval_minutes` | What the badge says; must match the Cloudflare cron |

Facebook: `social.json` → `facebook.mode` (`live` / `off`).

## Secrets (never in the repo)
- GitHub Actions: `FB_PAGE_ID`, `FB_PAGE_TOKEN`, `ANTHROPIC_API_KEY` (optional).
- Cloudflare Pages: `ADMIN_PASSWORD`. Cloudflare Worker: `GITHUB_TOKEN` (fine-grained, Actions read/write on this repo only).

## Summaries
Only from text the publisher makes available (article body if robots.txt allows and no paywall; else the publisher's excerpt). Structured output with evidence for every sentence; deterministic checks for quotes, numbers, names and copied runs; one retry; failures are withheld and the story stays as headline + publisher + link. Excerpt-based summaries say "Based on the publisher's available excerpt."

## Recovery
- Badge says DELAYED: GitHub → Actions → look at the latest **Update HaulTimes** run. Re-run it. Check the Cloudflare Worker's logs.
- Facebook stopped: `data/social_facebook.json` → `paused` explains why (usually an expired or wrong token).
- A source keeps failing: `data/sources.json` shows its last error; the admin page lists sources failing 3+ times in a row.
