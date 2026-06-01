# code by Claude AI Sonnet 4.6 — https://claude.ai
"""
Women's Sports YouTube Tracker
================================
Fetches channel stats and recent video view counts from official YouTube channels
for WNBA, Volleyball World (VNL), PWHL, and Barclays Women's Super League (WSL).

SETUP
-----
1. Get a free YouTube Data API v3 key:
   - Go to https://console.cloud.google.com
   - Create a project (or select an existing one)
   - Go to "APIs & Services" > "Library"
   - Search for "YouTube Data API v3" and enable it
   - Go to "APIs & Services" > "Credentials" > "Create Credentials" > "API Key"
   - Copy the key and paste it below (or set as environment variable)

2. Install dependencies:
   pip install google-api-python-client pandas

3. Run:
   python womens_sports_youtube_tracker.py

QUOTA NOTE
----------
The free tier gives you 10,000 units/day.
- Each channel stats lookup: ~3 units
- Each video search: 100 units
- Each batch of video stats (up to 50 videos): ~3 units
This script uses roughly 500-600 units per full run (well within the free quota).
"""

import os
import json
import time
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
import pandas as pd

# ── Configuration ────────────────────────────────────────────────────────────

API_KEY = os.environ.get("YOUTUBE_API_KEY", "YOUR_API_KEY_HERE")

# Official league channels (handle → channel ID resolved at runtime via search,
# or you can hardcode the IDs directly to save quota).
# Channel IDs confirmed May 2026.
LEAGUES = {
    # "WNBA": {
    #     "handle": "WNBA",             # youtube.com/@WNBA
    #     "label": "WNBA",
    #     "color": "#FF6B35",
    # },
    # "PWHL": {
    #     "handle": "thepwhlofficial",  # youtube.com/@thepwhlofficial
    #     "label": "PWHL",
    #     "color": "#A8DADC",
    # },
    "Barclays WSL": {
        "handle": "BarclaysWSL",      # youtube.com/@BarclaysWSL
        "label": "Barclays WSL",
        "color": "#E63946",
    },
}

# How many recent videos to pull per channel (used when not in historical mode)
VIDEOS_PER_CHANNEL = 20

# ── Historical year range ─────────────────────────────────────────────────────
# Set both values to fetch videos year-by-year for growth analysis.
# Set both to None to just fetch the most recent VIDEOS_PER_CHANNEL videos.
#
# NOTE on quota: each year x each league costs roughly 100-500 units.
# 5 years x 4 leagues = up to ~2,000 units — well within the 10,000 free daily limit
# unless channels have very large video libraries (100+ uploads per year).
#
START_YEAR = 2024   # Change to None to disable historical mode
END_YEAR   = 2025   # Change to None to disable historical mode

# ── Content filters ───────────────────────────────────────────────────────────
# Words in a video title that indicate men's content — filtered out per league.
# All comparisons are case-insensitive.

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


def is_excluded(title: str, league: str) -> bool:
    """Return True if the video title contains any excluded term for that league."""
    title_lower = title.lower()
    for term in EXCLUDE_TERMS_BY_LEAGUE.get(league, []):
        if term.lower() in title_lower:
            return True
    return False


# ── YouTube API helpers ───────────────────────────────────────────────────────

def get_youtube_client(api_key: str):
    """Build and return the YouTube API client."""
    return build("youtube", "v3", developerKey=api_key)


def resolve_handle_to_id(youtube, handle: str) -> str:
    """
    Resolve a YouTube @handle to its UC... channel ID.
    Uses the channels.list forHandle parameter (costs ~3 quota units).
    Raises ValueError if the handle can't be found.
    """
    response = youtube.channels().list(
        part="id,snippet",
        forHandle=handle
    ).execute()

    items = response.get("items", [])
    if not items:
        raise ValueError(
            f"Could not resolve @{handle} to a channel ID. "
            "Check the handle is correct and the channel is public."
        )
    channel_id = items[0]["id"]
    title = items[0]["snippet"]["title"]
    print(f"   🔍 Resolved @{handle} → {channel_id} ({title})")
    return channel_id


