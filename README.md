# ntlp-geodata

Python client for the [NTLP Geo Data Platform](https://geo.nlp-tlp.org): Western Australia's (and
increasingly all of Australia's) public geoscience data in one database — drillholes, assays,
WAMEX reports read page by page, HyLogger core scans, tenure, geophysics — behind one API.

```bash
pip install "git+https://github.com/PascalSun/ntlp-geodata@v0.1.0"
pip install "ntlp-geodata[pandas] @ git+https://github.com/PascalSun/ntlp-geodata@v0.1.0"   # with DataFrames
```

## Sign in

Create a **personal API token** on your account page,
[geo.nlp-tlp.org/account#tokens](https://geo.nlp-tlp.org/account#tokens) (a free account). *Read*
covers every query; *Read and write* also uploads and edits your own data.

```python
from ntlp_geodata import GeoData

gd = GeoData(token="gp_your_token_here")   # or set GEODATA_TOKEN in the environment
gd.me()                                     # who the token belongs to
```

The summary and `search` need no token.

## Quick start

The same steps as the guides on [geo.nlp-tlp.org/docs](https://geo.nlp-tlp.org/docs).

```python
gd.summary()                                            # what the platform holds
gd.catalog(q="drill")                                   # the data catalogue
gd.search("A38751")                                     # a report, hole, tenement or site by id

# around a point
gd.nearby(121.47, -30.75, radius_km=5, metal="Au")      # one aggregate answer
for f in gd.nearby_points(121.47, -30.75, radius_km=5, kind="drillhole"):
    ...                                                 # GeoJSON features, every page

# a region
gd.region_summary(121.3, -30.9, 121.7, -30.5, metal="Au")
ring = [(121.3, -30.9), (121.7, -30.9), (121.7, -30.5), (121.3, -30.5)]
gd.geochem_export("company_dh_collars", ring, "collars.zip")   # EarthBank-ready zip
job = gd.export("drillholes", bbox=(121.3, -30.9, 121.7, -30.5), format="csv")
gd.download(job["url"], "drillholes.csv")

# reports and documents
for r in gd.wamex(121.47, -30.75, nearby=True, radius_km=10):
    print(r["anumber"], r["year"], r["title"])
gd.report_files("A38751")                               # PDF and data-file links

# core scans
holes = list(gd.core_holes(state="WA"))
gd.core_hole(holes[0]["key"])
gd.core_metre(holes[0]["key"], 120)

# the database itself (read-only)
gd.tables()
gd.describe("mdhdb_raw.gswa_dh_collar")
for row in gd.sql("SELECT hole_id, max_depth FROM mdhdb_raw.gswa_dh_collar ORDER BY hole_id", max_rows=5000):
    ...

# a whole dataset as one file (built once per update; the first call can take minutes)
gd.catalog_download("hylogger-core-scans", format="csv", path="core_scans.csv")

# your own data (a Read and write token)
ds = gd.upload_dataset("soils.csv", name="Kalgoorlie soils", visibility="public")
print(f"https://geo.nlp-tlp.org/datasets/{ds['id']}")

# DataFrames (with pandas installed)
df = GeoData.to_dataframe(gd.sql("SELECT * FROM mdhdb_raw.gswa_dh_collar ORDER BY hole_id", max_rows=1000))
```

## Paging, limits and errors

- Lists come back as **iterators over every row**: the client follows each answer's `page.next`
  until there are no more pages. Pass `max_rows=` to stop early. Give SQL queries that span pages an
  `ORDER BY`, so pages do not overlap.
- The platform allows 600 requests a minute with a token (120 without), SQL 30 a minute and
  exports 10 an hour. A `429` is retried after the server's `Retry-After`, up to `retries=3` times.
- Any other error raises `GeoDataError` with `.status`, `.message` and the server's `.body`.

## Licences

The **code** is MIT. The **data** keeps its sources' licences — most of it CC BY 4.0 from the
Geological Survey of Western Australia / DMIRS, some non-commercial (Minedex, the interpreted faults,
bedrock geology and others). Each dataset's licence and the credit line to use are on its page at
[geo.nlp-tlp.org/data](https://geo.nlp-tlp.org/data) and in `gd.catalog_item(slug)`.

Built by NTLP and AI4WA at The University of Western Australia. Questions: pascal.sun@uwa.edu.au.
