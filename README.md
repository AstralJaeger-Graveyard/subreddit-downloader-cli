# subreddit-downloader-cli

A cli tool to download a full subreddit
---
# Usage
In order to start the script the following requirements must be met:
- Python 3.11
- Poetry

## Setup:
1. ``poetry install``
2. Set environment variables:
   - ``temp_location``: Location for temporary files
   - ``data_location``: Location for files
   - ``reddit_cid``: Your reddit application client id 
   - ``reddit_cs``: Your reddit client secret 
   - ``imgur_cid``: Imgur Client ID
3. Run application with ``python main.py subreddit [subreddit ...]``
4. The application will tell you if environment variables are missing

