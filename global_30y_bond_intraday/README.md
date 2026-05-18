# global_30y_bond_intraday

Builds a UTC-day intraday overview for 30Y sovereign yield moves in the US, Japan, Korea, and the UK.

The chart uses UTC+0 from `00:00` to `23:59`. The y-axis is the move from each market's configured local open in basis points. Raw timestamps are converted to UTC. Minute gaps up to 10 minutes are forward-filled; longer gaps remain empty.

## Usage

```powershell
python global_30y_bond_intraday\cli.py --date 2026-05-18
```

Download and cache the available minute data for a UTC year:

```powershell
python global_30y_bond_intraday\cli.py --download-year 2026
```

Build the current chart plus cached historical date pages:

```powershell
python global_30y_bond_intraday\cli.py --build-history
```

Optional paths:

```powershell
python global_30y_bond_intraday\cli.py --date 2026-05-18 --output-html site\charts\global-rates\global-30y-bond-intraday.html --summary-csv site\data\global-rates\global-30y-bond-intraday.csv
```

## CSV input

CSV files are configured in `config.yaml`. The default format is:

```csv
timestamp,yield
2026-05-18 09:00:00,2.345
2026-05-18 09:01:00,2.346
```

If a CSV timestamp has no timezone, it is interpreted in that market's configured local timezone. If the timestamp already has an offset, the offset is used and the value is converted to UTC.

`yield_unit` can be `percent`, `decimal`, or `bp`. `value_scale` is applied before unit conversion. The default US Yahoo symbol is `^TYX`, with `value_scale: 0.1`.

## Free minute data limits

This project does not use paid APIs. The Yahoo provider uses the free Yahoo chart endpoint for recent 1-minute data when it is available. Free intraday coverage can be delayed, short-lived, rate-limited, blocked, or absent for some symbols.

Japan, Korea, and UK 30Y minute data are configured as CSV sources because reliable official free minute APIs are not generally available for these yields. Missing CSV files or missing rows are not fabricated. With the default optional source settings, the site still builds and the affected market appears as `No data` in the summary.

Yahoo 1-minute history is short-lived. When old dates are outside the free lookback window, the downloader records `skipped_lookback_limit` in `data/global_30y_bond_intraday/download_report.csv`.
