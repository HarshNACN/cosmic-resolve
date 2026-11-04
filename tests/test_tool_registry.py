from cosmic_resolve.tool_registry import READ_TOOLS, invoke_read_tool, read_tool_specs

READ_TOOL_NAMES = {
    "get_case",
    "get_order",
    "get_customer",
    "get_shipment",
    "check_inventory",
    "get_policy",
    "get_product_listing",
}
WRITE_TOOL_NAMES = {
    "issue_refund",
    "create_replacement",
    "issue_store_credit",
    "send_customer_message",
    "escalate",
    "tag_root_cause",
}


def test_registry_exposes_exactly_the_seven_read_tools():
    assert set(READ_TOOLS) == READ_TOOL_NAMES


def test_write_tools_are_not_model_callable():
    assert not (set(READ_TOOLS) & WRITE_TOOL_NAMES)
    assert invoke_read_tool("issue_refund", {"order_id": "O-1001", "amount": "10", "reason": "x"})["status"] == "error"


def test_tool_specs_match_registry_and_are_bedrock_shaped():
    specs = read_tool_specs()
    assert [spec["toolSpec"]["name"] for spec in specs] == list(READ_TOOLS)
    for spec in specs:
        schema = spec["toolSpec"]["inputSchema"]["json"]
        assert schema["type"] == "object"
        assert schema["required"] == list(schema["properties"])
        assert schema["additionalProperties"] is False


def test_get_case_returns_json_result():
    result = invoke_read_tool("get_case", {"case_id": "C-1001"})
    assert result["status"] == "success"
    payload = result["content"][0]["json"]
    assert payload["case_id"] == "C-1001"
    assert payload["order_id"] == "O-1001"


def test_list_result_is_serialised_per_item():
    result = invoke_read_tool("get_policy", {"market": "US", "category": "GADGETS", "case_type": "DAMAGED_ON_ARRIVAL"})
    assert result["status"] == "success"
    clauses = result["content"][0]["json"]
    assert isinstance(clauses, list) and clauses
    assert all(isinstance(clause["clause_id"], str) for clause in clauses)


def test_missing_record_is_an_error_result_not_an_exception():
    result = invoke_read_tool("get_case", {"case_id": "C-9999"})
    assert result["status"] == "error"
    assert "C-9999" in result["content"][0]["json"]["error"]


def test_unknown_tool_is_an_error_result():
    result = invoke_read_tool("delete_everything", {})
    assert result["status"] == "error"
    assert "Unknown tool" in result["content"][0]["json"]["error"]


def test_bad_arguments_are_error_results():
    assert invoke_read_tool("get_case", {})["status"] == "error"  # missing
    assert invoke_read_tool("get_case", {"case_id": "C-1001", "extra": "x"})["status"] == "error"  # unexpected
    assert invoke_read_tool("get_case", {"case_id": 1001})["status"] == "error"  # wrong type
    assert invoke_read_tool("get_case", "C-1001")["status"] == "error"  # not an object