def get_channel_stats(youtube, channel_id: str) -> dict:
    """
    Fetch subscriber count, total view count, and video count for a channel.

    Returns a dict like:
        {
            "subscribers": 475000,
            "total_views": 123456789,
            "video_count": 1842,
            "channel_title": "WNBA"
        }
    """
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
        "subscribers": int(stats.get("subscriberCount", 0)),
        "total_views": int(stats.get("viewCount", 0)),
        "video_count": int(stats.get("videoCount", 0)),
    }


def get_recent_videos(youtube, channel_id: str, max_results: int = 20, league: str = "") -> list[dict]:
    """
    Fetch the most recent `max_results` videos uploaded by a channel.
    Filters out men's/off-topic content using EXCLUDE_TERMS_BY_LEAGUE.

    Uses search.list (costs 100 units) — results are then enriched with
    videos.list for statistics (costs ~3 units per 50-video batch).

    Note: we request more results than needed (up to 50) so that after
    filtering we still end up with close to max_results women's videos.
    """
    # Request extra to compensate for filtered-out videos
    fetch_count = min(max_results * 2, 50)

    # Step 1: search for recent uploads (100 quota units)
    search_response = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        maxResults=fetch_count,
        order="date",
        type="video"
    ).execute()

    video_ids = []
    basic_info = {}
    excluded_count = 0
    for item in search_response.get("items", []):
        vid_id = item["id"]["videoId"]
        title = item["snippet"]["title"]
        if is_excluded(title, league):
            excluded_count += 1
            continue
        video_ids.append(vid_id)
        basic_info[vid_id] = {
            "video_id": vid_id,
            "title": title,
            "published_at": item["snippet"]["publishedAt"],
        }

    if excluded_count:
        print(f"   🚫 Filtered out {excluded_count} non-women's videos")

    if not video_ids:
        return []

    # Step 2: get statistics for all videos in one batch (~3 quota units)
    stats_response = youtube.videos().list(
        part="statistics",
        id=",".join(video_ids)
    ).execute()

    results = []
    for item in stats_response.get("items", []):
        vid_id = item["id"]
        stats = item.get("statistics", {})
        entry = basic_info[vid_id].copy()
        entry.update({
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
        })
        results.append(entry)

    # Sort by published date descending, trim to requested amount
    results.sort(key=lambda x: x["published_at"], reverse=True)
    return results[:max_results]



def get_videos_in_range(
    youtube,
    channel_id: str,
    published_after: str,
    published_before: str,
    league: str = "",
    max_per_page: int = 50,
) -> list[dict]:
    """
    Fetch all videos published between two ISO-8601 timestamps for a channel.
    Handles pagination automatically (each page costs 100 quota units).

    Args:
        published_after:  ISO string e.g. "2022-01-01T00:00:00Z"
        published_before: ISO string e.g. "2022-12-31T23:59:59Z"
        league:           Used for content filtering via EXCLUDE_TERMS_BY_LEAGUE.
    """
    video_ids = []
    basic_info = {}
    next_page_token = None
    excluded_count = 0

    while True:
        params = dict(
            part="snippet",
            channelId=channel_id,
            maxResults=max_per_page,
            order="date",
            type="video",
            publishedAfter=published_after,
            publishedBefore=published_before,
        )
        if next_page_token:
            params["pageToken"] = next_page_token

        response = youtube.search().list(**params).execute()

        for item in response.get("items", []):
            vid_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            if is_excluded(title, league):
                excluded_count += 1
                continue
            video_ids.append(vid_id)
            basic_info[vid_id] = {
                "video_id": vid_id,
                "title": title,
                "published_at": item["snippet"]["publishedAt"],
            }

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    if excluded_count:
        print(f"      🚫 Filtered out {excluded_count} non-women's videos")

    if not video_ids:
        return []

    # Batch stats requests in groups of 50
    all_stats = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        stats_response = youtube.videos().list(
            part="statistics",
            id=",".join(batch)
        ).execute()
        all_stats.extend(stats_response.get("items", []))

    results = []
    for item in all_stats:
        vid_id = item["id"]
        stats = item.get("statistics", {})
        entry = basic_info[vid_id].copy()
        entry.update({
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
        })
        results.append(entry)

    results.sort(key=lambda x: x["published_at"], reverse=True)
    return results


