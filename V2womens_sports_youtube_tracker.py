# code by Claude AI Sonnet 4.6 — https://claude.ai
"""
Women's Sports YouTube Tracker
================================
Two complementary data collection modes:

  1. CHANNEL MODE (original)
     Fetches stats from official league channels — subscriber counts,
     total views, and recent/historical video-level data.

  2. ECOSYSTEM MODE (new)
     Searches YouTube broadly for each league by keyword, year by year.
     Captures fan uploads, broadcaster clips, and media coverage —
     not just what the league officially posted. This is the richer
     signal for tracking long-term growth since it doesn't depend on
     when an official channel was created.

     For each league + year it collects the top 50 videos by view count
     and calculates:
       - total ecosystem views (sum)
       - average views per video
       - average engagement rate
       - number of videos found (supply-side signal)

SETUP
-----
1. Get a free YouTube Data API v3 key:
   - Go to https://console.cloud.google.com
   - Create a project → APIs & Services → Library
   - Search "YouTube Data API v3" and enable it
   - Credentials → Create Credentials → API Key

2. Install dependencies:
   pip install google-api-python-client pandas

3. Run:
   python womens_sports_youtube_tracker.py

QUOTA GUIDE
-----------
Free tier: 10,000 units/day
- Channel stats lookup:          ~3 units
- Each search page (50 results): 100 units
- Video stats batch (50 videos):  ~3 units

Ecosystem mode (10 years × 3 leagues):
  Each year/league = 1 search (100) + 1 stats batch (~3) = ~103 units
  Full run = ~103 × 30 = ~3,090 units  (well within daily free limit)
"""

import os
import json
import sqlite3
import time
from datetime import datetime, timezone
from googleapiclient.discovery import build
import pandas as pd

# ── Configuration ─────────────────────────────────────────────────────────────

API_KEY = os.environ.get("YOUTUBE_API_KEY", "YOUR_API_KEY_HERE")

# ── League definitions ────────────────────────────────────────────────────────
# Each league has:
#   handle       — official YouTube @handle (resolved to channel ID at runtime)
#   search_terms — list of queries used in ecosystem mode; results are merged
#                  and deduplicated. More terms = richer coverage but more quota.
#   color        — hex colour for dashboard charts

LEAGUES = {
    "WNBA": {
        "handle": "WNBA",
        "search_terms": [
            "WNBA highlights",
            "WNBA women's basketball",
        ],
        "color": "#FF6B35",
    },
    "PWHL": {
        "handle": "thepwhlofficial",
        "search_terms": [
            "professional women's hockey league",
            "PWHL highlights",
            "Women's Hockey",
        ],
        "color": "#A8DADC",
    },
    "Barclays WSL": {
        "handle": "BarclaysWSL",
        "search_terms": [
            "Barclays WSL football",
            "WSL football highlights",
            "women's football"
        ],
        "color": "#E63946",
    },
}

# ── Mode switches ─────────────────────────────────────────────────────────────

# ECOSYSTEM MODE — set year range for broad keyword search across YouTube
# Set to None to skip ecosystem collection
ECOSYSTEM_START_YEAR = 2018
ECOSYSTEM_END_YEAR   = 2025

# How many top videos to pull per search term per year (max 50)
# These are ordered by view count so you always get the most-watched content
ECOSYSTEM_TOP_N = 35

# CHANNEL MODE — set year range for official channel video history
# Set to None to just fetch the VIDEOS_PER_CHANNEL most recent videos
CHANNEL_START_YEAR = None
CHANNEL_END_YEAR   = None
VIDEOS_PER_CHANNEL = 15   # used when CHANNEL_START_YEAR is None

# ── Content filters ───────────────────────────────────────────────────────────
# Titles containing these terms are excluded from results.
# Applies to both channel and ecosystem modes.

