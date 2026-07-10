"""Job-description keyword extraction -- extracted from app/main.py (B2)."""

import re


def normalize_token(s: str) -> str:
    return re.sub(r"[^a-z0-9.+#-]+", "", s.lower())


# Broad (not exhaustive) technology vocabulary used to spot job-description keywords.
TECH_VOCAB = frozenset(
    normalize_token(t)
    for t in (
        "javascript", "typescript", "python", "java", "kotlin", "swift", "go", "golang", "rust",
        "ruby", "php", "c", "c++", "c#", "scala", "elixir", "dart", "r", "matlab", "bash", "shell",
        "react", "react native", "next.js", "vue", "nuxt", "angular", "svelte", "solid", "astro",
        "redux", "tailwind", "bootstrap", "jquery", "html", "css", "sass", "webpack", "vite",
        "node.js", "node", "express", "nestjs", "fastapi", "flask", "django", "spring", "spring boot",
        ".net", "asp.net", "laravel", "rails", "graphql", "rest", "grpc", "websocket",
        "postgresql", "postgres", "mysql", "mariadb", "sqlite", "mongodb", "redis", "cassandra",
        "dynamodb", "elasticsearch", "kafka", "rabbitmq", "sql", "nosql", "prisma", "sqlalchemy",
        "aws", "azure", "gcp", "google cloud", "lambda", "s3", "ec2", "eks", "ecs", "cloudformation",
        "terraform", "ansible", "docker", "kubernetes", "k8s", "helm", "jenkins", "gitlab",
        "github actions", "ci/cd", "cicd", "linux", "nginx", "serverless",
        "git", "jira", "agile", "scrum", "kanban", "microservices", "tdd", "oauth", "jwt",
        "pandas", "numpy", "pytorch", "tensorflow", "scikit-learn", "spark", "airflow", "dbt",
        "machine learning", "deep learning", "nlp", "llm", "openai", "langchain",
        "playwright", "cypress", "jest", "pytest", "selenium", "storybook", "figma",
    )
)

JD_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "you", "your", "our", "will", "are", "have", "has", "that",
        "this", "from", "who", "what", "when", "where", "how", "all", "any", "not", "but", "can",
        "team", "work", "role", "job", "experience", "years", "year", "strong", "good", "great",
        "para", "com", "que", "uma", "dos", "das", "por", "como", "seu", "sua", "mais", "nossa",
    }
)


def extract_jd_keywords(job_description: str) -> list[str]:
    """Extract likely technology/skill keywords from a job description, stack-agnostically.

    Heuristics: known-tech vocabulary, tokens with tech punctuation (Node.js, C#, CI/CD),
    and acronyms/PascalCase identifiers (API, AWS, GraphQL, PostgreSQL).
    """
    raw_tokens = re.findall(r"[A-Za-z][A-Za-z0-9.+#/-]*", job_description)
    counts: dict[str, int] = {}
    order: list[str] = []
    for raw_tok in raw_tokens:
        # Drop sentence punctuation glued to the edges (e.g. "scalability." or "libraries,").
        tok = raw_tok.strip(".,;:/-")
        if not tok:
            continue
        norm = normalize_token(tok)
        if len(norm) < 2 or norm in JD_STOPWORDS:
            continue
        # Only treat punctuation as a tech signal when it is INTERNAL (Node.js, CI/CD) or a known
        # trailing form (C++, C#) — never a trailing sentence period.
        has_tech_punct = bool(re.search(r"[A-Za-z0-9][.+#/][A-Za-z0-9]", tok)) or tok.endswith(("++", "#"))
        is_acronym = tok.isupper() and len(tok) >= 2
        is_pascal = tok[0].isupper() and any(c.isupper() for c in tok[1:])
        looks_tech = norm in TECH_VOCAB or has_tech_punct or is_acronym or is_pascal
        if not looks_tech:
            continue
        if norm not in counts:
            order.append(norm)
        counts[norm] = counts.get(norm, 0) + 1
    index_of = {n: i for i, n in enumerate(order)}
    order.sort(key=lambda n: (-counts[n], index_of[n]))
    return order
