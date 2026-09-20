def test_cors_allows_configured_origin(client):
    resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_omits_header_for_unknown_origin(client):
    resp = client.get("/health", headers={"Origin": "http://evil.example"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers
