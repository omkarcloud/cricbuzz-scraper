# 🏏 Cricbuzz Scraper

Cricbuzz Scraper is a **free and open-source** scraper that gets you **unlimited** live cricket data for free.

## ✨ What Can I Get?

- 🔴 **Live scores, ball by ball** — every match in play, with commentary and win probability
- 📊 **Complete scorecards** — every batter, bowler, partnership, powerplay & fall of wicket
- 🏆 **Every series since 1877** — fixtures, points tables, squads, venues & the IPL auction
- 👤 **1,000+ teams and their players** — profiles, career stats, ICC rankings & recent form

## 🎥 Example: A Live Cricket Match

```json
{
  "id": 152742,
  "description": "2nd ODI",
  "format": "ODI",
  "link": "https://www.cricbuzz.com/live-cricket-scores/152742/aus-vs-zim-2nd-odi-australia-tour-of-zimbabwe-2026",
  "state": "In Progress",
  "status": "Zimbabwe need 104 runs in 32 balls",
  "status_category": "live",
  "start_time": "2026-09-18T07:30:00Z",
  "team1": {
    "id": 4,
    "name": "Australia",
    "short_name": "AUS",
    "link": "https://www.cricbuzz.com/cricket-team/australia/4",
    "flag": "https://static.cricbuzz.com/a/img/v1/i1/c776202/i.jpg?p=det&d=high",
    "innings": [{ "innings_id": 1, "runs": 356, "wickets": 6, "overs": 49.6 }]
  },
  "team2": {
    "id": 12,
    "name": "Zimbabwe",
    "short_name": "ZIM",
    "link": "https://www.cricbuzz.com/cricket-team/zimbabwe/12",
    "flag": "https://static.cricbuzz.com/a/img/v1/i1/c776198/i.jpg?p=det&d=high",
    "innings": [{ "innings_id": 2, "runs": 253, "wickets": 7, "overs": 44.4 }]
  },
  "batting_team_id": 12,
  "series": {
    "id": 11997,
    "name": "Australia tour of Zimbabwe 2026",
    "link": "https://www.cricbuzz.com/cricket-series/11997/australia-tour-of-zimbabwe-2026",
    "start_date": "2026-09-15",
    "end_date": "2026-09-22"
  },
  "venue": {
    "id": 69,
    "name": "Harare Sports Club",
    "city": "Harare",
    "timezone": "+02:00",
    "coordinates": { "latitude": -17.814114, "longitude": 31.050962 }
  }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Cricbuzz Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/cricbuzz-scraper
cd cricbuzz-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/matches/live"
```

```json
{
  "kind": "live",
  "type": "all",
  "types_available": ["International", "League", "Domestic", "Women"],
  "match_count": 19,
  "groups": [
    {
      "type": "International",
      "series": [
        {
          "id": 11997,
          "name": "Australia tour of Zimbabwe 2026",
          "match_count": 1,
          "matches": [
            {
              "id": 152742,
              "description": "2nd ODI",
              "format": "ODI",
              "state": "In Progress",
              "status": "Zimbabwe need 104 runs in 32 balls",
              "team1": { "short_name": "AUS", "innings": [{ "runs": 356, "wickets": 6, "overs": 49.6 }] },
              "team2": { "short_name": "ZIM", "innings": [{ "runs": 253, "wickets": 7, "overs": 44.4 }] }
            }
          ]
        }
      ]
    }
  ]
}
```

All 58 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

58 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Live Cricket Scores | `/matches/live` | Every match being played right now |
| Match Details | `/matches/details` | Toss, result, officials, venue and the live score |
| Match Scorecard | `/matches/scorecard` | Every batter, bowler, partnership and powerplay |
| Live Match Score | `/matches/live-score` | Score, batters, bowler and the last few balls |
| Commentary | `/matches/commentary`, `/matches/full-commentary` | Ball-by-ball text, latest page or a whole innings |
| Match Highlights | `/matches/highlights` | Only the wickets, fours, sixes and milestones |
| Overs & Ball Map | `/matches/overs`, `/matches/ball-by-ball` | Over-by-over runs, then every single delivery |
| Partnerships & Graphs | `/matches/partnerships`, `/matches/graphs` | Stands, run rate and win probability per over |
| Match Squads | `/matches/squads` | Playing XI, bench and support staff of both sides |
| Player Match Performance | `/matches/player-performance` | One player's innings with bowler match-ups |
| Recent, Upcoming & Schedule | `/matches/recent`, `/matches/upcoming`, `/matches/schedule` | Results, fixtures and the full calendar |
| Series | `/series/details`, `/series/matches`, `/series/venues` | A tournament's card, its fixtures and its grounds |
| Points Table | `/series/points-table` | Standings with net run rate, form and every match |
| Series Stats & Squads | `/series/stats`, `/series/squads`, `/series/squad-players` | Leaderboards and the announced squads |
| Series List & Archive | `/series`, `/series/archive` | Current series, and every series back to 1877 |
| Teams | `/teams`, `/teams/details`, `/teams/players` | 1,000+ teams with their current squads |
| Team Schedule, Results & Stats | `/teams/schedule`, `/teams/results`, `/teams/stats` | Fixtures, results and all-time leaderboards |
| Players | `/players/search`, `/players/details`, `/players/trending` | Find any cricketer and get the full profile |
| Player Form & Match Log | `/players/form`, `/players/matches` | Every innings, filterable by format and opponent |
| ICC Rankings & Standings | `/rankings`, `/standings` | Official rankings and the World Test Championship |
| Cricket Records | `/records`, `/records/types` | 15 record tables by format, year, team and opponent |
| Venue Details | `/venues/details` | A ground's profile and its Test, ODI and T20 records |
| News | `/news`, `/news/article`, `/news/topics`, `/news/topic`, `/news/author` | The newsroom, with full article text |
| Entity News | `/matches/news`, `/series/news`, `/teams/news`, `/players/news` | Stories tagged to any match, series, team or player |
| Photos & Videos | `/photos`, `/photos/gallery`, `/teams/photos`, `/videos`, `/videos/details` | Galleries and videos with stream links |
| IPL Auction | `/auction/players`, `/auction/search`, `/auction/seasons` | Who sold, for how much, to which franchise |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-cricbuzz-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-cricbuzz-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-cricbuzz-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/matches/scorecard",
    params={"match": "155409"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Cricbuzz Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Cricbuzz%20Scraper%20API.)

[![Ask Us by Email about Cricbuzz Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Cricbuzz%20Scraper%20API&body=I%20need%20help%20using%20the%20Cricbuzz%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**IMDb Scraper**](https://github.com/omkarcloud/imdb-scraper) — movies, TV, cast, ratings & box office
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/cricbuzz-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/cricbuzz-scraper)
