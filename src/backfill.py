"""Day one, run once. Seeds the actuals table so there is something to train on.

    python -m src.backfill
"""

from src.db import init_schema
from src.fetch import fetch_history, write_actuals


def main() -> None:
    print("Creating schema...")
    init_schema()

    print("Fetching history from Open-Meteo...")
    df = fetch_history(past_days=92)
    n = write_actuals(df)

    print(f"Wrote {n} hourly rows, {df['ts'].min()} to {df['ts'].max()}")
    print("Next: python -m src.train")


if __name__ == "__main__":
    main()
