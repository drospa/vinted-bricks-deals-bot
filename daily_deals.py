"""Daily Lego deals digest: entry point used by the GitHub workflow (python daily_deals.py).
The code lives in the legobot package; settings in config.toml. See README.md."""
from legobot.app import main

if __name__ == "__main__":
    main()
