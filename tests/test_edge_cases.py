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


def test_late_fee_cap_uses_price_at_return_time(client, clock, make_book, make_member):
    member = make_member()
    book = make_book(price_cents=10000)
    
    response = client.post("/loans", json={"member_id": member["id"], "book_id": book["id"]})
    loan = response.json()
    
    client.patch(f"/books/{book['id']}", json={"price_cents": 50})
    clock.advance(days=17)
    
    response = client.post(f"/loans/{loan['id']}/return")
    assert response.status_code == 200
    assert response.json()["late_fee_cents"] == 50


def test_due_at_boundary(client, clock, make_book, make_member):
    member = make_member()
    book = make_book()
    
    loan = client.post("/loans", json={"member_id": member["id"], "book_id": book["id"]}).json()
    
    clock.advance(days=14)
    assert client.get(f"/loans/{loan['id']}").json()["status"] == "active"
    assert client.get(f"/members/{member['id']}/stats").json()["overdue_loans"] == 0
    assert client.post(f"/loans/{loan['id']}/return").json()["late_fee_cents"] == 0


def test_due_at_boundary_one_second_past(client, clock, make_book, make_member):
    member = make_member()
    book = make_book()
    
    loan = client.post("/loans", json={"member_id": member["id"], "book_id": book["id"]}).json()
    
    clock.advance(days=14, seconds=1)
    assert client.get(f"/loans/{loan['id']}").json()["status"] == "overdue"
    assert client.post(f"/loans/{loan['id']}/return").json()["late_fee_cents"] == 25


def test_shared_stock_between_sales_and_loans(client, make_book, make_member):
    book = make_book(stock=1)
    member = make_member()
    
    assert client.post("/loans", json={"member_id": member["id"], "book_id": book["id"]}).status_code == 201
    assert client.post("/orders", json={"member_id": member["id"], "items": [{"book_id": book["id"], "quantity": 1}]}).status_code == 409


def test_search_treats_percent_and_underscore_literally(client, make_book):
    book1 = make_book(title="100% Pure")
    book2 = make_book(title="A_B")
    make_book(title="Plain")
    
    response = client.get("/books", params={"q": "%"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == book1["id"]

    response2 = client.get("/books", params={"q": "_"})
    assert response2.status_code == 200
    items2 = response2.json()["items"]
    assert len(items2) == 1
    assert items2[0]["id"] == book2["id"]


def test_patch_explicit_null_returns_422(client, make_book):
    book = make_book()
    response = client.patch(f"/books/{book['id']}", json={"title": None})
    assert response.status_code == 422
