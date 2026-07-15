import type { ResumeDocument, TemplateId } from '../../../types/resume'
import '@resume-templates/resume.css'
import { EditableText } from '../editing/EditableText'
import { ListAddButton, ListRemoveButton } from '../editing/EditableList'

// Ticket 08: every field below is a candidate for inline editing, but the
// component keeps rendering the SAME conditionals/`.map()`s regardless of
// `editable` (per the ticket 06 spike's decision: the toggle swaps which
// LEAF component renders a field, never which tree gets mounted). Only the
// lists with +/- buttons (skills, education, experience, projects,
// per-experience highlights) restructure their list item slightly (a
// wrapping element for the remove button) — harmless in read mode, where
// the button renders null anyway.
//
// Scope limits (ticket 08, documented rather than silently improvised):
// inline editing can change or remove content that's ALREADY rendered; it
// cannot originate a value for a currently-empty optional field (location/
// email/phone/job.location/education.details/...) or bootstrap a first item
// into an empty skills/education/highlights list — those sections stay
// hidden until they have at least one item via chat/upload, exactly as
// before. Links (label/url) are read-only in v2 — not in the ticket's list.
export function ResumePreview({
  resume,
  template = 'modern',
  editable = false,
}: {
  resume: ResumeDocument
  template?: TemplateId
  editable?: boolean
}) {
  const isPt = (resume.locale || '').toLowerCase().startsWith('pt')
  const labels = isPt
    ? {
        summary: 'Resumo',
        experience: 'Experiência',
        projects: 'Projetos',
        technologies: 'Tecnologias',
        education: 'Formação',
        location: 'Localização',
        email: 'E-mail',
        phone: 'Telefone',
        links: 'Links',
        contact: 'Contato',
        present: 'Atual',
        addHighlight: 'Adicionar destaque',
        removeHighlight: 'Remover destaque',
        addSkill: 'Adicionar habilidade',
        removeSkill: 'Remover habilidade',
        addEducation: 'Adicionar formação',
        removeEducation: 'Remover formação',
        addExperience: 'Adicionar experiência',
        removeExperience: 'Remover experiência',
        addProject: 'Adicionar projeto',
        removeProject: 'Remover projeto',
      }
    : {
        summary: 'Summary',
        experience: 'Experience',
        projects: 'Projects',
        technologies: 'Technologies',
        education: 'Education',
        location: 'Location',
        email: 'Email',
        phone: 'Phone',
        links: 'Links',
        contact: 'Contact',
        present: 'Present',
        addHighlight: 'Add highlight',
        removeHighlight: 'Remove highlight',
        addSkill: 'Add skill',
        removeSkill: 'Remove skill',
        addEducation: 'Add education entry',
        removeEducation: 'Remove education entry',
        addExperience: 'Add experience entry',
        removeExperience: 'Remove experience entry',
        addProject: 'Add project',
        removeProject: 'Remove project',
      }
  return (
    <div className="resume-doc">
      <div className={`page tpl-${template}`}>
        <header className="doc-header">
          <div className="doc-header-main">
            <EditableText as="h1" className="name" mode="plain" path="fullName" value={resume.fullName} editable={editable} />
            <EditableText as="p" className="headline" mode="rich" path="headline" value={resume.headline} editable={editable} />
          </div>
          <ul className="contact-bar">
            {resume.location && (
              <li className="contact-item">
                <EditableText as="span" mode="plain" path="location" value={resume.location} editable={editable} />
              </li>
            )}
            {resume.email && (
              <li className="contact-item">
                <EditableText as="span" mode="plain" path="email" value={resume.email} editable={editable} />
              </li>
            )}
            {resume.phone && (
              <li className="contact-item tabular">
                <EditableText as="span" mode="plain" path="phone" value={resume.phone} editable={editable} />
              </li>
            )}
            {resume.links?.map((link, i) => (
              <li className="contact-item" key={i}>
                <a href={link.url} target="_blank" rel="noreferrer">
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </header>
        <div className="layout">
          <main className="main">
            {resume.summary && (
              <section className="main-section">
                <h2 className="section-label">
                  <span className="section-accent" />
                  {labels.summary}
                </h2>
                <EditableText as="p" className="summary" mode="rich" path="summary" value={resume.summary} editable={editable} />
              </section>
            )}
            {resume.experience?.length > 0 && (
              <section className="main-section">
                <h2 className="section-label">
                  <span className="section-accent" />
                  {labels.experience}
                </h2>
                {resume.experience.map((job, i) => (
                  <article className="exp relative" key={i}>
                    <ListRemoveButton
                      path="experience"
                      index={i}
                      label={labels.removeExperience}
                      editable={editable}
                      className="absolute right-0 top-0"
                    />
                    <div className="exp-head">
                      <EditableText
                        as="span"
                        className="exp-title"
                        mode="plain"
                        path={`experience.${i}.title`}
                        value={job.title}
                        editable={editable}
                      />
                      <EditableText
                        as="span"
                        className="exp-company"
                        mode="plain"
                        path={`experience.${i}.company`}
                        value={job.company}
                        editable={editable}
                      />
                      <span className="exp-dates tabular">
                        <EditableText
                          as="span"
                          mode="plain"
                          path={`experience.${i}.start`}
                          value={job.start}
                          editable={editable}
                        />{' '}
                        —{' '}
                        {job.end ? (
                          <EditableText
                            as="span"
                            mode="plain"
                            path={`experience.${i}.end`}
                            value={job.end}
                            editable={editable}
                          />
                        ) : (
                          labels.present
                        )}
                      </span>
                    </div>
                    {job.location && (
                      <EditableText
                        as="p"
                        className="exp-loc"
                        mode="plain"
                        path={`experience.${i}.location`}
                        value={job.location}
                        editable={editable}
                      />
                    )}
                    {job.highlights?.length > 0 && (
                      <>
                        <ul className="exp-list">
                          {job.highlights.map((h, j) => (
                            <li key={j}>
                              <EditableText
                                as="span"
                                mode="rich"
                                path={`experience.${i}.highlights.${j}`}
                                value={h}
                                editable={editable}
                              />
                              <ListRemoveButton
                                path={`experience.${i}.highlights`}
                                index={j}
                                label={labels.removeHighlight}
                                editable={editable}
                                className="ml-1 align-middle"
                              />
                            </li>
                          ))}
                        </ul>
                        <ListAddButton
                          path={`experience.${i}.highlights`}
                          label={labels.addHighlight}
                          editable={editable}
                          className="mt-1"
                        />
                      </>
                    )}
                  </article>
                ))}
                <ListAddButton path="experience" label={labels.addExperience} editable={editable} className="mt-1" />
              </section>
            )}
            {resume.projects?.length > 0 && (
              <section className="main-section">
                <h2 className="section-label">
                  <span className="section-accent" />
                  {labels.projects}
                </h2>
                {resume.projects.map((proj, i) => (
                  <article className="proj relative" key={i}>
                    <ListRemoveButton
                      path="projects"
                      index={i}
                      label={labels.removeProject}
                      editable={editable}
                      className="absolute right-0 top-0"
                    />
                    <EditableText
                      as="h3"
                      className="proj-name"
                      mode="rich"
                      path={`projects.${i}.name`}
                      value={proj.name}
                      editable={editable}
                    />
                    <EditableText
                      as="p"
                      className="proj-desc"
                      mode="rich"
                      path={`projects.${i}.description`}
                      value={proj.description}
                      editable={editable}
                    />
                  </article>
                ))}
                <ListAddButton path="projects" label={labels.addProject} editable={editable} className="mt-1" />
              </section>
            )}
            {resume.skills?.length > 0 && (
              <section className="main-section">
                <h2 className="section-label">
                  <span className="section-accent" />
                  {labels.technologies}
                </h2>
                <ul className="skill-chips main-skills">
                  {resume.skills.map((s, i) => (
                    <li key={i}>
                      <EditableText as="span" mode="plain" path={`skills.${i}`} value={s} editable={editable} />
                      <ListRemoveButton
                        path="skills"
                        index={i}
                        label={labels.removeSkill}
                        editable={editable}
                        className="ml-1 align-middle"
                      />
                    </li>
                  ))}
                </ul>
                <ListAddButton path="skills" label={labels.addSkill} editable={editable} className="mt-1" />
              </section>
            )}
            {resume.education?.length > 0 && (
              <section className="main-section">
                <h2 className="section-label">
                  <span className="section-accent" />
                  {labels.education}
                </h2>
                {resume.education.map((ed, i) => (
                  <article className="edu relative" key={i}>
                    <ListRemoveButton
                      path="education"
                      index={i}
                      label={labels.removeEducation}
                      editable={editable}
                      className="absolute right-0 top-0"
                    />
                    <div className="edu-head">
                      <EditableText
                        as="span"
                        className="edu-degree"
                        mode="plain"
                        path={`education.${i}.degree`}
                        value={ed.degree}
                        editable={editable}
                      />
                      <EditableText
                        as="span"
                        className="edu-inst"
                        mode="plain"
                        path={`education.${i}.institution`}
                        value={ed.institution}
                        editable={editable}
                      />
                      {ed.end && (
                        <EditableText
                          as="span"
                          className="edu-end tabular"
                          mode="plain"
                          path={`education.${i}.end`}
                          value={ed.end}
                          editable={editable}
                        />
                      )}
                    </div>
                    {ed.details && (
                      <EditableText
                        as="p"
                        className="edu-details"
                        mode="rich"
                        path={`education.${i}.details`}
                        value={ed.details}
                        editable={editable}
                      />
                    )}
                  </article>
                ))}
                <ListAddButton path="education" label={labels.addEducation} editable={editable} className="mt-1" />
              </section>
            )}
          </main>
          <aside className="sidebar" aria-label={labels.contact}>
            {resume.location && (
              <section className="side-block">
                <h2 className="side-title">{labels.location}</h2>
                <p className="side-text">
                  <EditableText mode="plain" path="location" value={resume.location} editable={editable} />
                </p>
              </section>
            )}
            {resume.email && (
              <section className="side-block">
                <h2 className="side-title">{labels.email}</h2>
                <p className="side-text">
                  <a href={`mailto:${resume.email}`}>{resume.email}</a>
                </p>
              </section>
            )}
            {resume.phone && (
              <section className="side-block">
                <h2 className="side-title">{labels.phone}</h2>
                <p className="side-text tabular">
                  <EditableText mode="plain" path="phone" value={resume.phone} editable={editable} />
                </p>
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
