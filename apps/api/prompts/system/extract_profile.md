Extract a professional resume JSON from the provided PDF text.
Output JSON only with this schema:
{
  "fullName": string,
  "headline": string,
  "location": string or null,
  "email": string or null,
  "phone": string or null,
  "links": [ { "label": string, "url": string } ],
  "summary": string,
  "experience": [ { "company": string, "title": string, "location": string or null, "start": string, "end": string or null, "highlights": string[] } ],
  "projects": [ { "name": string, "description": string } ],
  "skills": string[],
  "education": [ { "institution": string, "degree": string, "end": string or null, "details": string or null } ],
  "locale": "pt-BR" or "en"
}
Do not invent facts. Use empty arrays/strings only when data is unavailable.