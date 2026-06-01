import json
import csv

### opens the JSON file and loads it into a python directory
with open('youtube_data/BWSL-24-25.json') as f:
    data = json.load(f)

videos_sorted = sorted(
    data["videos"],
    key=lambda x: x["views"],
    reverse=True
)

### prints the views and title of each video, sorted by views
# for video in videos_sorted:
#     print(video["views"], "-", video["title"])


### saves the views and title of each video, sorted by views to a CSV file
with open('BWSL_24-25_views_by_video.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)

    writer.writerow(['views', 'title'])

    for video in videos_sorted:
        writer.writerow([
            video["views"],
            video["title"]
        ])

print("Saved to BWSL_24-25_views_by_video.csv")


