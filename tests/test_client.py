import httpx
import pytest
import respx

from ntlp_geodata import GeoData, GeoDataError

BASE = "https://platform.test"


@respx.mock
def test_token_is_sent_and_summary_returns_a_dict():
    route = respx.get(f"{BASE}/geo/api/platform/summary/").mock(return_value=httpx.Response(200, json={"groups": {}}))
    assert GeoData(token="gp_abc", base_url=BASE).summary() == {"groups": {}}
    assert route.calls.last.request.headers["Authorization"] == "Bearer gp_abc"


@respx.mock
def test_wamex_follows_next_until_null():
    def handler(request):
        if request.url.params.get("offset") == "2":
            return httpx.Response(200, json={"reports": [{"anumber": "A3"}], "page": {"next": None}})
        return httpx.Response(200, json={"reports": [{"anumber": "A1"}, {"anumber": "A2"}],
                                         "page": {"next": f"{BASE}/geo/api/wamex/?lon=1&lat=2&limit=2&offset=2"}})

    respx.get(f"{BASE}/geo/api/wamex/").mock(side_effect=handler)
    got = [r["anumber"] for r in GeoData(base_url=BASE).wamex(1, 2, limit=2)]
    assert got == ["A1", "A2", "A3"]


@respx.mock
def test_max_rows_stops_early():
    respx.get(f"{BASE}/geo/api/sites/").mock(return_value=httpx.Response(200, json={
        "features": [{"id": i} for i in range(5)], "page": {"next": f"{BASE}/geo/api/sites/?offset=5"}}))
    assert len(list(GeoData(base_url=BASE).sites(max_rows=3))) == 3


@respx.mock
def test_sql_pages_by_resending_the_body_and_returns_dicts():
    calls = []

    def handler(request):
        import json
        body = json.loads(request.content)
        calls.append(body)
        if body.get("offset") == 2:
            return httpx.Response(200, json={"columns": ["g"], "rows": [[3]], "page": {"next": None}})
        return httpx.Response(200, json={"columns": ["g"], "rows": [[1], [2]], "page": {"next": {"limit": 2, "offset": 2}}})

    respx.post(f"{BASE}/geo/api/sql/query/").mock(side_effect=handler)
    rows = list(GeoData(base_url=BASE).sql("select g from t order by g", page_size=2))
    assert rows == [{"g": 1}, {"g": 2}, {"g": 3}]
    assert calls[1] == {"sql": "select g from t order by g", "limit": 2, "offset": 2}


@respx.mock
def test_429_is_retried_after_retry_after(monkeypatch):
    slept = []
    monkeypatch.setattr("ntlp_geodata.client.time.sleep", lambda s: slept.append(s))
    respx.get(f"{BASE}/geo/api/platform/summary/").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "2"}, json={"error": "rate_limited"}),
        httpx.Response(200, json={"ok": True})])
    assert GeoData(base_url=BASE).summary() == {"ok": True}
    assert slept == [2.0]


@respx.mock
def test_errors_carry_status_and_message():
    respx.get(f"{BASE}/geo/api/sql/tables/").mock(return_value=httpx.Response(401, json={"error": "invalid_token", "message": "expired"}))
    with pytest.raises(GeoDataError) as e:
        GeoData(token="gp_old", base_url=BASE).tables()
    assert (e.value.status, e.value.message) == (401, "expired")


# ---- methods added in 0.1.0 of ntlp-geodata ---------------------------------------------------

@respx.mock
def test_token_from_environment(monkeypatch):
    monkeypatch.setenv("GEODATA_TOKEN", "gp_env")
    route = respx.get(f"{BASE}/authenticate/api/me/").mock(return_value=httpx.Response(200, json={"email": "a@b.c"}))
    assert GeoData(base_url=BASE).me()["email"] == "a@b.c"
    assert route.calls.last.request.headers["Authorization"] == "Bearer gp_env"


@respx.mock
def test_search_returns_results_list():
    route = respx.get(f"{BASE}/geo/api/search/").mock(return_value=httpx.Response(200, json={
        "results": [{"kind": "report", "label": "A38751", "lon": 121.5, "lat": -30.5}]}))
    got = GeoData(base_url=BASE).search("A38751", limit=3)
    assert got[0]["label"] == "A38751"
    assert route.calls.last.request.url.params["q"] == "A38751"
    assert route.calls.last.request.url.params["limit"] == "3"


@respx.mock
def test_region_summary_sends_the_box_and_metal():
    route = respx.get(f"{BASE}/geo/api/region_summary/").mock(return_value=httpx.Response(200, json={"bbox": [1, 2, 3, 4]}))
    GeoData(base_url=BASE).region_summary(121.3, -30.9, 121.7, -30.5, metal="Au")
    p = route.calls.last.request.url.params
    assert (p["west"], p["south"], p["east"], p["north"], p["metal"]) == ("121.3", "-30.9", "121.7", "-30.5", "Au")


@respx.mock
def test_drillhole_traces_sends_poly_as_lon_lat_pairs():
    route = respx.get(f"{BASE}/geo/api/drillhole_traces/").mock(return_value=httpx.Response(200, json={"holes": []}))
    GeoData(base_url=BASE).drillhole_traces(1, 2, 3, 4, poly=[(1, 2), (3, 2), (3, 4)])
    assert route.calls.last.request.url.params["poly"] == "1.0 2.0,3.0 2.0,3.0 4.0"


