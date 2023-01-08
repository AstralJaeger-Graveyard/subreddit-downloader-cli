# subreddit-downloader-cli

A cli tool to download a full subreddit
---
# Requirements
In order to start the script the following requirements must be met:
- Python 3.11
- Poetry

## Setup:
1. After cloning run ``poetry install``
2. Set environment variables:
   - ``imgur_cid``: Imgur Client ID (register an application on the [Imgur Developer portal](https://api.imgur.com/oauth2/addclient)
   - ``reddit_cid``: Your reddit application client id (Register an application on the [Reddit Developer Portal](https://old.reddit.com/prefs/apps/))
   - ``reddit_cs``: Your reddit client secret 
   - ``reddit_username``: *[Optional]* Your reddit username, being signed in provides a higher ratelimit
   - ``reddit_password``: *[Optional]* Your reddit password, only use together with ``reddit_username``
3. Run application with ``python main.py -d path/to/data subreddit [subreddit ...]``
4. The application will tell you if environment variables are missing

## Caveats and issues
All visited submissions by the script are stored in the ``meta/dupmap.json`` file, 
they contain the submission id and the absolute path to the file, 
if you wish to move your data folder to a different location, 
please ensure to update these paths.

The application also requires Python 3.11 due to the use of ``TaskGroups`` which were only added in it.

Due to the Reddit API limit, it will take around 15 minutes per 1000 posts (which is the limit of the API).
So please calculate 15-17 minutes per new subreddit and 1000 posts.