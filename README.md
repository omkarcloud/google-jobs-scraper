# 💼 Google Jobs Scraper

Google Jobs Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Google Jobs data for free.

## ✨ What Can I Get?

- 💼 **Up to 200 jobs per search** — every board Google indexes: LinkedIn, Indeed, ZipRecruiter, Built In & career sites
- 💰 **Salary, benefits & job type** — pay range with currency, health / dental / PTO, remote flag & posting date
- 🔗 **Up to 8 apply links per job** — each job board plus the employer's own site, flagged as direct
- 🏢 **Employer ratings in one call** — Glassdoor, Indeed & AmbitionBox scores, website, logo & Knowledge Graph ID

## 🎥 Example: A Full Google Job

```json
{
  "id": "WvNw4jfoLAX2BG8FAAAAAA==",
  "title": "Senior Software Engineer (Fullstack)",
  "apply_link": "https://www.linkedin.com/jobs/view/senior-software-engineer-fullstack-at-onecrew-4472087276",
  "job_types": ["full_time"],
  "salary": { "min": 180000, "max": 230000, "currency": "USD", "period": "year", "text": "$180K–$230K a year" },
  "benefits": ["dental_insurance", "paid_time_off", "health_insurance"],
  "date_posted": "2026-09-25",
  "description": "We’re looking for a highly motivated and experienced Senior Software Engineer to join OneCrew’s quickly growing team...",
  "highlights": [
    { "title": "Qualifications", "items": ["You’re a top performer; maintaining high standards and instilling them in others"], "more_count": 2 }
  ],
  "company": { "name": "OneCrew", "id": "/g/11str79mvl", "link": "https://www.google.com/search?kgmid=/g/11str79mvl" },
  "location": { "display_name": "San Francisco, CA", "city": "San Francisco", "region": "CA" },
  "source": "LinkedIn",
  "apply_options": [
    { "source": "LinkedIn", "domain": "linkedin.com", "link": "https://www.linkedin.com/jobs/view/senior-software-engineer-fullstack-at-onecrew-4472087276", "is_direct": false },
    { "source": "Jobs", "domain": "ashbyhq.com", "link": "https://jobs.ashbyhq.com/triumph-arcade/ddadfd9d-43f7-4422-ae6e-721fe72f1d59", "is_direct": true }
  ],
  "occupation": { "onet_code": "15-1133.00", "onet_job_zone": 4 }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Google Jobs Data — Get It in 60 Seconds

1️⃣ Clone and install (the last command downloads Camoufox, the hardened Firefox that opens Google for you):
```bash
git clone https://github.com/omkarcloud/google-jobs-scraper
cd google-jobs-scraper
python -m pip install -r requirements.txt
python -m camoufox fetch
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/search?query=software+engineer&location=San+Francisco,+CA"
```

```json
{
  "current_page": 1,
  "total_pages": 2,
  "search_information": { "query": "software engineer San Francisco, CA" },
  "jobs": [
    {
      "position": 2,
      "id": "WvNw4jfoLAX2BG8FAAAAAA==",
      "title": "Senior Software Engineer (Fullstack)",
      "apply_link": "https://www.linkedin.com/jobs/view/senior-software-engineer-fullstack-at-onecrew-4472087276",
      "job_types": ["full_time"],
      "salary": { "min": 180000, "max": 230000, "currency": "USD", "period": "year", "text": "$180K–$230K a year" },
      "benefits": ["dental_insurance", "paid_time_off", "health_insurance"],
      "date_posted": "2026-09-25",
      "company": { "name": "OneCrew", "id": "/g/11str79mvl" },
      "location": { "display_name": "San Francisco, CA", "city": "San Francisco", "region": "CA" }
    }
  ]
}
```

All 5 endpoints are now live at `http://localhost:8000`.

The first search can take a minute while a browser opens Google and clears its checks; after that, each call takes a second or two.

### 🔓 Google Showing a Captcha?

Google often answers a fresh browser with an "unusual traffic" captcha. The scraper first tries on its own — no key, no cost — and when Google insists, it tells you so. Then:

1. Get a [CapSolver](https://dashboard.capsolver.com/passport/register?inviteCode=lvdYBC4sYKRm) API key (one captcha is solved per ~30 searches).
2. Start the API with it:
   ```bash
   CAPSOLVER_API_KEY=CAP-... python run.py
   ```

For heavy use, add a sticky residential proxy too — Google pauses one IP after a few dozen searches:

```bash
GOOGLE_JOBS_PROXY="http://user-session-{session}:pass@host:port" CAPSOLVER_API_KEY=CAP-... python run.py
```

## 📚 Endpoints

5 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Search Jobs | `/search` | 10–50 jobs per call with salary, description and apply links |
| Job Details | `/details` | One job in full, plus employer ratings and website |
| Batch Job Details | `/details/batch` | Up to 10 full jobs in a single call |
| Company Jobs | `/company-jobs` | Every open job at one company |
| Autocomplete | `/autocomplete` | Job-search suggestions for a partial title |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-google-jobs-scraper-free-200-calls/pricing) — 200 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-google-jobs-scraper-free-200-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-google-jobs-scraper-free-200-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/search",
    params={"query": "software engineer", "location": "San Francisco, CA", "job_type": "full_time"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Google Jobs Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Google%20Jobs%20Scraper%20API.)

[![Ask Us by Email about Google Jobs Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Google%20Jobs%20Scraper%20API&body=I%20need%20help%20using%20the%20Google%20Jobs%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/google-jobs-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/google-jobs-scraper)
