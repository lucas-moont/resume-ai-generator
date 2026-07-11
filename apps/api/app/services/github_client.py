import httpx

from app import config as config_module
from app.models import GitHubRepoInfo


async def fetch_user_repos(username: str, limit: int = 50) -> tuple[list[GitHubRepoInfo], str | None]:
    if not username:
        return [], None
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    github_token = config_module.resolve_github_token()
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    url = f"https://api.github.com/users/{username}/repos"
    params = {"per_page": min(limit, 100), "sort": "updated", "type": "all"}
    warn: str | None = None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers=headers, params=params)
            if r.status_code == 404:
                return [], "GitHub user not found"
            if r.status_code == 403:
                return [], "GitHub rate limit or forbidden — set GITHUB_TOKEN in .env"
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        return [], f"GitHub request failed: {e}"
    repos: list[GitHubRepoInfo] = []
    for row in data[:limit]:
        repos.append(
            GitHubRepoInfo(
                name=row.get("name", ""),
                full_name=row.get("full_name", ""),
                html_url=row.get("html_url", ""),
                description=row.get("description"),
                language=row.get("language"),
                topics=list(row.get("topics") or []),
                private=bool(row.get("private")),
            )
        )
    if not repos:
        warn = "No repositories returned (empty account or private-only without token)"
    return repos, warn


def repos_to_context_string(repos: list[GitHubRepoInfo]) -> str:
    if not repos:
        return "(no GitHub repos in response)"
    lines: list[str] = []
    for r in repos:
        topics = ", ".join(r.topics) if r.topics else ""
        desc = r.description or ""
        lines.append(
            f"- {r.full_name} ({r.html_url}) lang={r.language or 'n/a'} topics=[{topics}] private={r.private}\n  {desc}"
        )
    return "\n".join(lines)
