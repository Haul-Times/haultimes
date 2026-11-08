# HaulTimes

Freight and trucking news for the US and Canada, updated every 15 minutes, plus live truck border wait times.

## How it works

Every 15 minutes, GitHub runs three scripts automatically:

1. **Border wait times** (`scripts/fetch_border.py`) reads official commercial lane waits from U.S. Customs and Border Protection and the Canada Border Services Agency, and keeps a running history for the "usual wait by hour" charts.
2. **News** (`scripts/fetch_news.py`) pulls trucking headlines from news feeds. Claude (AI) writes an original title, a short summary and a "why it matters" line for each story, picks the topic and scores importance. Every story links to the original publisher.
3. **Pages** (`scripts/build_site.py`) builds the website into the `site/` folder. Cloudflare Pages publishes it.

## One-time setup

### 1. Add your AI key to GitHub (about 2 minutes)
1. In this repo, go to **Settings → Secrets and variables → Actions**.
2. Click **New repository secret**.
3. Name: `ANTHROPIC_API_KEY`. Secret: your key that starts with `sk-ant-`.
4. Click **Add secret**. The key stays hidden; nobody can see it, including you.

Until the key is added, the site still runs and shows border wait times, but no news.

### 2. Turn on the automatic updates
1. Open the **Actions** tab. If GitHub asks, click **I understand my workflows, go ahead and enable them**.
2. Click **Update HaulTimes** on the left, then **Run workflow** to run it once now.
3. After 1 to 2 minutes, a green check means it worked, and a `site/` folder appears in the repo.

### 3. Put the site online with Cloudflare Pages (free)
1. Log in to Cloudflare and go to **Workers & Pages → Create → Pages → Connect to Git**.
2. Connect GitHub and choose the **Haul-Times/haultimes** repo.
3. Build settings: **Framework preset: None**, **Build command: leave empty**, **Build output directory: `site`**.
4. Click **Save and Deploy**. You get a free address like `haultimes.pages.dev`.

### 4. Connect haultimes.com
1. In the Cloudflare Pages project, go to **Custom domains → Set up a custom domain** and enter `haultimes.com`. Repeat for `www.haultimes.com`.
2. Cloudflare shows the DNS records or nameservers to use. Add them at Domain.com (Network Solutions) under the domain's **DNS / Nameservers** settings.
3. It usually goes live within an hour, sometimes up to a day.

### 5. Visitor stats (free)
1. In Cloudflare, go to **Analytics & Logs → Web Analytics → Add a site**, enter `haultimes.com`, and copy the **token**.
2. In this repo, edit `config.json` and paste it into `"cloudflare_analytics_token"`.
3. Also add the site to **Google Search Console** to see Google searches. Choose the HTML tag method, copy the `content="..."` value into `"google_site_verification"`.

## Settings (`config.json`)

| Setting | What it does |
|---|---|
| `max_new_stories_per_run` | Cap on AI summaries per run, which controls cost. 25 is plenty. |
| `keep_days` | How long stories stay on the site. |
| `top_story_score` | Stories scoring at least this go into `top.xml`, the feed for Facebook auto-posting. |
| `news_feeds` | Where headlines come from. Add any trucking site's RSS feed. |
| `disqus_shortname` | Turns on comments under each story once you create a free Disqus site. |
| `newsletter_form_action` | Turns on the email signup box once you have a newsletter service form address. |
| `show_ad_slots` | Set to `true` when you have ads to place. |

## Photos

Add your own or free stock photos (Unsplash, Pexels) to `images/<topic>/`, for example `images/border/ambassador-1.jpg`. Topics: `rates`, `border`, `regs`, `fuel`, `equip`, `drivers`, `other`. New stories in that topic pick from those photos. Without photos, stories show a HaulTimes topic graphic.

Only use photos you own or that allow commercial use. Avoid photos showing company names, logos or license plates.

## Feeds for social media

- `https://haultimes.com/rss.xml` – every story
- `https://haultimes.com/top.xml` – top stories only. Connect it to Facebook, LinkedIn or X with Zapier or Make ("RSS → post to page").

## Costs

- AI summaries: a few dollars a month at most. Set a monthly spending limit in the Anthropic console.
- GitHub (public repo) and Cloudflare Pages: free.
