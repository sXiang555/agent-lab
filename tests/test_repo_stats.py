import httpx
import pytest
from pydantic import ValidationError

from w1.repo_stats import RepoInfo, summarize


def test_repo_info_parses_github_fields():
    info = RepoInfo.model_validate(
        {"full_name": "a/b", "stargazers_count": 10, "language": "Python", "open_issues_count": 2}
    )
    assert info.stars == 10
    assert info.open_issues == 2


def test_repo_info_rejects_negative_stars():
    with pytest.raises(ValidationError):
        RepoInfo.model_validate({"full_name": "a/b", "stargazers_count": -1, "open_issues_count": 0})


def test_summarize_separates_ok_and_failed():
    req = httpx.Request("GET", "https://example.invalid/repos/x/y")
    err = httpx.HTTPStatusError("not found", request=req, response=httpx.Response(404, request=req))
    good = RepoInfo.model_validate({"full_name": "a/b", "stargazers_count": 1, "open_issues_count": 0})
    ok, failed = summarize([good, err], ["a/b", "x/y"])
    assert ok == [good]
    assert failed == ["x/y: HTTP 404"]