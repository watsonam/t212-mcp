import json

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError


@pytest.fixture
def preview(call):
    async def preview_order(server, tool, **args):
        return await call(server, tool, args)
    return preview_order


async def test_market_buy_of_held_instrument_previews_without_placing(account, make_server, preview):
    route = account.post("orders/market").respond(json={"id": 1})
    result = await preview(make_server(), "preview_market_order", ticker="VUSAl_EQ", quantity=2)
    assert (result["side"], result["name"], result["estimatedValueGbp"]) == ("BUY", "Vanguard S&P 500", 180.0)
    assert route.call_count == 0


async def test_confirm_places_the_order_once_and_logs_it(account, make_server, log, preview, call):
    route = account.post("orders/market").respond(json={"id": 1, "status": "NEW"})
    server = make_server()
    token = (await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2))["token"]
    assert (await call(server, "confirm_order", {"token": token}))["id"] == 1
    assert json.loads(route.calls.last.request.content) == {"ticker": "VUSAl_EQ", "quantity": 2, "extendedHours": False}
    assert [entry["event"] for entry in log()] == ["preview", "sent", "placed"]
    with pytest.raises(ToolError, match="token"):
        await call(server, "confirm_order", {"token": token})
    assert route.call_count == 1


async def test_expired_token_is_refused(account, make_server, preview, call):
    route = account.post("orders/market").respond(json={"id": 1})
    server = make_server(token_seconds=0)
    token = (await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=1))["token"]
    with pytest.raises(ToolError, match="expired"):
        await call(server, "confirm_order", {"token": token})
    assert route.call_count == 0


async def test_market_buy_of_unheld_instrument_is_refused(account, make_server, preview):
    with pytest.raises(ToolError, match="limit order"):
        await preview(make_server(), "preview_market_order", ticker="AAPL_US_EQ", quantity=1)


async def test_limit_buy_converts_with_rate_from_held_position(account, make_server, preview):
    result = await preview(make_server(), "preview_limit_order", ticker="AAPL_US_EQ", quantity=3, limit_price=200)
    assert result["estimatedValueGbp"] == 450.0


async def test_limit_buy_in_pence(account, make_server, preview):
    result = await preview(make_server(), "preview_limit_order", ticker="VUSAl_EQ", quantity=5, limit_price=9100)
    assert result["estimatedValueGbp"] == 455.0


async def test_limit_buy_without_known_rate_is_refused(account, make_server, preview):
    with pytest.raises(ToolError, match="JPY"):
        await preview(make_server(), "preview_limit_order", ticker="7203_JP_EQ", quantity=1, limit_price=3000)


async def test_per_order_cap(account, make_server, preview):
    with pytest.raises(ToolError, match="per-order cap"):
        await preview(make_server(max_order_gbp=500), "preview_market_order", ticker="VUSAl_EQ", quantity=6)


async def test_daily_cap_counts_placed_orders(account, make_server, preview, call):
    account.post("orders/market").respond(json={"id": 1})
    server = make_server(max_daily_gbp=300)
    token = (await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2))["token"]
    await call(server, "confirm_order", {"token": token})
    with pytest.raises(ToolError, match="daily cap"):
        await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2)


async def test_rejected_order_does_not_count_toward_daily_cap(account, make_server, preview, call):
    account.post("orders/market").respond(400, text="market closed")
    server = make_server(max_daily_gbp=300)
    token = (await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2))["token"]
    with pytest.raises(ToolError, match="market closed"):
        await call(server, "confirm_order", {"token": token})
    await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2)


@pytest.mark.parametrize("response", [httpx.ReadTimeout("slow"), httpx.Response(503), httpx.Response(408)])
async def test_no_answer_is_never_retried(account, make_server, log, response, preview, call):
    route = account.post("orders/market").mock(side_effect=[response])
    server = make_server(max_daily_gbp=300)
    token = (await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2))["token"]
    with pytest.raises(ToolError, match="Do not resend"):
        await call(server, "confirm_order", {"token": token})
    assert route.call_count == 1
    assert log()[-1]["event"] == "unknown"
    with pytest.raises(ToolError, match="daily cap"):
        await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2)


