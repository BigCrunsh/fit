# fit

Goal-agnostic personal fitness data platform. Ingests from Garmin, Fitdays, Apple Health, and weather APIs into a single SQLite database.

## Setup

```bash
cp config.yaml config.local.yaml  # edit with your personal values
pip install -r requirements.txt
fit sync
```

## CLI

- `fit sync` — pull data from Garmin, enrich with weather, store in SQLite
- `fit checkin` — interactive daily check-in logger
- `fit report` — generate HTML dashboard
- `fit status` — quick overview of data and goals