def collect_yearly_data(
    youtube,
    channel_id: str,
    league: str,
    start_year: int,
    end_year: int,
) -> list[dict]:
    """
    Collect video data broken down by year, from start_year to end_year inclusive.
    Returns a flat list of video records, each with a 'year' field added.

    QUOTA NOTE: Each year window requires at least 1 search page (100 units).
    Channels with many videos per year may paginate and use more.
    Budget ~200-500 units per league per year window to be safe.
    """
    all_videos = []

    for year in range(start_year, end_year + 1):
        after  = f"{year}-01-01T00:00:00Z"
        before = f"{year}-12-31T23:59:59Z"
        print(f"      📅 Fetching {year}...", end=" ", flush=True)

        try:
            videos = get_videos_in_range(
                youtube, channel_id,
                published_after=after,
                published_before=before,
                league=league,
            )
            for v in videos:
                v["year"] = year
            all_videos.extend(videos)
            print(f"{len(videos)} videos found")
        except Exception as e:
            print(f"❌ Error: {e}")

        time.sleep(2)

    return all_videos


# ── Main data collection ──────────────────────────────────────────────────────

def collect_all_data(api_key: str, videos_per_channel: int = 20) -> dict:
    """
    Collect channel stats and recent video data for all leagues.
    Resolves @handles to channel IDs automatically at runtime.

    Returns a dict with two keys:
        "channel_stats": list of channel-level summaries
        "videos": list of video-level records (with a "league" field added)
    """
    youtube = get_youtube_client(api_key)

    channel_stats = []
    all_videos = []

    for league_name, config in LEAGUES.items():
        print(f"\n📊 Fetching data for: {league_name}")

        # Resolve @handle → channel ID
        try:
            channel_id = resolve_handle_to_id(youtube, config["handle"])
        except Exception as e:
            print(f"   ❌ Could not resolve handle @{config['handle']}: {e}")
            continue

        # Channel-level stats
        try:
            stats = get_channel_stats(youtube, channel_id)
            stats["league"] = league_name
            channel_stats.append(stats)
            print(f"   ✅ {stats['channel_title']}: "
                  f"{stats['subscribers']:,} subscribers | "
                  f"{stats['total_views']:,} total views")
        except Exception as e:
            print(f"   ❌ Channel stats failed: {e}")

        # Recent videos OR historical yearly breakdown
        try:
            if START_YEAR and END_YEAR:
                print(f"   📆 Collecting yearly data {START_YEAR}–{END_YEAR}...")
                videos = collect_yearly_data(
                    youtube, channel_id, league_name,
                    start_year=START_YEAR, end_year=END_YEAR,
                )
            else:
                videos = get_recent_videos(
                    youtube, channel_id, videos_per_channel, league=league_name
                )

            for v in videos:
                v["league"] = league_name
            all_videos.extend(videos)
            print(f"   ✅ Retrieved {len(videos)} videos total")
            if videos:
                top = max(videos, key=lambda x: x["views"])
                print(f"   🏆 Top video: '{top['title'][:60]}' — {top['views']:,} views")
        except Exception as e:
            print(f"   ❌ Video fetch failed: {e}")

        time.sleep(0.5)

    return {"channel_stats": channel_stats, "videos": all_videos}


