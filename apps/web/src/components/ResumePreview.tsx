import type { ResumeDocument } from '../types/resume'
import '../resume-print.css'
import { SafeRichHtml } from './SafeRichHtml'

export function ResumePreview({ resume }: { resume: ResumeDocument }) {
  const isPt = (resume.locale || '').toLowerCase().startsWith('pt')
  const labels = isPt
    ? {
        summary: 'Resumo',
        experience: 'Experiência',
        projects: 'Projetos',
        technologies: 'Tecnologias',
        education: 'Formação',
        location: 'Localização',
        phone: 'Telefone',
        links: 'Links',
        present: 'Atual',
      }
    : {
        summary: 'Summary',
        experience: 'Experience',
        projects: 'Projects',
        technologies: 'Technologies',
        education: 'Education',
        location: 'Location',
        phone: 'Phone',
        links: 'Links',
        present: 'Present',
      }
  return (
    <div className="resume-doc preview-scale">
      <div className="page">
        <header className="doc-header">
          <div className="doc-header-main">
            <h1 className="name">{resume.fullName}</h1>
            <SafeRichHtml as="p" className="headline" html={resume.headline} />
          </div>
        </header>
        <div className="layout">
          <main className="main">
            <section className="main-section">
              <h2 className="section-label">
                <span className="section-accent">//</span> {labels.summary}
              </h2>
              <SafeRichHtml as="p" className="summary" html={resume.summary} />
            </section>
            {resume.experience?.length > 0 && (
              <section className="main-section">
                <h2 className="section-label">
                  <span className="section-accent">//</span> {labels.experience}
                </h2>
                {resume.experience.map((job, i) => (
                  <article className="exp" key={i}>
                    <div className="exp-head">
                      <span className="exp-title">{job.title}</span>
                      <span className="exp-company">{job.company}</span>
                      <span className="exp-dates tabular">
                        {job.start} — {job.end ?? labels.present}
                      </span>
                    </div>
                    {job.location && <p className="exp-loc">{job.location}</p>}
                    {job.highlights?.length > 0 && (
                      <ul className="exp-list">
                        {job.highlights.map((h, j) => (
                          <SafeRichHtml as="li" key={j} html={h} />
                        ))}
                      </ul>
                    )}
                  </article>
                ))}
              </section>
            )}
            {resume.projects?.length > 0 && (
              <section className="main-section">
                <h2 className="section-label">
                  <span className="section-accent">//</span> {labels.projects}
                </h2>
                {resume.projects.map((proj, i) => (
                  <article className="proj" key={i}>
                    <SafeRichHtml as="h3" className="proj-name" html={proj.name} />
                    <SafeRichHtml as="p" className="proj-desc" html={proj.description} />
                  </article>
                ))}
              </section>
            )}
            {resume.skills?.length > 0 && (
              <section className="main-section">
                <h2 className="section-label">
                  <span className="section-accent">//</span> {labels.technologies}
                </h2>
                <ul className="skill-chips main-skills">
                  {resume.skills.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </section>
            )}
            {resume.education?.length > 0 && (
              <section className="main-section">
                <h2 className="section-label">
                  <span className="section-accent">//</span> {labels.education}
                </h2>
                {resume.education.map((ed, i) => (
                  <article className="edu" key={i}>
                    <div className="edu-head">
                      <span className="edu-degree">{ed.degree}</span>
                      <span className="edu-inst">{ed.institution}</span>
                      {ed.end && (
                        <span className="edu-end tabular">{ed.end}</span>
                      )}
                    </div>
                    {ed.details && (
                      <SafeRichHtml as="p" className="edu-details" html={ed.details} />
                    )}
                  </article>
                ))}
              </section>
            )}
          </main>
          <aside className="sidebar" aria-label="Contact">
            {resume.location && (
              <section className="side-block">
                <h2 className="side-title">{labels.location}</h2>
                <p className="side-text">{resume.location}</p>
              </section>
            )}
            {resume.phone && (
              <section className="side-block">
                <h2 className="side-title">{labels.phone}</h2>
                <p className="side-text tabular">{resume.phone}</p>
              </section>
            )}
            {resume.links?.length > 0 && (
              <section className="side-block">
                <h2 className="side-title">{labels.links}</h2>
                <ul className="side-links">
                  {resume.links.map((link, i) => (
                    <li key={i}>
                      <a href={link.url} target="_blank" rel="noreferrer">
                        {link.label}
                      </a>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </aside>
        </div>
      </div>
    </div>
  )
}