async def test_sell_more_than_available_is_refused(account, make_server, preview):
    with pytest.raises(ToolError, match="available"):
        await preview(make_server(), "preview_market_order", ticker="VUSAl_EQ", quantity=-11)


async def test_sell_values_at_current_price(account, make_server, preview):
    result = await preview(make_server(), "preview_stop_order", ticker="MSFT_US_EQ", quantity=-1, stop_price=350)
    assert (result["side"], result["estimatedValueGbp"]) == ("SELL", 300.0)


async def test_stop_buy_is_refused(account, make_server, preview):
    with pytest.raises(ToolError, match="stop-limit"):
        await preview(make_server(), "preview_stop_order", ticker="VUSAl_EQ", quantity=1, stop_price=9500)


async def test_stop_limit_body(account, make_server, preview, call):
    route = account.post("orders/stop_limit").respond(json={"id": 2})
    server = make_server()
    token = (await preview(server, "preview_stop_limit_order", ticker="AAPL_US_EQ", quantity=1, stop_price=190, limit_price=195, time_validity="GOOD_TILL_CANCEL"))["token"]
    await call(server, "confirm_order", {"token": token})
    assert json.loads(route.calls.last.request.content) == {"ticker": "AAPL_US_EQ", "quantity": 1, "stopPrice": 190, "limitPrice": 195, "timeValidity": "GOOD_TILL_CANCEL"}


async def test_trading_disabled_refuses_order_tools(account, make_server, preview, call):
    server = make_server(enabled=False)
    with pytest.raises(ToolError, match="T212_LIVE_TRADING"):
        await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=1)
    with pytest.raises(ToolError, match="T212_LIVE_TRADING"):
        await call(server, "cancel_order", {"order_id": 42})


async def test_cancel_and_get_order(api, make_server, log, call):
    cancel = api.delete("orders/42").respond(200)
    api.get("orders/42").respond(json={"id": 42, "status": "CANCELLING"})
    server = make_server()
    await call(server, "cancel_order", {"order_id": 42})
    assert cancel.call_count == 1
    assert (await call(server, "get_order", {"order_id": 42}))["status"] == "CANCELLING"
    assert [e["event"] for e in log()] == ["cancel", "cancelled"]


async def test_missing_execute_scope(account, make_server, preview, call):
    account.post("orders/market").respond(403)
    server = make_server()
    token = (await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=1))["token"]
    with pytest.raises(ToolError, match="orders:execute"):
        await call(server, "confirm_order", {"token": token})


async def test_user_is_asked_before_an_order_is_placed(account, make_server, preview, call):
    account.post("orders/market").respond(json={"id": 1})
    server = make_server()
    token = (await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2))["token"]
    questions = []
    await call(server, "confirm_order", {"token": token}, questions=questions)
    assert questions == ["BUY 2 x Vanguard S&P 500 (VUSAl_EQ), market order, about £180.00. Place this order?"]


async def test_declined_order_is_not_sent(account, make_server, log, preview, call):
    route = account.post("orders/market").respond(json={"id": 1})
    server = make_server()
    token = (await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2))["token"]
    with pytest.raises(ToolError, match="Not approved"):
        await call(server, "confirm_order", {"token": token}, approve=False)
    assert route.call_count == 0
    assert log()[-1]["event"] == "declined"
    with pytest.raises(ToolError, match="token"):
        await call(server, "confirm_order", {"token": token})


async def test_client_without_elicitation_cannot_place_orders(account, make_server, preview, call):
    route = account.post("orders/market").respond(json={"id": 1})
    server = make_server()
    token = (await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2))["token"]
    with pytest.raises(ToolError, match="nothing was sent"):
        await call(server, "confirm_order", {"token": token}, elicitation=False)
    assert route.call_count == 0