def save_results(data: dict, output_dir: str = "."):
    """Save results to CSV, JSON, and SQLite for further analysis."""
    import sqlite3
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_date = datetime.now().isoformat()
    df_channels = None
    df_videos = None

    # Channel stats CSV
    if data["channel_stats"]:
        df_channels = pd.DataFrame(data["channel_stats"])
        df_channels["snapshot_date"] = snapshot_date
        path = os.path.join(output_dir, f"channel_stats_{timestamp}.csv")
        df_channels.to_csv(path, index=False)
        print(f"\n💾 Channel stats saved to: {path}")

    # Videos CSV
    if data["videos"]:
        df_videos = pd.DataFrame(data["videos"])
        df_videos["published_at"] = pd.to_datetime(df_videos["published_at"])
        df_videos["engagement_rate"] = (
            (df_videos["likes"] + df_videos["comments"]) /
            df_videos["views"].replace(0, 1)
        ).round(4)
        df_videos["snapshot_date"] = snapshot_date
        path = os.path.join(output_dir, f"videos_{timestamp}.csv")
        df_videos.to_csv(path, index=False)
        print(f"💾 Video data saved to: {path}")

    # JSON snapshot
    json_path = os.path.join(output_dir, f"snapshot_{timestamp}.json")
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"💾 Full snapshot saved to: {json_path}")

    # SQLite — appends each run so you build a history over time
    db_path = os.path.join(output_dir, "womens_sports.db")
    conn = sqlite3.connect(db_path)
    if df_channels is not None:
        df_channels.to_sql("channel_stats", conn, if_exists="append", index=False)
    if df_videos is not None:
        df_videos.to_sql("videos", conn, if_exists="append", index=False)
    conn.close()
    print(f"💾 Data appended to SQLite: {db_path}")

    return df_channels, df_videos


def print_summary(df_channels: pd.DataFrame, df_videos: pd.DataFrame):
    """Print a quick comparison summary to the console."""
    print("\n" + "="*60)
    print("CHANNEL SUMMARY")
    print("="*60)
    summary = df_channels[["league", "subscribers", "total_views", "video_count"]].copy()
    summary = summary.sort_values("subscribers", ascending=False)
    summary["subscribers"] = summary["subscribers"].apply(lambda x: f"{x:,}")
    summary["total_views"] = summary["total_views"].apply(lambda x: f"{x:,}")
    print(summary.to_string(index=False))

    print("\n" + "="*60)
    print("TOP 5 MOST-VIEWED RECENT VIDEOS (across all leagues)")
    print("="*60)
    top5 = df_videos.nlargest(5, "views")[["league", "title", "views", "published_at"]]
    top5["views"] = top5["views"].apply(lambda x: f"{x:,}")
    top5["title"] = top5["title"].str[:55]
    print(top5.to_string(index=False))

    print("\n" + "="*60)
    print("AVERAGE VIEWS PER RECENT VIDEO (by league)")
    print("="*60)
    avg_views = (
        df_videos.groupby("league")["views"]
        .agg(["mean", "median", "max", "count"])
        .sort_values("mean", ascending=False)
        .rename(columns={"mean": "avg_views", "median": "median_views",
                         "max": "top_video_views", "count": "videos_sampled"})
    )
    avg_views = avg_views.map(lambda x: f"{int(x):,}")
    print(avg_views.to_string())


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if API_KEY == "YOUR_API_KEY_HERE":
        print("⚠️  Please set your YouTube API key.")
        print("   Either edit API_KEY in this file, or run:")
        print("   export YOUTUBE_API_KEY=your_key_here")
        exit(1)

    print("🏆 Women's Sports YouTube Tracker")
    print("=" * 40)
    print(f"Tracking {len(LEAGUES)} leagues: {', '.join(LEAGUES.keys())}")

    data = collect_all_data(API_KEY, VIDEOS_PER_CHANNEL)

    if data["channel_stats"] or data["videos"]:
        df_ch, df_vid = save_results(data, output_dir="youtube_data")
        if df_ch is not None and df_vid is not None:
            print_summary(df_ch, df_vid)
    else:
        print("No data collected. Check your API key and channel IDs.")
