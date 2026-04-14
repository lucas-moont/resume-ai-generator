from app.models import GitHubRepoInfo


def merge_github_with_markdown(
    md_entries: list[dict],
    repos: list[GitHubRepoInfo],
) -> str:
    md_by_repo: dict[str, dict] = {}
    for e in md_entries:
        repo = (e["frontmatter"].get("github_repo") or "").strip().lower()
        if repo:
            md_by_repo[repo] = e
        name_key = e["slug"].lower().replace("_", "-")
        md_by_repo.setdefault(name_key, e)

    blocks: list[str] = []

    for e in md_entries:
        fm = e["frontmatter"]
        repo_full = (fm.get("github_repo") or "").strip()
        gh_line = ""
        if repo_full:
            match = next((r for r in repos if r.full_name.lower() == repo_full.lower()), None)
            if match:
                gh_line = f"\nGitHub metadata: language={match.language} topics={match.topics}"
        blocks.append(
            f"## LOCAL: {e['slug']}\n"
            f"{fm.get('name', e['slug'])}\n"
            f"{e['body'][:8000]}{gh_line}\n"
        )

    linked_full_names = {
        (e["frontmatter"].get("github_repo") or "").lower() for e in md_entries if e["frontmatter"].get("github_repo")
    }
    for r in repos:
        if r.full_name.lower() in linked_full_names:
            continue
        blocks.append(
            f"## GITHUB_ONLY: {r.full_name}\n"
            f"URL: {r.html_url}\n"
            f"Description: {r.description or ''}\n"
            f"Language: {r.language} Topics: {r.topics}\n"
        )

    return "\n---\n".join(blocks) if blocks else "(no unified project context)"
