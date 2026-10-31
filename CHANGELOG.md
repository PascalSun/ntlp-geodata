# Changelog

## 0.2.0 — 2026-10-31

- `report_manifest(anumbers)`: every file of many WAMEX reports with sizes and download links, in one manifest.
- `download_reports(anumbers, dest)`: downloads every file of many reports into `dest/A<n>/`, several at a time; re-running skips what is already complete.
- `report_files` and `doc_files` now work with a personal token (fixed on the platform).

## 0.1.0 — 2026-10-10

First public release, moved out of the platform repository and renamed from `geodata`.

- `GeoData` with a personal token (or `GEODATA_TOKEN`), 429 retries and paged iterators.
- What is there: `summary`, `catalog`, `catalog_item`, `datasets`, `search`.
- Around a point: `nearby`, `nearby_points`, `sites`.
- A region: `region_summary`, `drillhole_traces`, `geochem_stats`, `geochem_export`, `export_layers`, `export`, `download`.
- Documents: `wamex`, `report_files`, `doc_files`.
- Core scans: `core_holes`, `core_hole`, `core_metre`.
- SQL: `tables`, `describe`, `sql`.
- Whole datasets: `catalog_download`.
- Your data: `my_datasets`, `upload_dataset`.
- `to_dataframe` (with pandas).