async def test_declined_cancel_is_not_sent(api, make_server, call):
    cancel = api.delete("orders/42").respond(200)
    with pytest.raises(ToolError, match="not cancelled"):
        await call(make_server(), "cancel_order", {"order_id": 42}, approve=False)
    assert cancel.call_count == 0


async def test_corrupt_log_line_does_not_block_orders(account, make_server, preview, call, tmp_path):
    account.post("orders/market").respond(json={"id": 1})
    (tmp_path / "orders.jsonl").write_text('{"time": "2026-10-03T09:00:00+01:00", "event": "sen\n', encoding="utf-8")
    server = make_server()
    token = (await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2))["token"]
    assert (await call(server, "confirm_order", {"token": token}))["id"] == 1


async def test_entry_after_a_cut_off_line_is_kept(account, make_server, preview, tmp_path, log):
    (tmp_path / "orders.jsonl").write_bytes('{"time": "2026-10-03T09:00:00+01:00", "event": "se'.encode())
    await preview(make_server(), "preview_market_order", ticker="VUSAl_EQ", quantity=2)
    lines = (tmp_path / "orders.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["event"] == "preview"


async def test_sent_line_is_forced_to_disk(account, make_server, preview, call, monkeypatch):
    account.post("orders/market").respond(json={"id": 1})
    synced = []
    monkeypatch.setattr("t212_mcp.orders.os.fsync", synced.append)
    server = make_server()
    token = (await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2))["token"]
    await call(server, "confirm_order", {"token": token})
    assert len(synced) == 1


@pytest.mark.parametrize(("tool", "args"), [
    ("preview_market_order", {"quantity": "NaN"}),
    ("preview_limit_order", {"quantity": 1, "limit_price": -100}),
    ("preview_limit_order", {"quantity": 1, "limit_price": 0}),
    ("preview_limit_order", {"quantity": 1, "limit_price": "Infinity"}),
    ("preview_stop_order", {"quantity": -1, "stop_price": -5}),
])
async def test_bad_numbers_are_refused(account, make_server, preview, tool, args):
    with pytest.raises(ToolError, match="must be"):
        await preview(make_server(), tool, ticker="VUSAl_EQ", **args)


async def test_unreadable_rate_limit_header_after_order_is_not_an_error(account, make_server, preview, call):
    account.post("orders/market").respond(json={"id": 1}, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "soon"})
    server = make_server()
    token = (await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2))["token"]
    assert (await call(server, "confirm_order", {"token": token}))["id"] == 1


@pytest.mark.parametrize(("body", "headers"), [(b"<html>", {}), (b"not gzip", {"content-encoding": "gzip"}), (b"\xff\xfe\xfa", {"content-type": "application/json"})])
async def test_unreadable_success_response_is_unknown(account, make_server, preview, call, log, body, headers):
    route = account.post("orders/market").mock(side_effect=lambda request: httpx.Response(200, headers=headers, stream=httpx.ByteStream(body)))
    server = make_server()
    token = (await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2))["token"]
    with pytest.raises(ToolError, match="Do not resend"):
        await call(server, "confirm_order", {"token": token})
    assert route.call_count == 1
    assert log()[-1]["event"] == "unknown"


async def test_rejection_logs_the_response_body(account, make_server, preview, call, log):
    account.post("orders/market").respond(403, text="Scope( orders:execute ) missing")
    server = make_server()
    token = (await preview(server, "preview_market_order", ticker="VUSAl_EQ", quantity=2))["token"]
    with pytest.raises(ToolError):
        await call(server, "confirm_order", {"token": token})
    assert log()[-1]["response"] == "Scope( orders:execute ) missing"


async def test_failed_cancel_is_logged(api, make_server, call, log):
    api.delete("orders/42").respond(404, text="Order not found")
    with pytest.raises(ToolError, match="404"):
        await call(make_server(), "cancel_order", {"order_id": 42})
    assert log()[-1] == {**log()[-1], "event": "cancel-failed", "response": "Order not found"}
