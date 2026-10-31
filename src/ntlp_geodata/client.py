"""The client: one class, one method per thing you can get from the platform."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import httpx

from . import __version__

DEFAULT_BASE_URL = "https://platform.nlp-tlp.org"

Point = Sequence[float]          # (lon, lat)
BBox = Sequence[float]           # (west, south, east, north)


class GeoDataError(Exception):
    """An answer the client could not turn into data: carries the HTTP status and the server's message."""

    def __init__(self, status: int, message: str, body: Any = None):
        super().__init__(f"{status}: {message}")
        self.status, self.message, self.body = status, message, body


def _poly_param(ring: Iterable[Point]) -> str:
    """[(lon, lat), …] → the `lon lat,lon lat,…` form the region endpoints take."""
    return ",".join(f"{float(x)} {float(y)}" for x, y in ring)


class GeoData:
    """A session with the NTLP Geo Data Platform.

    token     a personal API token (``gp_…``) from https://geo.nlp-tlp.org/account#tokens, or the
              ``GEODATA_TOKEN`` environment variable. The summary, search and tiles need none.
    base_url  the platform API, https://platform.nlp-tlp.org by default.
    retries   how many times a 429 (rate limited) is retried after the server's Retry-After.
    """

    def __init__(self, token: str | None = None, base_url: str = DEFAULT_BASE_URL, *,
                 timeout: float = 60.0, retries: int = 3, client: httpx.Client | None = None):
        token = token or os.environ.get("GEODATA_TOKEN")
        headers = {"User-Agent": f"ntlp-geodata/{__version__}"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self._http = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._http.headers.update(headers)

    # ------------------------------------------------------------- transport --
    def _send(self, method: str, url: str, **kw) -> httpx.Response:
        if url.startswith("/"):
            url = self.base_url + url
        for attempt in range(self.retries + 1):
            r = self._http.request(method, url, **kw)
            if r.status_code == 429 and attempt < self.retries:
                time.sleep(float(r.headers.get("Retry-After", "1")))
                continue
            if r.status_code >= 400:
                try:
                    body = r.json()
                    msg = body.get("message") or body.get("detail") or body.get("error") or r.text
                except ValueError:
                    body, msg = None, r.text
                raise GeoDataError(r.status_code, str(msg)[:500], body)
            return r
        raise GeoDataError(429, "rate limited")   # unreachable: the loop returns or raises

    def _request(self, method: str, url: str, **kw) -> Any:
        return self._send(method, url, **kw).json()

    def get(self, path: str, **params) -> Any:
        """GET any platform path (or a full ``page.next`` URL) and return its JSON."""
        clean = {k: v for k, v in params.items() if v is not None}
        # only pass params when there are some: httpx replaces a URL's own query string with
        # `params`, and a page.next URL carries its offset in that query string
        return self._request("GET", path, **({"params": clean} if clean else {}))

    def post(self, path: str, body: dict) -> Any:
        """POST a JSON body to any platform path and return its JSON."""
        return self._request("POST", path, json=body)

    def _pages(self, first: dict, key: str, follow, max_rows: int | None) -> Iterator[dict]:
        """Yield rows under `key` page after page until page.next is null (or max_rows)."""
        page, n = first, 0
        while True:
            for row in page.get(key) or []:
                yield row
                n += 1
                if max_rows is not None and n >= max_rows:
                    return
            nxt = (page.get("page") or {}).get("next")
            if not nxt:
                return
            page = follow(nxt)

    # ------------------------------------------------------------ the account --
    def me(self) -> dict:
        """Who the token belongs to (email, whether it is verified)."""
        return self.get("/authenticate/api/me/")

    # ------------------------------------------------------------ what is there --
    def summary(self) -> dict:
        """What the platform holds: counts per family and the database size. No token needed."""
        return self.get("/geo/api/platform/summary/")

    def catalog(self, q: str | None = None, family: str | None = None) -> Any:
        """The data catalogue: every dataset with its rows, coverage, licence and update."""
        return self.get("/geo/api/catalog/", q=q, family=family)

    def catalog_item(self, slug: str) -> dict:
        """One dataset: fields, coverage outline, licence, citation, download status, update history."""
        return self.get(f"/geo/api/catalog/{slug}/")

    def datasets(self, max_rows: int | None = None) -> Iterator[dict]:
        """Dataset provenance and licences (the older listing the catalogue extends)."""
        return self._pages(self.get("/geo/api/datasets/"), "datasets", lambda u: self.get(u), max_rows)

    def search(self, q: str, limit: int = 8) -> list[dict]:
        """Find a drillhole id, company collar id, WAMEX A-number, tenement id, Minedex site or
        core-scan hole by the start of its name. Each result has kind, label, detail, lon, lat
        (and bbox/ring for tenements and reports). Place names are not searched."""
        return self.get("/geo/api/search/", q=q, limit=limit).get("results", [])

    # --------------------------------------------------------- around a point --
    def nearby(self, lon: float, lat: float, radius_km: float = 10, metal: str | None = None) -> dict:
        """Drillholes, samples, assay highlights, reports and tenure around a point (one answer)."""
        return self.get("/geo/api/nearby/", lon=lon, lat=lat, radius_km=radius_km, metal=metal)

    def nearby_points(self, lon: float, lat: float, radius_km: float = 10, kind: str | None = None,
                      limit: int = 2500, max_rows: int | None = None) -> Iterator[dict]:
        """GeoJSON features around a point; `kind` (e.g. "drillhole") walks one layer's pages."""
        first = self.get("/geo/api/nearby_points/", lon=lon, lat=lat, radius_km=radius_km, kind=kind, limit=limit)
        return self._pages(first, "features", lambda u: self.get(u), max_rows)

    def sites(self, metal: str | None = None, limit: int = 1000, max_rows: int | None = None) -> Iterator[dict]:
        """Minedex sites and known occurrences (for a commodity), as GeoJSON features."""
        first = self.get("/geo/api/sites/", metal=metal, limit=limit)
        return self._pages(first, "features", lambda u: self.get(u), max_rows)

    # ------------------------------------------------------------- a region --
    def region_summary(self, west: float, south: float, east: float, north: float,
                       metal: str | None = None) -> dict:
        """Counts and headline figures for a bounding box: tenure, sites, drillholes, geochemistry
        (count and max Au), reports, land access."""
        return self.get("/geo/api/region_summary/", west=west, south=south, east=east, north=north, metal=metal)

    def drillhole_traces(self, west: float, south: float, east: float, north: float,
                         poly: Iterable[Point] | None = None) -> dict:
        """Company drillholes in a box (or polygon) with their downhole assay intervals and
        desurveyed traces — what the 3D viewer draws."""
        return self.get("/geo/api/drillhole_traces/", west=west, south=south, east=east, north=north,
                        poly=_poly_param(poly) if poly is not None else None)

    def geochem_stats(self, layer: str) -> dict:
        """Per-element value ranges of a geochemistry point layer."""
        return self.get("/geo/api/geochem/stats/", layer=layer)

    def geochem_export(self, layer: str, poly: Iterable[Point], path: str | os.PathLike) -> Path:
        """The points of one geochemistry layer inside a polygon, as an EarthBank-ready zip written
        to `path`. Layers: assay_samples, company_surface_geochem, company_dh_collars. Capped at
        50,000 points; draw a smaller polygon if the readme says the cap was hit."""
        r = self._send("GET", "/geo/api/geochem/export/", params={"layer": layer, "poly": _poly_param(poly)})
        out = Path(path)
        out.write_bytes(r.content)
        return out

    def export_layers(self) -> list[dict]:
        """The layers `export` accepts, with their sizes and whether they need a bbox."""
        return self.get("/geo/api/export/").get("layers", [])

    def export(self, layer: str, bbox: BBox | None = None, poly: Iterable[Point] | None = None,
               format: str = "geojson", **filters) -> dict:
        """Export a layer within a bbox (west, south, east, north) or polygon to a file on the
        platform. Returns {count, returned, url, …}; `url` is a time-limited download link (see
        `download`). Large layers such as drillholes need a bbox."""
        body: dict[str, Any] = {"layer": layer, "format": format, **filters}
        if bbox is not None:
            body["bbox"] = [float(v) for v in bbox]
        if poly is not None:
            body["poly"] = [[float(x), float(y)] for x, y in poly]
        return self.post("/geo/api/export/", body)

    # ------------------------------------------------------------- documents --
    def wamex(self, lon: float, lat: float, nearby: bool = False, radius_km: float = 10,
              limit: int = 100, max_rows: int | None = None) -> Iterator[dict]:
        """WAMEX reports covering the point, or (nearby=True) reports within radius_km that do not."""
        first = self.get("/geo/api/wamex/", lon=lon, lat=lat, mode="nearby" if nearby else None,
                         radius_km=radius_km if nearby else None, limit=limit)
        return self._pages(first, "reports", lambda u: self.get(u), max_rows)

    def report_files(self, anumber: str) -> dict:
        """Download links for one WAMEX report's files, plus its abstract."""
        return self.get("/geo/api/wamex/report_files/", anumber=anumber)

    def doc_files(self, key: str, corpus: str = "wamex") -> dict:
        """Every file of one document in a corpus (wamex, ebookshop, …), as download links."""
        return self.get("/geo/api/doc/files/", corpus=corpus, key=key)

    def report_manifest(self, anumbers: Iterable[str], chunk: int = 200) -> dict:
        """Every file of many WAMEX reports, as one manifest: per report its files (name, bytes,
        download_url valid 7 days), plus `not_found`, `invalid`, `failed` and the totals. Asks
        the platform `chunk` reports at a time (200 at most)."""
        anums = list(dict.fromkeys(str(a).strip() for a in anumbers if str(a).strip()))
        out: dict[str, Any] = {"reports": [], "not_found": [], "invalid": [], "failed": [],
                               "count": 0, "files": 0, "bytes": 0}
        for i in range(0, len(anums), chunk):
            m = self.post("/geo/api/wamex/report_files/batch/", {"anumbers": anums[i:i + chunk]})
            for k in ("reports", "not_found", "invalid", "failed"):
                out[k] += m.get(k) or []
            for k in ("count", "files", "bytes"):
                out[k] += m.get(k) or 0
        return out

    def download_reports(self, anumbers: Iterable[str], dest: str | os.PathLike, *, workers: int = 4,
                         chunk: int = 200, progress: Any = None) -> dict:
        """Download every file of many WAMEX reports into dest/A<n>/<name>.

        Safe to re-run: a file already on disk at its full size is skipped, and a download goes
        to a .part file first, so an interrupted run leaves nothing half-written under the real
        name. Links are fetched `chunk` reports at a time, just before that chunk downloads, so a
        long run never meets an expired link. `progress(anumber, name, status)` is called per
        file, status one of "downloaded", "skipped", "failed". Returns what happened:
        {downloaded, skipped, failed: [{anumber, name, error}], not_found, invalid, bytes}."""
        from concurrent.futures import ThreadPoolExecutor

        root = Path(dest)
        anums = list(dict.fromkeys(str(a).strip() for a in anumbers if str(a).strip()))
        summary: dict[str, Any] = {"downloaded": 0, "skipped": 0, "failed": [], "not_found": [],
                                   "invalid": [], "bytes": 0}

        def fetch(job: tuple[str, dict]) -> tuple[str, str, str, int, str | None]:
            anum, f = job
            out = root / anum / f["name"]
            if out.exists() and out.stat().st_size == f["bytes"]:
                return anum, f["name"], "skipped", 0, None
            out.parent.mkdir(parents=True, exist_ok=True)
            part = out.with_name(out.name + ".part")
            try:
                self.download(f["download_url"], part)
                if part.stat().st_size != f["bytes"]:
                    raise GeoDataError(502, f"short download: {part.stat().st_size} of {f['bytes']} bytes")
                part.replace(out)
                return anum, f["name"], "downloaded", f["bytes"], None
            except (GeoDataError, httpx.HTTPError, OSError) as e:
                part.unlink(missing_ok=True)
                return anum, f["name"], "failed", 0, str(e)

        for i in range(0, len(anums), chunk):
            m = self.report_manifest(anums[i:i + chunk], chunk=chunk)
            summary["not_found"] += m["not_found"]
            summary["invalid"] += m["invalid"]
            summary["failed"] += [{"anumber": x["anumber"], "name": None, "error": x["error"]} for x in m["failed"]]
            jobs = [(r["anumber"], f) for r in m["reports"] for f in r["files"]]
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                for anum, name, status, nbytes, err in pool.map(fetch, jobs):
                    if status == "failed":
                        summary["failed"].append({"anumber": anum, "name": name, "error": err})
                    else:
                        summary[status] += 1
                        summary["bytes"] += nbytes
                    if progress is not None:
                        progress(anum, name, status)
        return summary

    # ------------------------------------------------------------ core scans --
    def core_holes(self, state: str | None = None, max_rows: int | None = None) -> Iterator[dict]:
        """HyLogger-scanned drillholes you may see (all public ones, plus your own uploads),
        optionally of one State ("WA", "NSW", …)."""
        n = 0
        for h in self.get("/core-scan/api/holes/").get("holes", []):
            if state and (h.get("state") or "").upper() != state.upper():
                continue
            yield h
            n += 1
            if max_rows is not None and n >= max_rows:
                return

    def core_hole(self, key: str) -> dict:
        """One scanned hole: collar, depth, the metre-by-metre mineral log and model results."""
        return self.get(f"/core-scan/api/holes/{key}/")

    def core_metre(self, key: str, metre: int) -> dict:
        """What the scan reads at one metre of a hole."""
        return self.get(f"/core-scan/api/holes/{key}/metres/{int(metre)}/")

    # -------------------------------------------------------------------- SQL --
    def tables(self) -> dict:
        """Every table the SQL endpoint may read, per schema, with row estimates."""
        return self.get("/geo/api/sql/tables/")

    def describe(self, table: str) -> dict:
        """The columns of one table (schema.table)."""
        return self.get("/geo/api/sql/describe/", table=table)

    def sql(self, query: str, page_size: int = 1000, max_rows: int | None = None) -> Iterator[dict]:
        """Rows of a read-only SELECT as dicts, page after page. Give the query an ORDER BY when it
        returns more than one page, so the pages do not overlap."""
        body = {"sql": query, "limit": page_size}

        def run(extra: dict) -> dict:
            return self.post("/geo/api/sql/query/", {**body, **extra})

        first = run({})
        cols = first.get("columns") or []

        def as_dicts(page: dict) -> dict:
            return {**page, "rows": [dict(zip(cols, r)) for r in page.get("rows") or []]}

        return self._pages(as_dicts(first), "rows", lambda nxt: as_dicts(run(nxt)), max_rows)

    # -------------------------------------------------------- whole datasets --
    def catalog_download(self, slug: str, format: str = "csv", path: str | os.PathLike | None = None,
                         wait: float = 900.0, poll: float = 5.0) -> dict | Path:
        """A whole dataset as one file (CSV, or GeoPackage where offered). The platform builds it
        once per update; the first request may take minutes, so this polls until it is ready.
        Returns the file record {url, size, rows, …}, or the saved Path when `path` is given."""
        rec = self.post(f"/geo/api/catalog/{slug}/download/", {"format": format})
        deadline = time.monotonic() + wait
        while rec.get("status") in ("running", "pending", "none") and time.monotonic() < deadline:
            time.sleep(poll)
            rec = self.get(f"/geo/api/catalog/{slug}/download/", format=format)
        if rec.get("status") != "ready":
            raise GeoDataError(504 if rec.get("status") == "running" else 500,
                               rec.get("error") or f"file not ready (status {rec.get('status')})", rec)
        return self.download(rec["url"], path) if path is not None else rec

    def download(self, url: str, path: str | os.PathLike) -> Path:
        """Stream a download link (from `export` or `catalog_download`) to a file."""
        out = Path(path)
        with httpx.stream("GET", url, timeout=None, follow_redirects=True) as r:
            if r.status_code >= 400:
                raise GeoDataError(r.status_code, "download failed")
            with out.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return out

    # -------------------------------------------------------------- your data --
    def my_datasets(self) -> list[dict]:
        """Datasets you uploaded."""
        d = self.get("/user-data/api/datasets/", scope="mine")
        return d.get("results", d) if isinstance(d, dict) else d

    def upload_dataset(self, path: str | os.PathLike, name: str, visibility: str = "private",
                       description: str | None = None) -> dict:
        """Upload a file (CSV, GeoJSON, zipped Shapefile, GeoTIFF, …) as a new dataset of yours. The
        platform reads it and builds the layer; visibility "public" shares it by link. Needs a token
        with the Read and write scope. Returns the dataset (its `id` gives the share link
        https://geo.nlp-tlp.org/datasets/<id>)."""
        p = Path(path)
        body: dict[str, Any] = {"name": name, "visibility": "private"}
        if description:
            body["description"] = description
        ds = self.post("/user-data/api/datasets/", body)
        version = (ds.get("latest_version") or {}).get("id")
        if not version:
            raise GeoDataError(500, "the platform did not open an upload for this dataset", ds)
        with p.open("rb") as f:
            self._send("PUT", f"/user-data/api/versions/{version}/upload/",
                       content=f.read(), headers={"X-Filename": p.name, "Content-Type": "application/octet-stream"})
        if visibility != "private":
            ds = self._request("PATCH", f"/user-data/api/datasets/{ds['id']}/", json={"visibility": visibility})
        return ds

    # --------------------------------------------------------------- helpers --
    @staticmethod
    def to_dataframe(rows: Iterable[dict]):
        """Rows (or GeoJSON features) as a pandas DataFrame; needs pandas installed."""
        try:
            import pandas as pd
        except ImportError as e:   # pragma: no cover - only without pandas
            raise ImportError("to_dataframe needs pandas: pip install pandas") from e
        rows = list(rows)
        if rows and isinstance(rows[0], dict) and rows[0].get("type") == "Feature":
            flat = []
            for f in rows:
                g = f.get("geometry") or {}
                coords = g.get("coordinates") if g.get("type") == "Point" else None
                flat.append({**(f.get("properties") or {}),
                             **({"lon": coords[0], "lat": coords[1]} if coords else {"geometry": json.dumps(g)})})
            rows = flat
        return pd.DataFrame(rows)

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
