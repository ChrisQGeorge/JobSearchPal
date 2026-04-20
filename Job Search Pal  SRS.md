# Software Requirements Specification
## For Job Search Pal

## Table of Contents
<!-- TOC -->
* [1. Introduction](#1-introduction)
    * [1.1 Document Purpose](#11-document-purpose)
    * [1.2 Product Scope](#12-product-scope)
    * [1.3 Definitions, Acronyms, and Abbreviations](#13-definitions-acronyms-and-abbreviations)
    * [1.4 References](#14-references)
    * [1.5 Document Overview](#15-document-overview)
* [2. Product Overview](#2-product-overview)
    * [2.1 Product Perspective](#21-product-perspective)
    * [2.2 Product Functions](#22-product-functions)
    * [2.3 Product Constraints](#23-product-constraints)
    * [2.4 User Characteristics](#24-user-characteristics)
    * [2.5 Assumptions and Dependencies](#25-assumptions-and-dependencies)
    * [2.6 Apportioning of Requirements](#26-apportioning-of-requirements)
* [3. Requirements](#3-requirements)
    * [3.1 External Interfaces](#31-external-interfaces)
    * [3.2 Functional](#32-functional)
    * [3.3 Quality of Service](#33-quality-of-service)
    * [3.4 Compliance](#34-compliance)
    * [3.5 Design and Implementation](#35-design-and-implementation)
    * [3.6 AI/ML](#36-aiml)
* [4. Verification](#4-verification)
* [5. Appendixes](#5-appendixes)
<!-- TOC -->



## 1. Introduction

Job Search Pal is a Claude Code–based companion that helps the user run their job search end-to-end. It combines three things:

1. A set of **console-based Claude Code skills** that can take concrete actions — analyze job descriptions, tailor resumes and cover letters, draft emails, research companies, record history, and more.
2. A **web interface** that surfaces the user's canonical history (work, education, courses, projects, publications, achievements, certifications, skills) as a complete, dated timeline, tracks applied and watched jobs (including interview rounds and artifacts), and exposes one-click generation of resumes, CVs, cover letters, and emails tailored to a specific job.
3. A **writing-samples library** of the user's own work, so any AI-generated content can be humanized to match the user's voice before leaving the app.

The tone target is an ironic corporate-dystopian lightness — lighthearted and funny, but with edges.

### 1.1 Document Purpose

This document exists so that an AI agent can "vibe code" the application from scratch. Use it to inform design and development decisions, but feel free to add sensible QOL improvements along the way. Requirements marked *shall* are binding; *should* and *may* are preferences.

### 1.2 Product Scope

Job Search Pal's primary purpose is to use Claude Code to make a job search faster and less painful: tracking opportunities and applications, maintaining a rich personal history, and generating tailored application materials — with a Companion persona that keeps the process lighthearted in an ironic, retro-futurist way. The aesthetic target is the *Outer Worlds* franchise: ironic, corporate, funny, and slightly dystopian.

The application consists of two top-level systems:

1. A set of Claude Code **skills** the Companion can invoke to: give job-search advice, tailor resumes and cover letters to specific job descriptions, record and maintain the user's history, ask relevant clarifying questions, analyze job descriptions, research companies, prep for interviews, and generally advance the search. A single skill may cover several of these responsibilities.
2. A clean **web UI** that lets the user: enter and edit their personal history, upload writing samples, track applied and watched jobs through detailed status stages with interview artifacts attached, customize generated documents in-place, and converse with the Companion.


#### Pages

The web interface is made up of the following pages. Tone across all pages should lean into the ironic corporate-dystopia aesthetic (think Spacer's Choice / Auntie Cleo's from *The Outer Worlds*): cheerful copy, slightly ominous subtext, retro-futurist visual cues.

A global UI behavior applies to every rich-text editor in the app (Document Studio, Job Description, Notes fields, Cover Letter, Email drafts, etc.): the user can highlight any portion of text and a floating action pops up offering "Send to Companion." That opens a small prompt box where the user can add notes ("make it punchier", "reword for a senior role", "translate to casual email tone"), and the companion returns a rewrite that can be accepted, rejected, or iterated. Every such rewrite is recorded as a `DocumentEdit` so the history is auditable.

1. **Dashboard** — Landing page. The companion greets the user in-character, then the page surfaces two bands of content:
   - **Activity band**: recent application events, pending follow-ups, upcoming interviews, open tasks, and quick-action buttons (track a new job, generate a document, chat with companion, run a skill).
   - **Metrics band**: a detailed, chart-heavy analytics area rendered with clean, minimal charts. All charts are interactive (hover for counts/percentages, click a segment to filter the underlying list view). Expected charts include:
     - Pie: application outcomes (applied, responded, interviewing, offer, won, lost, ghosted).
     - Funnel: applied → responded → interviewed → offered → accepted.
     - Bar: applications per week / month over time.
     - Bar: response rate by company size, industry, or source.
     - Stacked bar: interview rounds cleared per company.
     - Donut: skill distribution from history (technical / soft / domain / tool).
     - Horizontal bar: years of experience per skill, role, or technology.
     - Timeline histogram: courses completed per term, publications per year, achievements per year.
     - KPI tiles: total years of professional experience, total courses taken, total certifications, total tracked jobs, current active applications, average days-to-response.
   - Metrics must support a date-range filter and an "include/exclude archived" toggle.
2. **Career Timeline** — Visual chronological timeline of **every** dated event in the user's history, not just work experience. Events include: work experiences, education terms, individual courses taken, certifications earned, projects (start/end), publications, presentations/talks, achievements and awards, volunteer work, and any user-defined custom event type. Each event type has a distinct icon and color. The timeline supports type filters, date-range zoom, grouping by year/decade/role, and click-through to the corresponding History Editor entity.
3. **History Editor** — CRUD interface for every historical entity that feeds the timeline and the AI skills: work experience, education, **courses taken** (per education entry), skills, certifications, projects, publications, presentations, achievements, volunteer work, languages, and personal contacts / networking entries. This is the canonical source of truth that every AI skill draws from.
4. **Job Tracker** — Sortable/filterable list of jobs at every stage of the user's funnel. Shows company, title, status, current interview round, last-activity date, and source. Supports bulk import (e.g., paste a job URL), manual entry, and an "add job" modal that kicks off the creation flow described in Job Detail. Status filter exposes the full status vocabulary defined on `TrackedJob.status`: `watching`, `interested`, `applied`, `responded`, `screening`, `interviewing`, `assessment`, `offer`, `won` (accepted), `lost` (rejected or declined by user), `withdrawn`, `ghosted`, `archived`.
5. **Job Detail** — Single job view with tabs or panels for:
   - **Overview**: job description, company info, source URL, salary, location / remote policy, status, priority, notes.
   - **Interview Rounds**: ordered list of `InterviewRound` records for this job (round number, format, date, interviewer(s), outcome, notes).
   - **Interview Artifacts**: uploaded files and links attached to rounds — take-home assignments, whiteboard screenshots, prep notes, post-interview reflections, recruiter emails, offer letters — stored for future-session reference.
   - **Contacts**: people at the company the user has interacted with.
   - **Documents**: resumes, cover letters, and emails that have been generated for this job, with version history.
   - **Activity**: a chronological `ApplicationEvent` feed.

   **Creation / editing flow**: while entering or updating job info, action buttons are available inline to perform common tasks without leaving the page. At minimum: *Generate Tailored Resume*, *Generate Cover Letter*, *Draft Follow-up Email*, *Analyze Job Description*, *Research Company*. Clicking any of these runs the relevant skill and opens a **side-panel editor** with the generated artifact for quick editing. The side-panel editor supports the global "select text → send to Companion" rewrite behavior described above.
6. **Document Studio** — Interface to generate and iterate on tailored resumes, CVs, cover letters, and emails for a selected target job. Shows a side-by-side of source history vs. generated output, with regenerate / humanize / edit controls, version history, and diff view between versions. Fully supports the selection-to-Companion rewrite flow.
7. **Writing Samples Library** — Upload, tag, and manage samples of the user's own writing. Samples are the reference corpus the humanizer skill uses to rewrite AI output in the user's voice. Supports drag-and-drop upload (txt, md, pdf, docx), per-sample tagging, and a "paste-in" quick entry.
8. **Companion Chat** — Primary conversational surface to Claude Code. Persistent conversation history, skill invocations visible inline, and the ability to pin messages, promote them to tasks/notes, or attach them to a specific `TrackedJob`.
9. **Settings** — User profile basics, API keys / credentials, theme (light / dark / "corporate-approved"), data export, account controls, and **AI Persona selection**. The persona panel lets the user pick from a set of built-in personas (e.g., *Spacer's Choice Cheerful Cog*, *Auntie Cleo Concerned Associate*, *Straight-Laced Career Coach*, *Dry and Professional*) or define a custom persona with a name, a tone description, a system-prompt snippet, and an optional avatar. The active persona is applied globally to all skill outputs and Companion responses.

#### Schemas

Core data models (MySQL-backed). Timestamps (`created_at`, `updated_at`) and soft-delete (`deleted_at`) are assumed on every table and omitted below for brevity. Fields marked *(JSON)* are stored as JSON columns for flexibility.

**Identity and preferences**

1. **User** — id, email, display_name, hashed_password, avatar_url, active_persona_id (FK Persona), preferences *(JSON — includes theme, metric defaults, default humanize toggle, timezone, locale)*.
2. **Persona** — id, user_id, name, description, tone_descriptors *(JSON array — e.g., "sardonic", "cheerful", "formal")*, system_prompt, avatar_url, is_builtin (bool), is_active (bool).
3. **ApiCredential** — id, user_id, provider (anthropic / openai / other), label, encrypted_secret, last_used_at.

**Canonical history**

4. **WorkExperience** — id, user_id, company_id (FK), title, start_date, end_date (nullable — null == current), location, employment_type (full_time / part_time / contract / internship / freelance / self_employed), summary, highlights *(JSON array of bullet points)*, technologies_used *(JSON array)*, team_size, manager_name, reason_for_leaving.
5. **WorkExperienceSkill** — join table: work_experience_id, skill_id, usage_notes.
6. **Education** — id, user_id, institution, degree (e.g., B.S., M.A., Ph.D.), field_of_study, minor, start_date, end_date (nullable), gpa, honors *(JSON array — e.g., "summa cum laude", "Dean's List Fall 2021")*, thesis_title, thesis_summary, notes.
7. **Course** — id, education_id (FK), code, name, term (e.g., "Fall 2022"), credits, grade, description, topics_covered *(JSON array)*, notable_work (e.g., capstone project description), instructor.
8. **Certification** — id, user_id, name, issuer, issued_date, expires_date (nullable), credential_id, credential_url, verification_status.
9. **Skill** — id, user_id, name, category (technical / soft / domain / tool / language), proficiency (novice / intermediate / advanced / expert), years_experience, last_used_date, evidence_notes.
10. **Language** — id, user_id, name, proficiency (basic / conversational / professional / fluent / native), certifications *(JSON array)*.
11. **Project** — id, user_id, name, summary, description_md, url, repo_url, start_date, end_date (nullable), is_ongoing (bool), role, collaborators *(JSON)*, highlights *(JSON array)*, technologies_used *(JSON array)*, visibility (public / private / portfolio_only).
12. **Publication** — id, user_id, title, type (journal_article / conference_paper / book / book_chapter / blog_post / whitepaper / other), venue, publication_date, authors *(JSON array, in order)*, doi, url, abstract, citation_count, notes.
13. **Presentation** — id, user_id, title, venue, event_name, date, audience_size, format (talk / workshop / panel / poster), slides_url, recording_url, summary.
14. **Achievement** — id, user_id, title, type (award / recognition / milestone / competition_result / scholarship / grant / patent / other), date, issuer, description, url, supporting_document_url.
15. **VolunteerWork** — id, user_id, organization, role, cause_area, start_date, end_date (nullable), hours_total, summary, highlights *(JSON)*.
16. **Contact** — id, user_id, company_id (nullable), name, role, email, phone, linkedin_url, other_links *(JSON)*, notes, relationship_type (recruiter / referral / hiring_manager / peer / mentor / other), last_contacted_date.
17. **CustomEvent** — id, user_id, type_label, title, description, start_date, end_date (nullable), metadata *(JSON)*. Catch-all for any dated event the user wants on the timeline that does not fit another schema.

**Companies and jobs**

18. **Company** — id, name, website, industry, size (e.g., "11-50", "201-500"), headquarters_location, founded_year, description, research_notes (AI-assembled summary), source_links *(JSON)*, reputation_signals *(JSON — e.g., Glassdoor rating, news highlights)*, tech_stack_hints *(JSON)*.
19. **TrackedJob** — id, user_id, company_id (FK), title, job_description, source_url, source_platform (linkedin / indeed / company_site / referral / other), location, remote_policy (onsite / hybrid / remote), salary_min, salary_max, salary_currency, equity_notes, priority (low / medium / high), status (enum: watching / interested / applied / responded / screening / interviewing / assessment / offer / won / lost / withdrawn / ghosted / archived), notes, jd_analysis *(JSON — output of jd-analyzer skill)*, date_posted, date_discovered, date_applied, date_closed.
20. **ApplicationEvent** — id, tracked_job_id (FK), event_type (applied / responded / phone_screen / interview_scheduled / interview_completed / assessment_assigned / assessment_submitted / offer_received / offer_accepted / offer_declined / rejection / withdrawal / follow_up / note / other), event_date, details_md, related_round_id (FK InterviewRound nullable), attachments *(JSON array of InterviewArtifact IDs or file refs)*.
21. **InterviewRound** — id, tracked_job_id (FK), round_number, round_type (recruiter_screen / hiring_manager / technical / system_design / behavioral / panel / take_home / onsite / final / other), scheduled_at, duration_minutes, format (phone / video / in_person), location_or_link, interviewers *(JSON array of {name, role, contact_id?}*), outcome (pending / passed / failed / mixed / unknown), self_rating (1–5), notes_md, prep_notes_md.
22. **InterviewArtifact** — id, interview_round_id (FK nullable), tracked_job_id (FK), kind (take_home / whiteboard_capture / notes / feedback / offer_letter / recruiter_email / prep_doc / other), title, file_url, mime_type, content_md (for inline text artifacts), source (uploaded / generated / pasted), tags *(JSON)*.

**Generated content and Companion**

23. **GeneratedDocument** — id, user_id, tracked_job_id (FK nullable), doc_type (resume / cv / cover_letter / email / interview_prep / other), title, content_md, content_structured *(JSON — optional, for templated formats)*, version, parent_version_id (nullable, self-FK), humanized (bool), humanized_from_samples *(JSON array of WritingSample IDs)*, model_used, persona_id (FK Persona), prompt_snapshot, source_skill.
24. **DocumentEdit** — id, generated_document_id (FK), editor (user / companion), action (rewrite_selection / accept_suggestion / reject_suggestion / manual_edit), selection_start, selection_end, selection_text, user_notes, replacement_text, accepted (bool), created_at.
25. **WritingSample** — id, user_id, title, content_md, tags *(JSON)*, source (original / blog / email / paper / journal / other), word_count, style_signals *(JSON — optional cached analysis: avg sentence length, vocabulary markers, etc.)*.
26. **CompanionConversation** — id, user_id, title, summary, pinned (bool), related_tracked_job_id (FK nullable), persona_id (FK Persona).
27. **ConversationMessage** — id, conversation_id (FK), role (user / assistant / tool / system), content_md, skill_invoked (nullable), tool_calls *(JSON)*, tool_results *(JSON)*, attachments *(JSON)*, created_at.
28. **Task** — id, user_id, tracked_job_id (FK nullable), title, description, due_date, status (open / in_progress / done / dismissed), priority, source (companion / manual), related_event_id (FK ApplicationEvent nullable).

**Operational**

29. **AuditLog** — id, user_id, actor (user / skill_name / system), action, entity_type, entity_id, diff *(JSON)*, created_at. Captures every mutation so the user can review what skills changed on their behalf.
30. **MetricSnapshot** — id, user_id, metric_key, period (daily / weekly / monthly / all_time), period_start, period_end, value *(JSON)*, computed_at. Optional caching layer for dashboard charts.

#### Skills

Claude Code skills are the action surface the companion uses. Each skill is self-contained, reads from the user's canonical history / writing samples via the API, and writes results back as `GeneratedDocument`, `ApplicationEvent`, or history updates where appropriate. Every skill inherits tone from the active `Persona`.

1. **resume-tailor** — Given a `TrackedJob`, produces a tailored resume drawing only from the user's real history. Highlights keyword overlap with the JD and flags any gaps it could not truthfully cover.
2. **cover-letter-tailor** — Generates a cover letter for a `TrackedJob` referencing specific job requirements and matching user experience. Always passes output through `writing-humanizer` before returning.
3. **email-drafter** — Drafts job-search emails: application follow-ups, thank-you notes, recruiter replies, networking outreach, salary negotiation. Parameterized by tone and recipient.
4. **jd-analyzer** — Extracts required/nice-to-have skills, seniority signals, culture cues, and red flags from a pasted or linked job description. Persists output to `TrackedJob.jd_analysis`.
5. **company-researcher** — Gathers publicly available information about a company (recent news, tech stack hints, reputation signals) and writes a summary to `Company.research_notes`.
6. **history-interviewer** — Asks the user targeted questions to fill gaps in their `WorkExperience`, `Education`, `Course`, `Skill`, `Publication`, `Achievement`, etc. entries. Writes answers directly to the canonical history after confirmation.
7. **application-tracker** — Creates and updates `TrackedJob`, `ApplicationEvent`, and `InterviewRound` records from conversational input ("I just applied to X", "had my second-round technical with Y"). Can also suggest next actions and create `Task` records.
8. **writing-humanizer** — Rewrites AI-generated text to match the user's voice using `WritingSample` records as reference. Invoked implicitly by other generation skills unless disabled, and directly by the global "select text → Send to Companion" UI.
9. **interview-prep** — Generates role-specific practice questions from a `TrackedJob`, runs mock-interview drills, stores prep docs as `InterviewArtifact` records, and gives feedback. Can reference prior answers across sessions.
10. **interview-retrospective** — After an `InterviewRound` is marked complete, prompts the user for reflections, captures lessons learned, and stores them as `InterviewArtifact` records tagged `feedback` for future prep.
11. **job-strategy-advisor** — Higher-level advisor skill. Reviews the user's tracked jobs, response rates, and history to recommend search-strategy adjustments (targeting, resume positioning, skill gaps to close). Reads from `MetricSnapshot` where available.
12. **selection-rewriter** — Targeted skill invoked by the in-editor "Send to Companion" action. Takes a selection, surrounding context, and user notes; returns a rewrite. Always records a `DocumentEdit`.
13. **companion-persona** — Not a task skill — the wrapper that keeps Claude Code in-character across interactions according to the active `Persona`. Other skills defer tone decisions to this one.


### 1.3 Definitions, Acronyms, and Abbreviations
| Term |       Definition       |
|------|------------------------|
| QOL  | Quality Of Life        |                |
| JD   | Job Description        |
| CV   | Curriculum Vitae       |
| LLM  | Large Language Model   |
| RBAC | Role-Based Access Control |
| PII  | Personally Identifiable Information |
| SRS  | Software Requirements Specification |
| UI   | User Interface         |
| API  | Application Programming Interface |
| MVP  | Minimum Viable Product |
| CRUD | Create, Read, Update, Delete |
| WCAG | Web Content Accessibility Guidelines |
| SLO  | Service Level Objective |
| HITL | Human-in-the-Loop      |

### 1.4 References

The following references inform this SRS. References are marked **[N]** normative (binding — the implementation must comply) or **[I]** informative (guidance).

- **[N]** Next.js Documentation — Vercel, current stable (app router). https://nextjs.org/docs
- **[N]** FastAPI Documentation — Sebastián Ramírez, current stable. https://fastapi.tiangolo.com/
- **[N]** MySQL 8.x Reference Manual — Oracle. https://dev.mysql.com/doc/refman/8.0/en/
- **[N]** Docker Compose Specification — Docker Inc., current v2 spec. https://docs.docker.com/compose/compose-file/
- **[N]** Anthropic Claude API Documentation — Anthropic, current. https://docs.anthropic.com
- **[N]** Claude Code Skills Documentation — Anthropic, current. https://docs.claude.com/en/docs/claude-code/skills
- **[N]** WCAG 2.1 Level AA — W3C. https://www.w3.org/TR/WCAG21/
- **[I]** OWASP Top 10 (current edition) — https://owasp.org/Top10/
- **[I]** *The Outer Worlds* — Obsidian Entertainment, 2019. Tone and visual-vibe reference for copy and UI styling; not a functional requirement.
- **[I]** This repository's Git history — the authoritative log of design decisions over time.

### 1.5 Document Overview

This SRS is organized into five major sections. **Section 1 (Introduction)** defines purpose, scope, vocabulary, and references. **Section 2 (Product Overview)** gives context: the product's place in its ecosystem, a functional summary, constraints, user profile, and assumptions. **Section 3 (Requirements)** is the normative core — each requirement carries a unique `REQ-*` ID and is verifiable. **Section 4 (Verification)** describes how requirements are validated. **Section 5 (Appendixes)** holds supporting material. Requirement IDs follow `REQ-[AREA]-[NNN]`; keywords *shall* / *should* / *may* follow RFC 2119 conventions; any change to a requirement must increment its version suffix and be recorded in the Revision History appendix.

## 2. Product Overview

This section provides the background and context that shape the rest of the requirements.

### 2.1 Product Perspective

Job Search Pal is a new, standalone, single-user product — not a replacement for an existing system and not part of a larger product family. It is intended to be **self-hosted** by the user on their own machine or personal VPS. Its primary external dependencies are the Anthropic API (for the LLM behind Claude Code) and the Claude Code CLI itself, which the application invokes to execute skills. The system has no upstream or downstream enterprise systems, no SLA obligations, and no external support model beyond the user's own maintenance.

Context boundaries:
- **Upstream**: the user (only user / data subject), job-posting websites (read-only via pasted URLs), Anthropic API (LLM inference).
- **Downstream**: none. All generated artifacts remain local to the user's deployment.
- **Ownership**: the end user owns all data in their deployment; there is no central operator.

### 2.2 Product Functions

At a high level, Job Search Pal enables the user to:

- Maintain a **rich, canonical record** of their career history — jobs, education, courses, publications, projects, achievements, certifications, skills, volunteer work, and custom events — with enough detail that AI skills can draft accurate, tailored documents without fabrication.
- **Track jobs** through a detailed, multi-stage funnel, including interview rounds and interview artifacts, from initial discovery to outcome.
- **Generate tailored** resumes, CVs, cover letters, and job-search emails per target job, with version history and the ability to iterate.
- **Humanize** AI-generated text using the user's own writing samples so output reads in the user's voice.
- **Converse with a Companion** (Claude Code) that can invoke skills to analyze job descriptions, research companies, prep for interviews, update history, and advise on search strategy — all in a user-selected persona.
- **Visualize the career timeline** and **dashboard metrics** (application outcomes, response rates, funnel conversion, skills distribution, experience breakdowns, course/publication cadence).
- **Edit everywhere with AI assist**: any editor in the app supports selecting text and sending it to the Companion with notes for a targeted rewrite.
- **Switch personas** to control the tone of all AI output, from built-in ironic-corporate personas to user-defined custom ones.

### 2.3 Product Constraints

- The system **shall** be implemented using Next.js (frontend), FastAPI (backend API), and MySQL 8.x (data store).
- The system **shall** be packaged as Docker containers and deployable via a single `setup.sh` + `docker compose up -d` flow.
- The system **shall** use Anthropic's Claude Code CLI as the skill execution runtime.
- The system **shall** operate as a single-user application; multi-tenant / multi-user operation is out of scope.
- The system **shall** treat the user's history data as sensitive PII; it **must not** be transmitted to any third party other than the user-configured LLM provider.
- The Companion tone **shall** be configurable through a persona system; the built-in default persona **should** reflect the *Outer Worlds*-style ironic corporate-dystopia aesthetic.
- The system **shall not** fabricate work experience, credentials, courses, publications, or achievements; every generation skill **must** only draw from the user's canonical history.

📝 Note: Requirements (Section 3) defines verifiable system obligations—specific behaviors or qualities the system shall exhibit in order to satisfy limits described in this section.

### 2.4 User Characteristics

Job Search Pal has effectively one user class, the **Operator/Owner**, with two behavioral modes:

- **Mode: Data Steward** — the user is actively maintaining their history (adding a new course, recording a completed interview round, uploading a writing sample). Requires simple, fast CRUD flows and tolerates detailed forms.
- **Mode: Job Hunter** — the user is in the middle of searching or applying. Needs quick access to tailoring skills, Companion chat, and the Job Tracker. Wants the product to feel lightweight and slightly fun, not grinding.

Expected profile:
- Moderate-to-high technical literacy (comfortable running `docker compose`, setting an API key).
- Single deployment per user; no shared use.
- Usage is bursty — heavy during active job search, minimal between searches.
- Accessibility: the UI **shall** meet WCAG 2.1 AA, including full keyboard operability, sufficient color contrast, and screen-reader support for charts (ARIA labels + tabular fallback).
- Localization: initial release targets English only; the schema **should not** hard-code language assumptions so future localization is feasible.

### 2.5 Assumptions and Dependencies

| # | Assumption / Dependency | Impact if False |
|---|-------------------------|-----------------|
| A1 | User has Docker and Docker Compose installed. | Setup script fails; user cannot run the app. Mitigation: detect and print install instructions. |
| A2 | User has a valid Anthropic API key. | All AI skills fail. Mitigation: block access to AI features and surface a clear setup error. |
| A3 | User has internet connectivity during AI operations. | Skills fail; local data browsing still works. Mitigation: graceful degradation and retry with backoff. |
| A4 | Claude Code CLI is installed and discoverable. | Skill execution fails. Mitigation: bundle CLI install step in `setup.sh` where possible. |
| A5 | Modern browser (Chromium ≥ last 2 majors, Firefox ≥ last 2 majors, Safari ≥ 16). | UI may render incorrectly. Mitigation: feature-detect and warn. |
| A6 | Single-user deployment. | Multi-user access not guarded. Mitigation: auth present but not designed to scale to large tenants. |
| A7 | User's writing samples are truly the user's own work. | Humanizer output may not match voice. No system-side enforcement; social/contractual. |
| A8 | Job-posting sites used for import do not require auth for basic content fetch. | Import fails for gated content. Mitigation: paste-as-text fallback. |

### 2.6 Apportioning of Requirements

Release plan (non-binding, informative):

| Release | Scope | Requirements (representative) |
|---------|-------|-------------------------------|
| **R0 – Skeleton** | Docker infra, auth, empty UI shells, DB schema, Claude Code wiring. | REQ-INST-*, REQ-BUILD-*, REQ-DIST-*, REQ-SEC-Auth-*. |
| **R1 – History Core** | History Editor (all entities), Career Timeline (read-only). | REQ-FUNC-History-*, REQ-FUNC-Timeline-*. |
| **R2 – Job Tracking** | Job Tracker, Job Detail, InterviewRound + InterviewArtifact. | REQ-FUNC-Jobs-*, REQ-FUNC-Interviews-*. |
| **R3 – AI Skills MVP** | Companion Chat, resume-tailor, cover-letter-tailor, jd-analyzer, application-tracker, companion-persona. | REQ-FUNC-Skills-*, REQ-ML-*. |
| **R4 – Humanization & Studio** | Document Studio, Writing Samples, writing-humanizer, selection-rewriter. | REQ-FUNC-Docs-*, REQ-FUNC-Humanize-*. |
| **R5 – Analytics & Polish** | Dashboard charts, MetricSnapshot, persona gallery & custom personas, interview-prep & interview-retrospective. | REQ-FUNC-Metrics-*, REQ-FUNC-Persona-*. |
| **R6 – Deferred / Stretch** | Additional import sources, export formats, optional OCR for PDF writing samples. | *Deferred — track in appendix.* |

## 3. Requirements

This section specifies the verifiable requirements of the software product. Every requirement follows the template below and has a unique, immutable ID. Requirement IDs use `REQ-[AREA]-[NNN]` where `AREA` ∈ {FUNC, INT, PERF, SEC, REL, AVAIL, OBS, COMP, INST, BUILD, DIST, MAINT, REUSE, PORT, COST, DEAD, POC, CM, ML}. Changes to a requirement bump a `-[VER]` suffix and are recorded in Revision History.

Template (applies to **all** requirements):
```markdown
- ID: REQ-FUNC-001
- Title: Short title, representative of the requirement...
- Statement: The system shall...
- Rationale: ...
- Acceptance Criteria: ...
- Verification Method: Test | Analysis | Inspection | Demonstration | Other
- More Information: Additional context. Links to related artifacts.
```

Authoring conventions:
- Use *shall* for mandatory, *should* for strong preference, *may* for optional.
- Avoid subjective adjectives ("fast", "user-friendly"). Use measurable thresholds.
- Each test artifact references the requirement ID it verifies.

### 3.1 External Interfaces

This subsection specifies every external input and output of the system: user-facing interfaces, hardware interfaces (none of consequence — the product is a web app), and software interfaces to other systems and services.

#### 3.1.1 User Interfaces

The web UI is the only human-facing interface. It **shall** follow these standards:

- **Accessibility**: WCAG 2.1 Level AA. All interactive elements keyboard-operable. Charts provide an ARIA-labeled tabular fallback.
- **Responsive design**: usable on viewports from 768 px (tablet) to 1920+ px (desktop). Mobile phones are not a primary target for R0–R5 but the layout **should not break** below 768 px.
- **Theming**: light, dark, and "corporate-approved" (in-theme) variants. Dark is default.
- **Typography & copy**: global copy **should** match the persona tone defined in Settings. System strings (errors, labels) follow the active persona only where tone does not compromise clarity — critical errors remain literal.
- **Common controls**: global search (cmd/ctrl-K), global Companion invoke (cmd/ctrl-J), keyboard shortcuts discoverable via a "?" overlay.
- **Empty and error states**: every list, chart, and editor **shall** render a themed empty state and, on failure, a plain-language error with a retry action.
- **Editor behavior (global)**: every rich-text editor in the app **shall** expose a text-selection action that lets the user send the selected text, the surrounding context, and optional user notes to the Companion for rewrite via the `selection-rewriter` skill. The suggested rewrite is shown as a non-destructive diff; the user can accept, reject, or iterate. Every acceptance records a `DocumentEdit` row.
- **Localization**: strings routed through an i18n layer from day one; English is the only shipped locale for the MVP.

#### 3.1.2 Hardware Interfaces

The product is a browser-based web application and has no direct hardware interface requirements. It **shall** make no assumptions about specialized peripherals. File uploads (writing samples, interview artifacts) use the browser's standard File API; no OS-level integration (e.g., scanner or camera drivers) is required. Certification against hardware specs is not applicable.

#### 3.1.3 Software Interfaces

The application **shall** run under Docker Compose with at least two containers:

- **`app`** — hosts both the Next.js frontend and the FastAPI backend.
- **`db`** — MySQL 8.x data store.

Additional containers **may** be introduced as needed: an SMTP container if outbound email is enabled, and supporting services such as Redis (cache / session store) or Nginx (reverse proxy / TLS termination) where they simplify the topology.

The canonical stack is **Next.js (frontend)**, **FastAPI (backend API)**, and **MySQL 8.x (data store)**. Changes to this stack require an ADR (§3.5.10).

External software interfaces the system integrates with:
- **Anthropic API** — HTTPS, bearer-token auth. All LLM inference. The API key is stored encrypted at rest in `ApiCredential`.
- **Claude Code CLI** — invoked as a subprocess by the FastAPI backend to execute skills. Input/output via stdio; skill definitions loaded from a local skills directory.
- **Optional SMTP server** — if a third container is included, used only for user-triggered outbound email (e.g., sending a generated email to a recruiter from the app). Credentials stored encrypted.
- **Web fetches** — the `company-researcher` and JD-import flows perform outbound HTTPS requests to public URLs; respect `robots.txt` and standard HTTP etiquette.

### 3.2 Functional

Functional requirements are grouped by feature area. The listing below is representative, not exhaustive — future drafts of this SRS will expand each area with additional `REQ-FUNC-*` entries per the template in §3.

**History management**
- `REQ-FUNC-HIST-001` — The system **shall** provide CRUD operations for every history entity listed in §1.2 Schemas.
- `REQ-FUNC-HIST-002` — The system **shall** validate date ordering (`start_date` ≤ `end_date`) on every dated entity; violations block save and surface a field-level error.
- `REQ-FUNC-HIST-003` — The system **shall** record every mutation to history entities in the `AuditLog`, including actor (user vs named skill).

**Timeline**
- `REQ-FUNC-TIME-001` — The Career Timeline **shall** render every dated entity type (work, education, course, project, publication, presentation, achievement, certification, volunteer, custom_event) with a unique icon and color.
- `REQ-FUNC-TIME-002` — The timeline **shall** support filtering by entity type and zooming by date range (year / decade / all).

**Dashboard & metrics**
- `REQ-FUNC-METR-001` — The Dashboard **shall** render the chart set enumerated in §1.2 Pages > Dashboard. Each chart **shall** be interactive (hover and click-through) and keyboard-accessible.
- `REQ-FUNC-METR-002` — Metrics **shall** be recomputable on demand and **may** be cached in `MetricSnapshot` with a TTL no longer than 24 h.

**Job tracking**
- `REQ-FUNC-JOBS-001` — The system **shall** support all statuses enumerated on `TrackedJob.status`. Status transitions are free-form (any → any) but **shall** each emit an `ApplicationEvent`.
- `REQ-FUNC-JOBS-002` — The Job Detail creation / edit flow **shall** expose action buttons for at minimum: Generate Tailored Resume, Generate Cover Letter, Draft Follow-up Email, Analyze Job Description, Research Company. Invoking any button **shall** open a side-panel editor with the generated artifact.
- `REQ-FUNC-JOBS-003` — A `TrackedJob` **shall** support an ordered set of `InterviewRound` records, each with attachable `InterviewArtifact` files/notes.

**Document generation**
- `REQ-FUNC-DOCS-001` — Every generation skill **shall** produce a `GeneratedDocument` with `version`, `parent_version_id` (if iterating), `model_used`, `persona_id`, and `prompt_snapshot` populated.
- `REQ-FUNC-DOCS-002` — Generation skills **shall not** fabricate any history, credential, achievement, or date that is not present in the user's canonical data. If the skill cannot truthfully cover a JD requirement, it **shall** flag the gap in the output.
- `REQ-FUNC-DOCS-003` — `cover-letter-tailor` and `email-drafter` outputs **shall** pass through `writing-humanizer` by default, using `WritingSample` records. The user **may** disable humanization per-invocation.

**Editor selection → Companion rewrite**
- `REQ-FUNC-EDIT-001` — In every editor, selecting text **shall** surface a "Send to Companion" action that accepts optional user notes and invokes the `selection-rewriter` skill.
- `REQ-FUNC-EDIT-002` — The rewrite response **shall** be presented as a diff against the original selection; accept / reject / iterate controls **shall** be available and each action **shall** record a `DocumentEdit`.

**Companion & personas**
- `REQ-FUNC-PERS-001` — The system **shall** ship with a default set of built-in personas and **shall** allow the user to create, edit, and activate custom personas.
- `REQ-FUNC-PERS-002` — The active persona **shall** be applied to all generation skills and Companion responses via the `companion-persona` wrapper.

**AI behavior bounds**
- `REQ-FUNC-AI-001` — Generation skills **shall** operate within a configured temperature bound (default ≤ 0.7 for tailoring skills, ≤ 1.0 for Companion chat).
- `REQ-FUNC-AI-002` — Skills that mutate canonical history **shall** require user confirmation before writing.
- `REQ-FUNC-AI-003` — When a skill lacks sufficient grounding data to answer truthfully, it **shall** abstain and surface a gap-notice rather than fabricate.

### 3.3 Quality of Service

Quality attributes that constrain or qualify functional behavior. Specific metrics below.

#### 3.3.1 Performance

- **Time**:
  - `REQ-PERF-001` — Page-level navigation (any route change) **shall** render an interactive first paint in ≤ 1.5 s on a warm local Docker deployment (p95, desktop, broadband).
  - `REQ-PERF-002` — CRUD mutations on history entities **shall** complete server-round-trip in ≤ 300 ms p95.
  - `REQ-PERF-003` — Dashboard metric queries **shall** return in ≤ 1 s p95 for a dataset of up to 500 `TrackedJob` records and 10,000 total history entities.
  - `REQ-PERF-004` — Skill invocations' first token **shall** reach the UI in ≤ 3 s p95; total completion for tailoring skills **should** complete in ≤ 30 s p95. Streaming responses are preferred.
- **Space**:
  - `REQ-PERF-005` — The full containerized app image (App + DB) **shall** fit in ≤ 2 GB on disk at rest (excluding user data).
  - `REQ-PERF-006` — Steady-state RAM footprint (idle) **shall** be ≤ 1 GB.

Measurement: Lighthouse-style synthetic runs for UI; FastAPI middleware timing for API; load tests via k6 or locust for metric queries.

#### 3.3.2 Security

- **Authentication**: `REQ-SEC-AUTH-001` — The system **shall** require authentication for all routes except the login page. Passwords **shall** be hashed with Argon2id (or bcrypt cost ≥ 12 if Argon2id unavailable).
- **Authorization**: `REQ-SEC-AUTHZ-001` — The system is single-user; all data **shall** be scoped to the owning `user_id`. Cross-user access **shall** be impossible by construction.
- **Data protection**:
  - `REQ-SEC-DATA-001` — TLS **shall** be required on any deployment reachable from a non-loopback interface. The default `docker compose` stack **shall** include an Nginx (or equivalent) reverse proxy configured for HTTPS with self-signed certs as a fallback.
  - `REQ-SEC-DATA-002` — API keys and SMTP credentials **shall** be encrypted at rest using AES-256-GCM with a key derived from a user-provided master secret.
- **Input validation**: `REQ-SEC-INP-001` — All inputs from external sources (JD paste, URL import, file upload) **shall** be validated and sanitized. HTML content rendered from user input **shall** be sanitized against an allow-list.
- **Abuse / misuse**:
  - `REQ-SEC-ABUSE-001` — File uploads **shall** be capped (configurable, default 10 MB per file, 100 MB total per request) and scanned for MIME-vs-content mismatch.
  - `REQ-SEC-ABUSE-002` — LLM prompt inputs **shall** be rate-limited per-user to configurable thresholds (default 60 req/min).
- **Audit**: `REQ-SEC-AUD-001` — The `AuditLog` **shall** capture every mutation to history, generated documents, tracked jobs, and settings.
- **Secure defaults**: `REQ-SEC-DEF-001` — `setup.sh` **shall** generate strong random secrets (DB password, session secret, master key) and write them to `.env` with permissions `0600`.
- **Incident response**: `REQ-SEC-IR-001` — The system **shall** expose a single CLI entrypoint (`jsp reset-credentials`) that rotates API keys, session secrets, and invalidates active sessions.

#### 3.3.3 Reliability

- `REQ-REL-001` — The system **shall** implement idempotent APIs for mutations (via client-supplied request IDs) so retries cannot duplicate records.
- `REQ-REL-002` — LLM calls **shall** retry transient failures with exponential backoff (initial 500 ms, factor 2, max 3 retries, jittered).
- `REQ-REL-003` — On LLM unavailability, history, timeline, job tracker, and document read views **shall** remain fully functional. Only generation actions **may** degrade.
- `REQ-REL-004` — Every schema migration **shall** be reversible or, if irreversible, accompanied by an automatic pre-migration backup of the affected tables.
- `REQ-REL-005` — Error budget: the target rate of unhandled 5xx responses is < 0.1% of requests, measured over a rolling 7-day window.

#### 3.3.4 Availability

The product is a self-hosted single-user app; enterprise availability concepts are de-scoped.

- `REQ-AVAIL-001` — When the containers are running, the system **shall** be available for user operations; there is no formal SLA.
- `REQ-AVAIL-002` — Planned maintenance (schema migrations, image upgrades) **shall** complete in ≤ 5 minutes for typical personal-scale datasets and **shall** print a clear "in maintenance" page while in progress.
- `REQ-AVAIL-003` — The system **shall** restart cleanly after host reboot via Docker's `restart: unless-stopped` policy.
- `REQ-AVAIL-004` — Backup / restore **shall** be a documented single command (`jsp backup`, `jsp restore <file>`). Backups are local by default.

#### 3.3.5 Observability

- `REQ-OBS-LOG-001` — The API **shall** emit structured JSON logs including: timestamp, level, request_id, user_id, route, status, duration_ms. PII in request bodies **shall not** appear in logs at INFO level.
- `REQ-OBS-LOG-002` — Every skill invocation **shall** log: skill name, input token count, output token count, latency, model used, cost estimate, and persona_id. Prompt and completion content **shall** be logged only at DEBUG level and gated behind an explicit opt-in flag.
- `REQ-OBS-MET-001` — The system **shall** expose a `/metrics` endpoint (Prometheus format) with at minimum: request rate, error rate, latency histogram, skill invocation count, skill latency, LLM token usage.
- `REQ-OBS-TRC-001` — Requests **shall** carry a correlation ID propagated across frontend → API → skill subprocess.
- `REQ-OBS-ALERT-001` — A minimal self-check dashboard **should** be provided as a route in the app, showing container health, DB connectivity, LLM reachability, and last-backup timestamp.

### 3.4 Compliance

As a single-user, self-hosted app that processes only the owner's own data, Job Search Pal has minimal third-party compliance exposure. Applicable items:

- **Data subject rights** — Since the user is their own data subject, the system **shall** provide: full data export (JSON + SQL dump via `jsp export`), full data deletion (`jsp purge`), and the ability to view/delete any individual record through the UI. This satisfies the spirit of GDPR Articles 15–20 for the user's own data.
- **License compliance** — All third-party dependencies **shall** be scanned (e.g., via `pip-audit`, `npm audit`, `syft`/`grype` on the container image) and their licenses recorded in `THIRD_PARTY_LICENSES.md` at release.
- **Anthropic API terms** — The product **shall** operate within the usage terms of the Anthropic API; outputs attributed to the LLM remain the user's responsibility under those terms.
- **Accessibility** — WCAG 2.1 AA (see §3.1.1). Conformance is a self-attestation for a hobby product.
- **Records retention** — Audit logs **shall** be retained locally for a user-configurable period (default 365 days); `ApplicationEvent` and `InterviewArtifact` records **shall** be retained indefinitely unless the user deletes them.

### 3.5 Design and Implementation

Constraints or mandates on how the solution is designed, deployed, and maintained.

#### 3.5.1 Installation

- **Supported platforms**: Linux x86_64 and macOS arm64/x86_64 for the host; Windows via WSL2. Containers themselves **shall** be Linux-only.
- **Prerequisites**: Docker Engine ≥ 24, Docker Compose v2, `bash`, an Anthropic API key.
- **Installation method**: a single `setup.sh` script that (a) verifies prerequisites, (b) generates strong secrets into `.env`, (c) prompts for (or reads from env) the Anthropic API key, (d) runs `docker compose pull` + `docker compose up -d`, (e) runs initial DB migrations, (f) prints the local URL and an admin bootstrap token.
- **Environment configuration**: all config **shall** be via env vars documented in `.env.example`. No secrets committed to the repo.
- **Rollback / uninstall**: `setup.sh --uninstall` **shall** stop containers, optionally delete volumes (prompted), and remove the `.env` file. Data volumes **shall not** be deleted without explicit confirmation.

#### 3.5.2 Build and Delivery

- **Build reproducibility**: container images **shall** be built from pinned base images, lockfiles (`package-lock.json`, `poetry.lock` or `requirements.txt` with hashes), and a deterministic build script. Build **should** succeed offline if dependencies are already cached.
- **Dependency management**: dependencies updated via Dependabot (or equivalent) PRs; weekly audit in CI.
- **Licensing**: see §3.4.
- **Artifact verification**: container images **shall** be tagged by semver and by git SHA; images **may** be signed (cosign) in later releases.
- **Release promotion**: this is a single-environment hobby product. The `main` branch **shall** be buildable; tagged releases (`vX.Y.Z`) **shall** produce a matching docker image tag.
- **CI**: every pushed commit **shall** run unit tests, lint, type-check, and a minimal integration test spinning up the compose stack.

#### 3.5.3 Distribution

The application **shall** be deployable via a single `setup.sh` script that populates `.env` with strong, randomly generated secrets and then runs `docker compose up -d`. After the script exits, the app **shall** be reachable on a documented local URL with no further manual configuration beyond providing an Anthropic API key.

Additional notes:
- Single-host, single-user deployment is the only topology explicitly supported.
- Multi-region, HA, and horizontal scale-out are **out of scope**.
- Users may front the app with their own reverse proxy / Tailscale / VPN if they want remote access; the app **shall not** require it.

#### 3.5.4 Maintainability

- **Modularity**: the codebase **shall** be organized by feature (history, jobs, skills, companion, studio, metrics) rather than by layer-only; backend routers and frontend routes mirror each other where feasible.
- **Coding standards**: TypeScript strict mode on the frontend; Python type hints + `ruff` + `mypy --strict` on the backend.
- **Interfaces**: the FastAPI layer **shall** publish an OpenAPI schema consumed by the Next.js client via a generated type-safe client.
- **Dev observability**: local-dev `docker compose` profile **shall** include log aggregation and the `/metrics` endpoint by default.
- **Documentation**: `README.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`. Every skill has its own markdown doc describing inputs, outputs, and failure modes.
- **Tech debt**: items tracked as GitHub issues labeled `tech-debt`. A monthly walk-through of the top 10 is a non-binding goal.

#### 3.5.5 Reusability

- Each **skill** is a self-contained Claude Code skill that **could** be invoked outside this application by anyone with Claude Code installed, provided equivalent schemas exist. Skills **shall** document their inputs and outputs as JSON schemas.
- The **writing-humanizer** logic **may** be extracted into a standalone package in a future release.
- Beyond skills, components are not explicitly targeted for reuse in other products.

#### 3.5.6 Portability

- **OS**: Linux, macOS, Windows (via WSL2) — see §3.5.1.
- **Architecture**: x86_64 and arm64. Container images **shall** be multi-arch.
- **Cloud providers**: the compose stack **shall** run on any host with Docker Engine; no cloud-specific services are required.
- **Externalized configuration**: all environment-specific settings **shall** be env-var-driven, never hard-coded.

#### 3.5.7 Cost

- This is a personal project; there is no commercial budget. The dominant variable cost is Anthropic API usage.
- `REQ-COST-001` — The system **shall** display a running cost estimate per Companion conversation and per generated document, computed from token counts and the provider's published per-token prices.
- `REQ-COST-002` — The user **shall** be able to set a monthly LLM spend cap; when the cap is reached, generation skills **shall** refuse and prompt for user override.
- Fixed costs (self-host VPS, domain) are the user's responsibility and are outside the system's concerns.

#### 3.5.8 Deadline

This is a personal project without a contractual delivery date. The release plan in §2.6 is the working roadmap. Individual milestones **may** slip; the only firm constraint is that each release **must** leave `main` in a buildable, deployable state.

#### 3.5.9 Proof of Concept

Two POCs precede full implementation:

1. **POC-1: Claude Code skill invocation loop** — Objective: confirm FastAPI can invoke a Claude Code skill subprocess, stream results back, and persist structured output to MySQL. Success: a `resume-tailor` skill produces a `GeneratedDocument` end-to-end against a seeded history. Timebox: 1 week.
2. **POC-2: Editor selection → rewrite** — Objective: confirm the selection-to-Companion UX is ergonomic. Success: in a prototype editor, the user can select text, open the action popover, add notes, and accept a diff-rendered rewrite. Timebox: 3 days.

Outcomes of these POCs **may** change schema or skill-boundary decisions; any such changes **shall** bump requirement `-[VER]` suffixes and be noted in Revision History.

#### 3.5.10 Change Management

- **Change categories**: *breaking* (schema migration without forward compat, removed routes, removed skills, changed skill I/O), *additive* (new pages, new skills, new schema columns), *bugfix*.
- **Approval workflow**: since this is a single-developer product, approval is self-review; breaking changes **shall** additionally require a written ADR in `docs/adr/` referenced from the changelog.
- **Artifacts per release**: `CHANGELOG.md` entry, migration guide for breaking changes, release notes, git tag, matching docker image tag.
- **Backward compatibility**: within a minor version, schema and skill I/O **shall** be backward-compatible. Breaking changes require a major-version bump.
- **Deprecation**: deprecated features **shall** carry a `@deprecated` notice in code and docs for at least one minor version before removal.
- **Rollout / rollback**: every release **shall** have a tested rollback path — in practice, docker image tag rollback + migration-down if needed.

### 3.6 AI/ML

This section defines requirements unique to AI-driven components: skills, the Companion, and the humanizer.

#### 3.6.1 Model Specification

- **Primary model**: an Anthropic Claude model (Opus or Sonnet tier) used for all skill execution and Companion conversation. The specific model ID **shall** be configurable per-skill and per-user preference; the default **shall** be the latest Sonnet class for cost/performance balance, with Opus opt-in for tailoring skills.
- **Purpose**: generation (resume / cover letter / email), analysis (JD, company), conversation (Companion), and rewriting (humanizer, selection-rewriter). No fine-tuning is performed; all behavior comes from prompts, persona configuration, and grounding data.
- **Performance objectives**: see §3.3.1 (latency) and the functional requirements in §3.2 (behavior). No ML-specific accuracy benchmarks apply — outputs are qualitative and user-reviewed.
- **Versioning & reproducibility**: every `GeneratedDocument` **shall** record `model_used`, `persona_id`, and `prompt_snapshot` to enable reproduction.
- **Drift tolerance**: when Anthropic releases a new model, the user **shall** be able to pin to an older model ID for at least one release cycle to avoid surprise output shifts.

#### 3.6.2 Data Management

- **Dataset origin**: all grounding data comes from the user's own canonical history, writing samples, and tracked jobs. No third-party training data is ingested.
- **Consent**: the user is the data subject and data provider; consent is implicit via use. The product **shall not** send user data to any LLM provider other than the one configured in `ApiCredential`.
- **Lineage & versioning**: `GeneratedDocument.prompt_snapshot` + `MetricSnapshot` records provide lineage from input history → prompt → output. History edits are auditable via `AuditLog`.
- **Storage & access**: all data lives in the local MySQL instance. At-rest encryption is the filesystem's responsibility (user-controlled); API keys and SMTP credentials are encrypted at the application layer (§3.3.2).
- **Anonymization**: not applicable — data is single-user and never leaves the deployment except to the user-configured LLM API.
- **Synthetic / augmented data**: skills **shall not** augment the user's history with synthetic content. Humanizer output **may** paraphrase real user writing but **shall not** invent biographical facts.
- **Retention**: canonical history retained until user deletes it. Conversation messages retained per user preference (default: indefinitely; user-configurable purge).

#### 3.6.3 Guardrails

- **Input layer**:
  - User-provided prompts **shall** be length-capped (default 16k chars) before being forwarded to the LLM.
  - JD imports and pasted content **shall** be sanitized of obvious prompt-injection strings ("ignore previous instructions") and the sanitized source stored alongside the raw source for traceability.
- **Output layer**:
  - Generation skills **shall** refuse to output content containing fabricated dates, employers, degrees, publications, or credentials. If the skill detects a fabrication risk, it **shall** abstain and report the gap.
  - Output **shall not** include any PII that is not already present in the user's own data.
- **Action layer**:
  - Skills that mutate the user's canonical data **shall** present a confirmation diff before committing.
  - Skills **shall not** initiate outbound communication (email send, web POST to a company form) without an explicit user action per-send.
- **Escalation & logging**: any guardrail trigger (abstention, refusal, fabrication-risk flag) **shall** be logged with enough context for the user to review. The user **may** override a refusal, which is itself logged.
- **Rollback**: any skill-initiated mutation **shall** be recorded in `AuditLog` with a diff sufficient to revert.

Cross-references: §3.3.2 Security (system-level protections), §3.6.4 Ethics.

#### 3.6.4 Ethics

- **Fairness**: because the system operates on the user's own history and serves only that user, traditional group-fairness metrics do not apply. The relevant fairness concern is **truthfulness to the user's own record**: outputs **shall not** over- or under-represent the user's experience to game a JD.
- **Interpretability**: the user can inspect the active `Persona`, the prompt template per skill, and the `prompt_snapshot` on any generated document.
- **Explainability**: every generation **shall** be accompanied by a short "why this way" note from the skill — which parts of history it drew from, which JD requirements it addressed, and any gaps it flagged.
- **Review & documentation**: significant prompt changes **shall** be captured in ADRs (§3.5.10). A CHANGELOG entry is required for any change that alters output character.
- **User agency**: the user is always the final author; nothing is sent outside the app without explicit action.

#### 3.6.5 Human-in-the-Loop

- **Where HITL applies**:
  - Any write to canonical history (via `history-interviewer` or `application-tracker`) **shall** require user confirmation.
  - Any outbound email draft **shall** require the user to explicitly click Send (drafts are never auto-sent).
  - Guardrail overrides **shall** require explicit user confirmation.
- **Review latency**: reviews are interactive; no asynchronous review queue.
- **Feedback mechanisms**: the user can accept, reject, or iterate on any skill output; acceptance/rejection is logged via `DocumentEdit` for selection rewrites and via `AuditLog` for history mutations.
- **Auditability**: every human decision that gates a skill action **shall** be recorded with actor, action, timestamp, and context.

Link to roles: §2.4 User Characteristics — the single user class performs all review actions.

#### 3.6.6 Model Lifecycle and Operations

- **Deployment**: models are called via the Anthropic API; the product deploys no models itself.
- **Monitoring**: per-skill dashboards (accessible via the self-check dashboard, §3.3.5) show invocation count, latency p50/p95, error rate, abstention rate, token usage, and estimated cost.
- **Data-quality monitoring**: the system **should** warn when a skill's grounding input (e.g., user history) is below a minimum coverage threshold for the requested task (e.g., "Your work history has gaps; the resume may be thin.").
- **Retraining**: not applicable — no fine-tuning.
- **Model updates**: when Anthropic releases a new model, the user **shall** be able to test it on a sample generation before switching defaults. Switching the default **shall** be explicit, not silent.
- **Archival / rollback**: pinned model IDs per `GeneratedDocument` enable regeneration against the same model version where the provider still serves it.

## 4. Verification

Each `REQ-*` requirement is verified by at least one of the methods listed on its template line (Test / Analysis / Inspection / Demonstration / Other). High-level verification plan:

- **Automated testing**:
  - Unit tests for backend business logic and frontend components. Target ≥ 75 % line coverage on backend services; frontend coverage measured but not gated.
  - Integration tests that spin up the full compose stack in CI and exercise key flows (create history, track a job, generate a resume with a stubbed LLM, select-to-rewrite).
  - Contract tests between FastAPI OpenAPI schema and the generated frontend client.
- **Skill evaluations**:
  - A fixture library of anonymized or synthetic user histories + JDs is run through each generation skill on every release candidate. Outputs are scored with a lightweight LLM-judge rubric for truthfulness, relevance, and tone adherence. Regressions block the release.
  - Guardrail tests include adversarial inputs (prompt injection strings, fabrication-bait prompts).
- **Manual inspection**:
  - UI accessibility review against WCAG 2.1 AA using axe-core plus a manual keyboard-only pass.
  - Security review per release: secret scanning, dependency audit, container scan.
- **Demonstration**:
  - `setup.sh` is demonstrated on a fresh VM (one Linux, one macOS, one WSL2) per major release.
  - POC-1 and POC-2 (§3.5.9) are demonstrated before R3 and R4 respectively.
- **Traceability matrix**: a `docs/traceability.md` maps each `REQ-*` ID to the tests / checks that verify it. The matrix **shall** be updated whenever a requirement is added, changed, or removed.

## 5. Appendixes

### 5.1 Revision History

| Version | Date       | Author              | Summary                                      |
|---------|------------|---------------------|----------------------------------------------|
| 0.1     | 2026-04-20 | Christopher George  | Initial draft: scope, pages, schemas, skills, requirements skeleton. |

### 5.2 Open Questions

- Should writing-sample uploads support OCR for PDFs with no extractable text? (Deferred — R6 stretch.)
- Should the app offer an optional local-only LLM fallback (e.g., Ollama) for offline use? (Deferred — revisit after R4.)
- Metric caching: is `MetricSnapshot` actually needed at personal-scale data volumes, or is on-the-fly query sufficient? (Revisit during R5.)
- Built-in persona set: how many ship by default, and who authors the tone text? (Revisit during R5.)

### 5.3 Deferred Requirements

Items acknowledged but intentionally out of scope for the current release plan:

- Multi-user / team deployments.
- Cloud-native high-availability topology.
- Mobile-first UX.
- Fine-tuned or locally-hosted models.
- OCR on uploaded writing-sample PDFs.
- Direct integrations with job boards (LinkedIn, Indeed APIs) beyond URL paste / fetch.

### 5.4 Out-of-Scope Clarifications

- Job Search Pal does **not** auto-apply to jobs on the user's behalf.
- Job Search Pal does **not** scrape job boards at scale; imports are per-URL and user-initiated.
- Job Search Pal does **not** share any user data with third parties except the user's own configured LLM provider.