EXCLUDE_TERMS_BY_LEAGUE = {
    "WNBA": [
        "nba", "lakers", "celtics", "warriors", "bulls", "heat", "nets",
        "knicks", "bucks", "suns", "nuggets", "clippers", "spurs", "mavs",
        "mavericks", "rockets", "76ers", "sixers", "pistons", "pacers",
        "hornets", "hawks", "magic", "wizards", "kings", "jazz", "thunder",
        "blazers", "grizzlies", "pelicans", "raptors", "timberwolves",
        "lebron", "curry", "durant", "giannis", "embiid", "luka", "wembanyama",
        "men's",
    ],
    "PWHL": [],
    "Barclays WSL": [],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_youtube_client(api_key: str):
    return build("youtube", "v3", developerKey=api_key)


def is_excluded(title: str, league: str) -> bool:
    title_lower = title.lower()
    for term in EXCLUDE_TERMS_BY_LEAGUE.get(league, []):
        if term.lower() in title_lower:
            return True
    return False


def resolve_handle_to_id(youtube, handle: str) -> str:
    """Resolve a YouTube @handle to its UC... channel ID (~3 quota units)."""
    response = youtube.channels().list(
        part="id,snippet",
        forHandle=handle
    ).execute()
    items = response.get("items", [])
    if not items:
        raise ValueError(f"Could not resolve @{handle}. Check the handle is correct.")
    channel_id = items[0]["id"]
    title = items[0]["snippet"]["title"]
    print(f"   🔍 @{handle} → {channel_id} ({title})")
    return channel_id


def get_channel_stats(youtube, channel_id: str) -> dict:
    """Fetch subscriber count, total views, video count for a channel."""
    response = youtube.channels().list(
        part="statistics,snippet",
        id=channel_id
    ).execute()
    if not response.get("items"):
        raise ValueError(f"No channel found for ID: {channel_id}")
    item = response["items"][0]
    stats = item["statistics"]
    return {
        "channel_title": item["snippet"]["title"],
        "subscribers":   int(stats.get("subscriberCount", 0)),
        "total_views":   int(stats.get("viewCount", 0)),
        "video_count":   int(stats.get("videoCount", 0)),
    }


def fetch_video_stats_batch(youtube, video_ids: list[str]) -> dict:
    """
    Fetch statistics for up to 50 video IDs in one API call (~3 quota units).
    Returns a dict of {video_id: {views, likes, comments}}.
    """
    if not video_ids:
        return {}
    response = youtube.videos().list(
        part="statistics",
        id=",".join(video_ids[:50])
    ).execute()
    result = {}
    for item in response.get("items", []):
        s = item.get("statistics", {})
        result[item["id"]] = {
            "views":    int(s.get("viewCount", 0)),
            "likes":    int(s.get("likeCount", 0)),
            "comments": int(s.get("commentCount", 0)),
        }
    return result


# ── Channel mode ──────────────────────────────────────────────────────────────

def get_videos_in_range(
    youtube, channel_id: str,
    published_after: str, published_before: str,
    league: str = "",
) -> list[dict]:
    """
    Fetch all videos from a channel within a date range, with pagination.
    Each page costs 100 quota units.
    """
    video_ids, basic_info, excluded_count = [], {}, 0
    next_page_token = None

    while True:
        params = dict(
            part="snippet", channelId=channel_id, maxResults=50,
            order="date", type="video",
            publishedAfter=published_after, publishedBefore=published_before,
        )
        if next_page_token:
            params["pageToken"] = next_page_token
        response = youtube.search().list(**params).execute()

        for item in response.get("items", []):
            vid_id = item["id"]["videoId"]
            title  = item["snippet"]["title"]
            if is_excluded(title, league):
                excluded_count += 1
                continue
            video_ids.append(vid_id)
            basic_info[vid_id] = {
                "video_id": vid_id, "title": title,
                "published_at": item["snippet"]["publishedAt"],
            }

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    if excluded_count:
        print(f"      🚫 Filtered {excluded_count} non-women's videos")

    if not video_ids:
        return []

    stats_map = fetch_video_stats_batch(youtube, video_ids)
    results = []
    for vid_id in video_ids:
        entry = basic_info[vid_id].copy()
        entry.update(stats_map.get(vid_id, {"views": 0, "likes": 0, "comments": 0}))
        results.append(entry)

    results.sort(key=lambda x: x["published_at"], reverse=True)
    return results


def get_recent_videos(youtube, channel_id: str, max_results: int = 20, league: str = "") -> list[dict]:
    """Fetch the most recent videos from a channel."""
    fetch_count = min(max_results * 2, 50)
    response = youtube.search().list(
        part="snippet", channelId=channel_id,
        maxResults=fetch_count, order="date", type="video"
    ).execute()

    video_ids, basic_info, excluded_count = [], {}, 0
    for item in response.get("items", []):
        vid_id = item["id"]["videoId"]
        title  = item["snippet"]["title"]
        if is_excluded(title, league):
            excluded_count += 1
            continue
        video_ids.append(vid_id)
        basic_info[vid_id] = {
            "video_id": vid_id, "title": title,
            "published_at": item["snippet"]["publishedAt"],
        }

    if excluded_count:
        print(f"   🚫 Filtered {excluded_count} non-women's videos")
    if not video_ids:
        return []

    stats_map = fetch_video_stats_batch(youtube, video_ids)
    results = []
    for vid_id in video_ids:
        entry = basic_info[vid_id].copy()
        entry.update(stats_map.get(vid_id, {"views": 0, "likes": 0, "comments": 0}))
        results.append(entry)

    results.sort(key=lambda x: x["published_at"], reverse=True)
    return results[:max_results]


# ── Ecosystem mode ────────────────────────────────────────────────────────────

def search_ecosystem_videos(
    youtube,
    query: str,
    published_after: str,
    published_before: str,
    league: str = "",
    max_results: int = 50,
) -> list[dict]:
    """
    Search all of YouTube for a query within a date window, ordered by view count.
    Returns up to max_results videos with full stats.
    Costs 100 units for the search + ~3 units for stats batch.
    """
    response = youtube.search().list(
        part="snippet",
        q=query,
        type="video",
        order="viewCount",          # ← top videos by views, not recency
        publishedAfter=published_after,
        publishedBefore=published_before,
        maxResults=min(max_results, 50),
        relevanceLanguage="en",
    ).execute()

    video_ids, basic_info, excluded_count = [], {}, 0
    for item in response.get("items", []):
        vid_id = item["id"]["videoId"]
        title  = item["snippet"]["title"]
        if is_excluded(title, league):
            excluded_count += 1
            continue
        video_ids.append(vid_id)
        basic_info[vid_id] = {
            "video_id":    vid_id,
            "title":       title,
            "channel":     item["snippet"]["channelTitle"],
            "published_at": item["snippet"]["publishedAt"],
        }

    if excluded_count:
        print(f"         🚫 Filtered {excluded_count} non-women's videos")
    if not video_ids:
        return []

    stats_map = fetch_video_stats_batch(youtube, video_ids)
    results = []
    for vid_id in video_ids:
        entry = basic_info[vid_id].copy()
        entry.update(stats_map.get(vid_id, {"views": 0, "likes": 0, "comments": 0}))
        results.append(entry)

    results.sort(key=lambda x: x["views"], reverse=True)
    return results


def collect_ecosystem_data(
    youtube,
    league_name: str,
    search_terms: list[str],
    start_year: int,
    end_year: int,
    top_n: int = 50,
) -> tuple[list[dict], list[dict]]:
    """
    For each year in range, search YouTube for each search term, merge and
    deduplicate results, then compute yearly aggregate stats.

    Returns:
        videos_rows  — one row per video (for the detailed table)
        summary_rows — one row per year (total views, avg views, etc.)
    """
    all_video_rows  = []
    all_summary_rows = []

    for year in range(start_year, end_year + 1):
        after  = f"{year}-01-01T00:00:00Z"
        before = f"{year}-12-31T23:59:59Z"
        print(f"      📅 {year}", end="", flush=True)

        seen_ids = {}   # video_id → record; deduplicates across search terms

        for term in search_terms:
            print(f" [{term[:30]}]", end="", flush=True)
            try:
                videos = search_ecosystem_videos(
                    youtube, query=term,
                    published_after=after, published_before=before,
                    league=league_name, max_results=top_n,
                )
                for v in videos:
                    # Keep highest-view version if same video appears in multiple searches
                    if v["video_id"] not in seen_ids or v["views"] > seen_ids[v["video_id"]]["views"]:
                        seen_ids[v["video_id"]] = v
            except Exception as e:
                print(f" ❌{e}", end="")
            time.sleep(2)

        videos_this_year = list(seen_ids.values())
        videos_this_year.sort(key=lambda x: x["views"], reverse=True)

        # Tag each video record
        for v in videos_this_year:
            v["year"]   = year
            v["league"] = league_name
        all_video_rows.extend(videos_this_year)

        # Compute yearly aggregates
        if videos_this_year:
            views_list = [v["views"] for v in videos_this_year]
            eng_list   = [
                (v["likes"] + v["comments"]) / max(v["views"], 1)
                for v in videos_this_year
            ]
            all_summary_rows.append({
                "league":            league_name,
                "year":              year,
                "video_count":       len(videos_this_year),
                "total_views":       sum(views_list),
                "avg_views":         round(sum(views_list) / len(views_list)),
                "median_views":      sorted(views_list)[len(views_list) // 2],
                "top_video_views":   max(views_list),
                "avg_engagement_rate": round(sum(eng_list) / len(eng_list), 4),
                "top_video_title":   videos_this_year[0]["title"][:80],
            })
            print(f" → {len(videos_this_year)} videos, {sum(views_list):,} total views")
        else:
            print(" → no results")

        time.sleep(3)

    return all_video_rows, all_summary_rows


# ── Orchestration ─────────────────────────────────────────────────────────────

def collect_all_data(api_key: str) -> dict:
    """
    Run both channel mode and ecosystem mode for all leagues.
    Returns a dict with keys:
        channel_stats   — current subscriber/view counts per league
        channel_videos  — per-video rows from official channels
        ecosystem_videos  — per-video rows from broad YouTube search
        ecosystem_summary — yearly aggregate rows (the core trend dataset)
    """
    youtube = get_youtube_client(api_key)

    channel_stats      = []
    channel_videos     = []
    ecosystem_videos   = []
    ecosystem_summary  = []

    for league_name, config in LEAGUES.items():
        print(f"\n{'='*55}")
        print(f"📊  {league_name}")
        print(f"{'='*55}")

        # ── Resolve channel handle ──────────────────────────────
        try:
            channel_id = resolve_handle_to_id(youtube, config["handle"])
        except Exception as e:
            print(f"   ❌ Handle resolution failed: {e}")
            channel_id = None

        # ── Channel stats ───────────────────────────────────────
        if channel_id:
            try:
                stats = get_channel_stats(youtube, channel_id)
                stats["league"] = league_name
                channel_stats.append(stats)
                print(f"   ✅ {stats['subscribers']:,} subscribers | "
                      f"{stats['total_views']:,} total views")
            except Exception as e:
                print(f"   ❌ Channel stats failed: {e}")

        # ── Channel videos ──────────────────────────────────────
        if channel_id:
            try:
                if CHANNEL_START_YEAR and CHANNEL_END_YEAR:
                    print(f"   📆 Channel videos {CHANNEL_START_YEAR}–{CHANNEL_END_YEAR}...")
                    vids = []
                    for year in range(CHANNEL_START_YEAR, CHANNEL_END_YEAR + 1):
                        after  = f"{year}-01-01T00:00:00Z"
                        before = f"{year}-12-31T23:59:59Z"
                        print(f"      📅 {year}...", end=" ", flush=True)
                        batch = get_videos_in_range(
                            youtube, channel_id, after, before, league=league_name
                        )
                        for v in batch:
                            v["year"] = year
                        vids.extend(batch)
                        print(f"{len(batch)} videos")
                        time.sleep(0.5)
                else:
                    vids = get_recent_videos(
                        youtube, channel_id, VIDEOS_PER_CHANNEL, league=league_name
                    )

                for v in vids:
                    v["league"] = league_name
                channel_videos.extend(vids)
                print(f"   ✅ {len(vids)} channel videos collected")
            except Exception as e:
                print(f"   ❌ Channel video fetch failed: {e}")

        # ── Ecosystem search ────────────────────────────────────
        if ECOSYSTEM_START_YEAR and ECOSYSTEM_END_YEAR:
            print(f"\n   🌐 Ecosystem search {ECOSYSTEM_START_YEAR}–{ECOSYSTEM_END_YEAR}...")
            try:
                vid_rows, sum_rows = collect_ecosystem_data(
                    youtube,
                    league_name=league_name,
                    search_terms=config["search_terms"],
                    start_year=ECOSYSTEM_START_YEAR,
                    end_year=ECOSYSTEM_END_YEAR,
                    top_n=ECOSYSTEM_TOP_N,
                )
                ecosystem_videos.extend(vid_rows)
                ecosystem_summary.extend(sum_rows)
                print(f"   ✅ Ecosystem: {len(vid_rows)} videos across "
                      f"{ECOSYSTEM_END_YEAR - ECOSYSTEM_START_YEAR + 1} years")
            except Exception as e:
                print(f"   ❌ Ecosystem collection failed: {e}")

        time.sleep(5)

    return {
        "channel_stats":      channel_stats,
        "channel_videos":     channel_videos,
        "ecosystem_videos":   ecosystem_videos,
        "ecosystem_summary":  ecosystem_summary,
    }


# ── Save ──────────────────────────────────────────────────────────────────────

def save_results(data: dict, output_dir: str = "youtube_data") -> dict:
    """Save all datasets to CSV, JSON, and SQLite."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp     = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_date = datetime.now().isoformat()
    dataframes    = {}

    def _add_engagement(df: pd.DataFrame) -> pd.DataFrame:
        df["engagement_rate"] = (
            (df["likes"] + df["comments"]) / df["views"].replace(0, 1)
        ).round(4)
        return df

    # Build dataframes
    if data["channel_stats"]:
        df = pd.DataFrame(data["channel_stats"])
        df["snapshot_date"] = snapshot_date
        dataframes["channel_stats"] = df

    if data["channel_videos"]:
        df = pd.DataFrame(data["channel_videos"])
        df["published_at"] = pd.to_datetime(df["published_at"])
        df["snapshot_date"] = snapshot_date
        dataframes["channel_videos"] = _add_engagement(df)

    if data["ecosystem_videos"]:
        df = pd.DataFrame(data["ecosystem_videos"])
        df["published_at"] = pd.to_datetime(df["published_at"])
        df["snapshot_date"] = snapshot_date
        dataframes["ecosystem_videos"] = _add_engagement(df)

    if data["ecosystem_summary"]:
        df = pd.DataFrame(data["ecosystem_summary"])
        df["snapshot_date"] = snapshot_date
        dataframes["ecosystem_summary"] = df

    # CSV
    print("\n💾 Saving files...")
    for name, df in dataframes.items():
        path = os.path.join(output_dir, f"{name}_{timestamp}.csv")
        df.to_csv(path, index=False)
        print(f"   {path}  ({len(df)} rows)")

    # JSON snapshot
    json_path = os.path.join(output_dir, f"snapshot_{timestamp}.json")
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"   {json_path}")

    # SQLite (append — each run adds to history)
    db_path = os.path.join(output_dir, "womens_sports.db")
    conn = sqlite3.connect(db_path)
    for name, df in dataframes.items():
        df.to_sql(name, conn, if_exists="append", index=False)
    conn.close()
    print(f"   {db_path}  (SQLite, appended)")

    return dataframes


# ── Summary print ─────────────────────────────────────────────────────────────

def print_summary(dataframes: dict):
    print("\n" + "="*60)

    if "ecosystem_summary" in dataframes:
        df = dataframes["ecosystem_summary"]
        print("ECOSYSTEM GROWTH SUMMARY (avg views per video, by year)")
        print("="*60)
        pivot = df.pivot_table(
            index="year", columns="league", values="avg_views", aggfunc="mean"
        ).fillna(0).astype(int)
        print(pivot.to_string())

        print("\nTOTAL ECOSYSTEM VIEWS PER YEAR")
        print("-"*60)
        pivot2 = df.pivot_table(
            index="year", columns="league", values="total_views", aggfunc="sum"
        ).fillna(0).astype(int)
        print(pivot2.to_string())

    if "channel_stats" in dataframes:
        print("\nCURRENT CHANNEL STATS")
        print("="*60)
        df = dataframes["channel_stats"][
            ["league", "subscribers", "total_views", "video_count"]
        ].sort_values("subscribers", ascending=False)
        df["subscribers"]  = df["subscribers"].apply(lambda x: f"{x:,}")
        df["total_views"]  = df["total_views"].apply(lambda x: f"{x:,}")
        print(df.to_string(index=False))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if API_KEY == "YOUR_API_KEY_HERE":
        print("⚠️  Please set your YouTube API key:")
        print("   export YOUTUBE_API_KEY=your_key_here")
        exit(1)

    print("🏆 Women's Sports YouTube Tracker")
    print(f"   Leagues:    {', '.join(LEAGUES.keys())}")
    if ECOSYSTEM_START_YEAR:
        print(f"   Ecosystem:  {ECOSYSTEM_START_YEAR}–{ECOSYSTEM_END_YEAR} "
              f"(top {ECOSYSTEM_TOP_N} videos/year/term)")
    if CHANNEL_START_YEAR:
        print(f"   Channel:    {CHANNEL_START_YEAR}–{CHANNEL_END_YEAR}")
    else:
        print(f"   Channel:    {VIDEOS_PER_CHANNEL} most recent videos")

    data       = collect_all_data(API_KEY)
    dataframes = save_results(data, output_dir="youtube_data")
    print_summary(dataframes)
