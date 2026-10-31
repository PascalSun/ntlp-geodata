"""Python client for the NTLP Geo Data Platform API (https://geo.nlp-tlp.org).

    from ntlp_geodata import GeoData
    gd = GeoData(token="gp_…")      # a personal API token from https://geo.nlp-tlp.org/account#tokens
    gd.summary()
    gd.nearby(121.47, -30.75, radius_km=10)
    for report in gd.wamex(121.47, -30.75, nearby=True):     # follows page.next for you
        print(report["anumber"], report["title"])
    for row in gd.sql("SELECT hole_id, max_depth FROM mdhdb_raw.gswa_dh_collar ORDER BY hole_id"):
        ...

Responses are plain dicts. Paged endpoints come back as iterators over all rows; pass
`max_rows` to stop early. A 429 is retried after the server's Retry-After (up to `retries`).
"""
__version__ = "0.2.0"

from .client import GeoData, GeoDataError  # noqa: E402 - __version__ first: the client reads it

__all__ = ["GeoData", "GeoDataError", "__version__"]
