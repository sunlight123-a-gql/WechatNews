# Public Affairs News Publisher

Daily automation for collecting public Chinese news feeds and publishing a static digest website. The current configuration focuses on public security, politics, finance, and technology.

## What It Does

1. Reads the verified RSS sources in `sources.yml`.
2. Keeps news published today in the `Asia/Shanghai` timezone.
3. Filters by topic keywords, removes duplicate events, and ranks matching items.
4. Reserves at least two results for each configured topic category.
5. Renders a static HTML digest for GitHub Pages.
6. Can optionally rewrite selected stories with DeepSeek and create a WeChat draft.

The default configuration does not call DeepSeek or WeChat, so it can be run immediately without API credentials.

## Run Locally

Python 3.11 or newer is recommended. This project uses only the Python standard library.

```bash
python -m unittest discover -s tests -v
python src/main.py --config config.yml --sources sources.yml --output output --dry-run
```

The generated page is written to `output/YYYY-MM-DD.html`.

## News Sources

`sources.yml` currently includes nine verified public sources from People.cn, XinhuaNet, China Police Daily, ITHome, and Solidot. The fetcher supports both RSS/Atom feeds and dated links from configured channel pages:

- Politics
- Public security, legal affairs, and society
- Finance and economic policy
- Technology and innovation

Each source has a category used by the ranking rules. A source can be an RSS/Atom feed or a configured public channel page whose article links contain publication dates.

## Topic Coverage

The `category_minimums` section in `config.yml` controls minimum coverage:

```yaml
category_minimums:
  public_security: 2
  politics: 2
  finance: 2
  technology: 2
```

The remaining positions are filled by overall keyword score and publication time.
`category_maximums` prevents one topic from dominating the digest; the default limit is five items per category.

## Email Delivery

Email delivery uses authenticated SMTP and is enabled explicitly with `--send-email`. Configure credentials only through environment variables:

```text
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_SECURITY=ssl
SMTP_USERNAME=sender@example.com
SMTP_PASSWORD=your-smtp-authorization-code
EMAIL_FROM=sender@example.com
EMAIL_TO=recipient@example.com
SMTP_TIMEOUT_SECONDS=30
```

Multiple recipients can be separated with commas or semicolons. Use an SMTP authorization code, not the mailbox login password. Run one manual delivery with:

```bash
python src/main.py --config config.yml --sources sources.yml --output output --send-email
```

`--dry-run` always skips email and WeChat calls.

## Ubuntu 24.04 Server Deployment

The files under `deploy/` define a dedicated service account, a one-shot service, and a daily 09:00 Asia/Shanghai timer. On a new server:

```bash
apt update
apt install -y git python3 python3-venv
useradd --system --home /opt/news-digest --create-home --shell /usr/sbin/nologin newsdigest
git clone https://github.com/sunlight123-a-gql/WechatNews.git /opt/news-digest
chown -R newsdigest:newsdigest /opt/news-digest
sudo -u newsdigest python3 -m venv /opt/news-digest/.venv
sudo -u newsdigest /opt/news-digest/.venv/bin/python -m unittest discover -s /opt/news-digest/tests -v
install -o root -g newsdigest -m 0640 /opt/news-digest/deploy/news-digest.env.example /etc/news-digest.env
install -o root -g root -m 0644 /opt/news-digest/deploy/news-digest.service /etc/systemd/system/news-digest.service
install -o root -g root -m 0644 /opt/news-digest/deploy/news-digest.timer /etc/systemd/system/news-digest.timer
```

Edit `/etc/news-digest.env`, replace every example email value, then verify one delivery before enabling the timer:

```bash
nano /etc/news-digest.env
systemctl daemon-reload
systemctl start news-digest.service
journalctl -u news-digest.service -n 100 --no-pager
systemctl enable --now news-digest.timer
systemctl list-timers news-digest.timer
```

To update the deployed code later:

```bash
cd /opt/news-digest
sudo -u newsdigest git pull --ff-only
sudo -u newsdigest .venv/bin/python -m unittest discover -s tests -v
systemctl restart news-digest.service
```

## Optional DeepSeek Generation

DeepSeek generation is disabled by default:

```yaml
article_generation:
  enabled: false
```

To enable it, set the API key as an environment variable and change `enabled` to `true`:

```text
DEEPSEEK_API_KEY
```

Do not put API keys in `config.yml` or commit them to Git. `--dry-run` skips WeChat publishing but does not disable DeepSeek when article generation is enabled.

## Optional WeChat Publishing

For local runs or a fixed-IP server, configure:

```text
WECHAT_APP_ID
WECHAT_APP_SECRET
WECHAT_THUMB_MEDIA_ID
```

Then update `config.yml`:

```yaml
wechat:
  create_draft: true
  auto_publish: false
```

Keep `auto_publish` disabled until drafts, article images, account permissions, and the outbound IP whitelist have been verified with the real account.

## GitHub Actions

The workflow runs daily at 09:00 Asia/Shanghai and on pushes to `main`. It runs tests, generates the digest in dry-run mode, and deploys the latest HTML file to GitHub Pages.

## Compliance Boundary

The project uses public RSS/Atom feeds and official APIs. It does not automate login, bypass captcha, reuse cookies, or access private platform APIs.