@respx.mock
def test_geochem_export_writes_the_zip(tmp_path):
    respx.get(f"{BASE}/geo/api/geochem/export/").mock(return_value=httpx.Response(200, content=b"PK\x03\x04zip"))
    out = GeoData(base_url=BASE).geochem_export("company_dh_collars", [(1, 2), (3, 2), (3, 4)], tmp_path / "x.zip")
    assert out.read_bytes().startswith(b"PK")


@respx.mock
def test_export_posts_bbox_as_a_list():
    route = respx.post(f"{BASE}/geo/api/export/").mock(return_value=httpx.Response(200, json={"url": "https://s3/x", "count": 3}))
    got = GeoData(base_url=BASE).export("drillholes", bbox=(121.3, -30.9, 121.7, -30.5), format="csv")
    import json
    body = json.loads(route.calls.last.request.content)
    assert body == {"layer": "drillholes", "format": "csv", "bbox": [121.3, -30.9, 121.7, -30.5]}
    assert got["url"] == "https://s3/x"


@respx.mock
def test_core_holes_filters_by_state():
    respx.get(f"{BASE}/core-scan/api/holes/").mock(return_value=httpx.Response(200, json={
        "holes": [{"key": "A", "state": "WA"}, {"key": "B", "state": "NSW"}, {"key": "C", "state": "wa"}], "n": 3}))
    assert [h["key"] for h in GeoData(base_url=BASE).core_holes(state="WA")] == ["A", "C"]


@respx.mock
def test_core_hole_and_metre_paths():
    respx.get(f"{BASE}/core-scan/api/holes/05GJD001/").mock(return_value=httpx.Response(200, json={"key": "05GJD001"}))
    m = respx.get(f"{BASE}/core-scan/api/holes/05GJD001/metres/120/").mock(return_value=httpx.Response(200, json={"m": 120}))
    gd = GeoData(base_url=BASE)
    assert gd.core_hole("05GJD001")["key"] == "05GJD001"
    assert gd.core_metre("05GJD001", 120)["m"] == 120 and m.called


@respx.mock
def test_catalog_download_polls_until_ready_then_saves(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    respx.post(f"{BASE}/geo/api/catalog/hylogger-core-scans/download/").mock(
        return_value=httpx.Response(202, json={"status": "running", "format": "csv"}))
    states = iter([{"status": "running", "format": "csv"},
                   {"status": "ready", "format": "csv", "url": "https://s3.test/f.csv", "size": 5, "rows": 1}])
    respx.get(f"{BASE}/geo/api/catalog/hylogger-core-scans/download/").mock(side_effect=lambda r: httpx.Response(200, json=next(states)))
    respx.get("https://s3.test/f.csv").mock(return_value=httpx.Response(200, content=b"a,b\n"))
    out = GeoData(base_url=BASE).catalog_download("hylogger-core-scans", path=tmp_path / "f.csv")
    assert out.read_bytes() == b"a,b\n"


@respx.mock
def test_catalog_download_reports_a_failed_build(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    respx.post(f"{BASE}/geo/api/catalog/x/download/").mock(
        return_value=httpx.Response(200, json={"status": "failed", "error": "could not build"}))
    with pytest.raises(GeoDataError, match="could not build"):
        GeoData(base_url=BASE).catalog_download("x")


@respx.mock
def test_upload_dataset_creates_uploads_and_publishes(tmp_path):
    f = tmp_path / "soils.csv"
    f.write_text("lon,lat\n121,-30\n")
    respx.post(f"{BASE}/user-data/api/datasets/").mock(return_value=httpx.Response(201, json={
        "id": "ds1", "latest_version": {"id": "v1"}, "visibility": "private"}))
    put = respx.put(f"{BASE}/user-data/api/versions/v1/upload/").mock(return_value=httpx.Response(200, json={"ok": True}))
    patch = respx.patch(f"{BASE}/user-data/api/datasets/ds1/").mock(return_value=httpx.Response(200, json={
        "id": "ds1", "visibility": "public"}))
    ds = GeoData(token="gp_rw", base_url=BASE).upload_dataset(f, "Soils", visibility="public")
    assert put.calls.last.request.headers["X-Filename"] == "soils.csv"
    assert put.calls.last.request.content == b"lon,lat\n121,-30\n"
    assert patch.called and ds["visibility"] == "public"


@respx.mock
def test_catalog_item_and_doc_files():
    respx.get(f"{BASE}/geo/api/catalog/wamex-reports/").mock(return_value=httpx.Response(200, json={"slug": "wamex-reports"}))
    d = respx.get(f"{BASE}/geo/api/doc/files/").mock(return_value=httpx.Response(200, json={"files": []}))
    gd = GeoData(base_url=BASE)
    assert gd.catalog_item("wamex-reports")["slug"] == "wamex-reports"
    gd.doc_files("A38751")
    assert d.calls.last.request.url.params["corpus"] == "wamex"
    assert d.calls.last.request.url.params["key"] == "A38751"


def test_to_dataframe_flattens_point_features():
    pd = pytest.importorskip("pandas")
    df = GeoData.to_dataframe([{"type": "Feature", "geometry": {"type": "Point", "coordinates": [121.0, -30.0]},
                                "properties": {"name": "H1"}}])
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["name", "lon", "lat"]
