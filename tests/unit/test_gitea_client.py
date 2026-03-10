import os
import httpx

from services.langgraph_api.core.gitea_client import build_comment_body, post_pr_comment_sync


def test_build_comment_body():
    findings = [
        {"agent": "backend", "title": "sql issue", "severity": "HIGH"},
        {"agent": "security", "title": "xss", "severity": "CRITICAL"},
    ]

    body = build_comment_body("wf-123", "APPROVE", findings)
    # new format uses markdown header and includes decision and workflow id
    assert "###" in body
    assert "APPROVE" in body
    assert "workflow `wf-123`" in body

def test_post_pr_comment_sync_success(monkeypatch):
    # set env vars
    monkeypatch.setenv("GITEA_URL", "http://gitea.local")
    monkeypatch.setenv("GITEA_TOKEN", "fake-token")

    owner_repo = "owner/repo"
    pr_number = 1
    body = "test comment"

    class FakeResp:
        def __init__(self, status=201, json_data=None):
            self._status = status
            self.status_code = status
            self._json = json_data or {}

        def raise_for_status(self):
            if self._status >= 400:
                raise httpx.HTTPStatusError("error", request=None, response=None)

        def json(self):
            return self._json

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None, headers=None):
            assert url == f"http://gitea.local/api/v1/repos/{owner_repo}/issues/{pr_number}/comments"
            return FakeResp(201, {"id": 123, "body": body})

    monkeypatch.setattr(httpx, "Client", FakeClient)

    resp = post_pr_comment_sync(owner_repo, pr_number, body)

    assert resp["body"] == body


def test_post_pr_comment_sync_no_config(monkeypatch):
    # ensure missing env skips
    monkeypatch.delenv("GITEA_URL", raising=False)
    monkeypatch.delenv("GITEA_TOKEN", raising=False)

    resp = post_pr_comment_sync("owner/repo", 1, "x")
    assert resp is None
