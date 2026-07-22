from web.app import create_app


def test_openapi_exposes_only_versioned_api_routes():
    paths = create_app().openapi()["paths"]
    assert paths
    assert all(path.startswith("/api/v1/") for path in paths)
    assert "/api/subscriptions" not in paths


def test_openapi_operation_ids_are_explicit_and_unique():
    operations = [operation for path in create_app().openapi()["paths"].values() for method, operation in path.items() if method in {"get", "post", "patch", "delete"}]
    operation_ids = [operation["operationId"] for operation in operations]
    assert len(operation_ids) == len(set(operation_ids))
    assert all(operation.get("tags") for operation in operations)
    assert all(operation.get("description") for operation in operations)
    assert "get_episode_transcript" in operation_ids
    assert "create_transcript_job" in operation_ids
