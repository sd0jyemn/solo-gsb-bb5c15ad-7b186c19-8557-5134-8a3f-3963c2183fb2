"""POST /transfers/preview 预演接口测试。"""
from helpers import container, sample, volume_of


def _preview(client, transfers):
    return client.post("/transfers/preview", json={"transfers": transfers})


def test_preview_returns_steps_and_final_states_without_writing(client):
    sample(client, "S1", "100")
    sample(client, "S2", "100")
    container(client, "V1")
    container(client, "V2")

    r = _preview(
        client,
        [
            {"source": "S1", "destination": "V1", "volume": "40"},
            {"source": "S2", "destination": "V1", "volume": "60"},
            {"source": "V1", "destination": "V2", "volume": "25"},
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # 每一步从各祖先来源实际扣取的精确份额
    assert [s["index"] for s in body["steps"]] == [1, 2, 3]
    step1, step2, step3 = body["steps"]
    assert step1["source"] == "S1" and step1["destination"] == "V1"
    assert step1["volume"] == "40.000000000"
    assert step1["taken"] == [{"source_id": "S1", "amount": "40.000000000"}]
    assert step2["taken"] == [{"source_id": "S2", "amount": "60.000000000"}]
    # 链式步骤使用本批前序模拟结果：V1 当时为 40/60 混合
    assert step3["taken"] == [
        {"source_id": "S1", "amount": "10.000000000"},
        {"source_id": "S2", "amount": "15.000000000"},
    ]

    # 全部受影响容器的最终体积与来源构成（按 ID 排序）
    assert [c["container_id"] for c in body["containers"]] == ["S1", "S2", "V1", "V2"]
    final = {c["container_id"]: c for c in body["containers"]}
    assert final["S1"]["volume"] == "60.000000000"
    assert final["S2"]["volume"] == "40.000000000"
    assert final["V1"]["volume"] == "75.000000000"
    assert {(s["source_id"], s["amount"]) for s in final["V1"]["sources"]} == {
        ("S1", "30.000000000"),
        ("S2", "45.000000000"),
    }
    assert final["V2"]["volume"] == "25.000000000"
    assert {(s["source_id"], s["amount"]) for s in final["V2"]["sources"]} == {
        ("S1", "10.000000000"),
        ("S2", "15.000000000"),
    }

    # 预演成功也不改变数据库
    assert volume_of(client, "S1") == "100.000000000"
    assert volume_of(client, "S2") == "100.000000000"
    assert volume_of(client, "V1") == "0"
    assert volume_of(client, "V2") == "0"


def test_preview_simulates_on_current_db_state(client):
    sample(client, "S1", "100")
    container(client, "V1")
    client.post(
        "/transfers/batch",
        json={"transfers": [{"source": "S1", "destination": "V1", "volume": "40"}]},
    )

    r = _preview(client, [{"source": "V1", "destination": "S1", "volume": "10"}])
    assert r.status_code == 200, r.text
    final = {c["container_id"]: c for c in r.json()["containers"]}
    # 模拟建立在已提交的当前状态（S1=60, V1=40）之上
    assert final["S1"]["volume"] == "70.000000000"
    assert final["V1"]["volume"] == "30.000000000"

    # 数据库仍是预演前状态
    assert volume_of(client, "S1") == "60.000000000"
    assert volume_of(client, "V1") == "40.000000000"


def test_preview_matches_real_commit(client):
    sample(client, "A", "3.333333333")
    sample(client, "B", "6.666666666")
    container(client, "M")
    container(client, "N")
    transfers = [
        {"source": "A", "destination": "M", "volume": "3.333333333"},
        {"source": "B", "destination": "M", "volume": "6.666666666"},
        {"source": "M", "destination": "N", "volume": "5.555555555"},
    ]

    preview = _preview(client, transfers).json()
    r = client.post("/transfers/batch", json={"transfers": transfers})
    assert r.status_code == 200, r.text

    # 预演的最终状态与真实提交后的查询结果逐一吻合
    for c in preview["containers"]:
        actual = client.get(f"/containers/{c['container_id']}").json()
        assert actual["volume"] == c["volume"]
        assert actual["sources"] == c["sources"]


def test_preview_error_response_identical_to_batch(client):
    sample(client, "S1", "10")
    container(client, "V1")
    container(client, "V2")
    transfers = [
        {"source": "S1", "destination": "V1", "volume": "5"},
        {"source": "S1", "destination": "V2", "volume": "100"},
    ]

    r = _preview(client, transfers)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "insufficient_volume"
    assert "第 2 条转移" in err["message"]

    # 与真实提交的错误（状态码、错误码、条目序号）完全一致
    r2 = client.post("/transfers/batch", json={"transfers": transfers})
    assert r2.status_code == r.status_code
    assert r2.json() == r.json()

    # 预演失败同样不写库
    assert volume_of(client, "S1") == "10.000000000"
    assert volume_of(client, "V1") == "0"
    assert volume_of(client, "V2") == "0"


def test_preview_unknown_container_404(client):
    sample(client, "S1", "10")
    r = _preview(client, [{"source": "S1", "destination": "GHOST", "volume": "1"}])
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "unknown_container"
    assert volume_of(client, "S1") == "10.000000000"


def test_preview_self_transfer_rejected(client):
    sample(client, "S1", "10")
    r = _preview(client, [{"source": "S1", "destination": "S1", "volume": "1"}])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "self_transfer"
    assert volume_of(client, "S1") == "10.000000000"


def test_preview_invalid_volume_rejected(client):
    sample(client, "S1", "10")
    container(client, "V1")

    r = _preview(client, [{"source": "S1", "destination": "V1", "volume": "0"}])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_volume"

    r = _preview(client, [{"source": "S1", "destination": "V1", "volume": "0.0000000001"}])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_volume"

    assert volume_of(client, "S1") == "10.000000000"
    assert volume_of(client, "V1") == "0"


def test_preview_empty_transfer_list_rejected(client):
    r = _preview(client, [])
    assert r.status_code == 422
