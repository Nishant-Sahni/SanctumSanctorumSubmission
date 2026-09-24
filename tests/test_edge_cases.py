import pytest

def test_list_members_default_response(client, make_member):
    members = [make_member() for _ in range(5)]
    
    response = client.get("/members")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert data["limit"] == 20
    assert data["offset"] == 0
    assert len(data["items"]) == 5
    assert [m["id"] for m in data["items"]] == [m["id"] for m in members]


def test_list_members_limit_and_offset_slice_correctly(client, make_member):
    members = [make_member() for _ in range(5)]
    
    response = client.get("/members?limit=2&offset=1")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert data["limit"] == 2
    assert data["offset"] == 1
    assert len(data["items"]) == 2
    assert [m["id"] for m in data["items"]] == [members[1]["id"], members[2]["id"]]


@pytest.mark.parametrize(
    "params",
    [
        "?limit=0",
        "?limit=101",
        "?offset=-1",
    ]
)
def test_invalid_pagination_params_returns_422(client, params):
    assert client.get(f"/members{params}").status_code == 422
