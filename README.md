# Women in Sports Data Visualisation 
---
This is a data visualisation project that focuses on comparing demand vs supply of womens sports in broadcasting using data from YouTube through their API v3. 
--- 

## How To Run
Download the project folder `womens-sports-tracker` and open in your code editor. Open the folder `data-vis-website` and open up `index.html` in your browser to view. No dependancies required.

---

### Explanation of Contents
- `data-vis-website` houses the html for the actual website of the final product
- `womens-sports-charts` inside is the html file that is a test of using my json data with d3 to make a line chart
- `youtube_data` houses all the data that is pulled from the API using the python scripts. There are csv, json, and database files clearly labelled of their contents
- `sample-parsing.py` is the script I wrote to parse my API data with pandas 
- `womens_sports_youtube_tracker.py` is the original script used to pull and save certain data from the YouTube API
- `V2womens_sports_youtube_tracker.py` is the second version of the above script that uses the ecosystem script to collect top videos from a range of channels using search terms


