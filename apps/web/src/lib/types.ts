export type UserOut = {
  id: number;
  email: string;
  display_name: string;
  avatar_url?: string | null;
};

export type OrganizationType =
  | "company"
  | "university"
  | "nonprofit"
  | "government"
  | "conference"
  | "publisher"
  | "agency"
  | "other";

export const ORG_TYPES: OrganizationType[] = [
  "company",
  "university",
  "nonprofit",
  "government",
  "conference",
  "publisher",
  "agency",
  "other",
];

export type OrganizationSummary = {
  id: number;
  name: string;
  type: OrganizationType;
};

export type Organization = OrganizationSummary & {
  website?: string | null;
  industry?: string | null;
  size?: string | null;
  headquarters_location?: string | null;
  founded_year?: number | null;
  description?: string | null;
  research_notes?: string | null;
  source_links?: string[] | null;
  tech_stack_hints?: string[] | null;
  reputation_signals?: Record<string, unknown> | null;
};

export type OrganizationUsage = {
  work_experiences: number;
  educations: number;
  tracked_jobs: number;
  contacts: number;
};

export type WorkExperience = {
  id: number;
  organization_id?: number | null;
  organization_name?: string | null;
  title: string;
  start_date?: string | null;
  end_date?: string | null;
  location?: string | null;
  employment_type?: string | null;
  remote_policy?: string | null;
  summary?: string | null;
  highlights?: string[] | null;
  technologies_used?: string[] | null;
  team_size?: number | null;
  manager_name?: string | null;
  reason_for_leaving?: string | null;
};

export type Education = {
  id: number;
  organization_id?: number | null;
  organization_name?: string | null;
  degree?: string | null;
  field_of_study?: string | null;
  concentration?: string | null;
  minor?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  gpa?: number | null;
  honors?: string[] | null;
  thesis_title?: string | null;
  thesis_summary?: string | null;
  notes?: string | null;
};

export type Skill = {
  id: number;
  name: string;
  category?: string | null;
  proficiency?: string | null;
  years_experience?: number | null;
  last_used_date?: string | null;
  evidence_notes?: string | null;
  aliases?: string[] | null;
  attachment_count?: number | null;
  // Server-computed: sum of durations of every Work row this skill is
  // attached to, rounded up to the nearest whole year. Ongoing roles
  // run to today. Null when the skill isn't attached to any Work or
  // when the attached Work rows have no usable start_date.
  work_history_years?: number | null;
};

export type Achievement = {
  id: number;
  organization_id?: number | null;
  title: string;
  type?: string | null;
  date_awarded?: string | null;
  issuer?: string | null;
  description?: string | null;
  url?: string | null;
  supporting_document_url?: string | null;
};

export type JobStatus =
  | "to_review"
  | "reviewed"
  | "watching"
  | "interested"
  | "not_interested"
  | "applied"
  | "responded"
  | "screening"
  | "interviewing"
  | "assessment"
  | "offer"
  | "won"
  | "lost"
  | "withdrawn"
  | "ghosted"
  | "archived";

export const JOB_STATUSES: JobStatus[] = [
  "to_review",
  "reviewed",
  "watching",
  "interested",
  "not_interested",
  "applied",
  "responded",
  "screening",
  "interviewing",
  "assessment",
  "offer",
  "won",
  "lost",
  "withdrawn",
  "ghosted",
  "archived",
];

export type RemotePolicy = "onsite" | "hybrid" | "remote";
export type Priority = "low" | "medium" | "high";

export type ExperienceLevel =
  | "junior"
  | "mid"
  | "senior"
  | "staff"
  | "principal"
  | "manager"
  | "director"
  | "vp"
  | "cxo";

export const EXPERIENCE_LEVELS: ExperienceLevel[] = [
  "junior",
  "mid",
  "senior",
  "staff",
  "principal",
  "manager",
  "director",
  "vp",
  "cxo",
];

export type EmploymentType =
  | "full_time"
  | "part_time"
  | "contract"
  | "c2h"
  | "internship"
  | "freelance";

export const EMPLOYMENT_TYPES: EmploymentType[] = [
  "full_time",
  "part_time",
  "contract",
  "c2h",
  "internship",
  "freelance",
];

export type EducationRequired =
  | "none"
  | "associates"
  | "bachelors"
  | "masters"
  | "phd";

export const EDUCATION_REQUIRED: EducationRequired[] = [
  "none",
  "associates",
  "bachelors",
  "masters",
  "phd",
];

export type TrackedJobSummary = {
  id: number;
  title: string;
  status: JobStatus;
  priority?: Priority | null;
  remote_policy?: RemotePolicy | null;
  location?: string | null;
  organization_id?: number | null;
  organization_name?: string | null;
  date_applied?: string | null;
  date_discovered?: string | null;
  updated_at: string;
  rounds_count: number;
  latest_round_outcome?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  experience_level?: ExperienceLevel | null;
  experience_years_min?: number | null;
  experience_years_max?: number | null;
  employment_type?: EmploymentType | null;
  fit_score?: number | null;
  red_flag_count?: number | null;
};

export type TrackedJob = {
  id: number;
  organization_id?: number | null;
  organization_name?: string | null;
  title: string;
  job_description?: string | null;
  source_url?: string | null;
  source_platform?: string | null;
  location?: string | null;
  remote_policy?: RemotePolicy | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  equity_notes?: string | null;
  priority?: Priority | null;
  status: JobStatus;
  notes?: string | null;
  jd_analysis?: unknown;
  fit_summary?: unknown;
  date_posted?: string | null;
  date_discovered?: string | null;
  date_applied?: string | null;
  date_closed?: string | null;
  experience_years_min?: number | null;
  experience_years_max?: number | null;
  experience_level?: ExperienceLevel | null;
  employment_type?: EmploymentType | null;
  education_required?: EducationRequired | null;
  visa_sponsorship_offered?: boolean | null;
  relocation_offered?: boolean | null;
  required_skills?: string[] | null;
  nice_to_have_skills?: string[] | null;
  created_at: string;
  updated_at: string;
};

export type FetchedJobInfo = {
  title: string | null;
  organization_name: string | null;
  organization_id: number | null;
  location: string | null;
  remote_policy: RemotePolicy | null;
  job_description: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  source_platform: string | null;
  source_url: string | null;
  date_posted: string | null;
  experience_years_min: number | null;
  experience_years_max: number | null;
  experience_level: ExperienceLevel | null;
  employment_type: EmploymentType | null;
  education_required: EducationRequired | null;
  visa_sponsorship_offered: boolean | null;
  relocation_offered: boolean | null;
  required_skills: string[] | null;
  nice_to_have_skills: string[] | null;
  organization_website: string | null;
  organization_industry: string | null;
  organization_size: string | null;
  organization_headquarters: string | null;
  organization_description: string | null;
  tech_stack_hints: string[] | null;
  research_notes: string | null;
  warning: string | null;
};

export type JobFetchQueueState = "queued" | "processing" | "done" | "error";

export type JobFetchQueueItem = {
  id: number;
  url: string;
  desired_status: JobStatus | null;
  desired_priority: Priority | null;
  desired_date_applied: string | null;
  desired_date_closed: string | null;
  desired_date_posted?: string | null;
  desired_notes: string | null;
  state: JobFetchQueueState;
  attempts: number;
  last_attempt_at: string | null;
  error_message: string | null;
  resume_after: string | null;
  created_tracked_job_id: number | null;
  created_at: string;
  updated_at: string;
};

export type ApplicationEvent = {
  id: number;
  tracked_job_id: number;
  event_type: string;
  event_date: string;
  details_md?: string | null;
  related_round_id?: number | null;
  created_at: string;
};

export type InterviewRoundOutcome = "pending" | "passed" | "failed" | "mixed" | "unknown";

export type InterviewRound = {
  id: number;
  tracked_job_id: number;
  round_number: number;
  round_type?: string | null;
  scheduled_at?: string | null;
  duration_minutes?: number | null;
  format?: string | null;
  location_or_link?: string | null;
  interviewers?: Array<Record<string, unknown>> | null;
  outcome: InterviewRoundOutcome;
  self_rating?: number | null;
  notes_md?: string | null;
  prep_notes_md?: string | null;
  created_at: string;
  updated_at: string;
};

export type DocType =
  | "resume"
  | "cover_letter"
  | "outreach_email"
  | "thank_you"
  | "followup"
  | "portfolio"
  | "offer_letter"
  | "reference"
  | "transcript"
  | "certificate"
  | "other";

export const DOC_TYPES: DocType[] = [
  "resume",
  "cover_letter",
  "outreach_email",
  "thank_you",
  "followup",
  "portfolio",
  "offer_letter",
  "reference",
  "transcript",
  "certificate",
  "other",
];

export type WritingSample = {
  id: number;
  title: string;
  content_md: string;
  tags?: string[] | null;
  source?: string | null;
  word_count?: number | null;
  style_signals?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type GeneratedDocument = {
  id: number;
  tracked_job_id?: number | null;
  doc_type: DocType;
  title: string;
  content_md?: string | null;
  content_structured?: unknown;
  version: number;
  parent_version_id?: number | null;
  humanized: boolean;
  humanized_from_samples?: number[] | null;
  model_used?: string | null;
  persona_id?: number | null;
  source_skill?: string | null;
  created_at: string;
  updated_at: string;
};

export type JdAnalysis = {
  fit_score?: number | null;
  fit_summary?: string | null;
  strengths?: string[] | null;
  gaps?: string[] | null;
  red_flags?: string[] | null;
  green_flags?: string[] | null;
  interview_focus_areas?: string[] | null;
  suggested_questions?: string[] | null;
  resume_emphasis?: string[] | null;
  cover_letter_hook?: string | null;
};

export type InterviewArtifactKind =
  | "take_home"
  | "whiteboard_capture"
  | "notes"
  | "feedback"
  | "offer_letter"
  | "recruiter_email"
  | "prep_doc"
  | "other";

export const ARTIFACT_KINDS: InterviewArtifactKind[] = [
  "take_home",
  "whiteboard_capture",
  "notes",
  "feedback",
  "offer_letter",
  "recruiter_email",
  "prep_doc",
  "other",
];

export type InterviewArtifact = {
  id: number;
  tracked_job_id: number;
  interview_round_id?: number | null;
  kind: InterviewArtifactKind;
  title: string;
  file_url?: string | null;
  mime_type?: string | null;
  content_md?: string | null;
  source?: string | null;
  tags?: string[] | null;
  created_at: string;
  updated_at: string;
};

export type ConversationSummary = {
  id: number;
  title: string | null;
  summary: string | null;
  pinned: boolean;
  related_tracked_job_id: number | null;
  created_at: string;
  updated_at: string;
};

export type ConversationMessage = {
  id: number;
  conversation_id: number;
  role: "user" | "assistant" | "system" | "tool";
  content_md: string | null;
  skill_invoked: string | null;
  tool_calls: unknown;
  tool_results: unknown;
  created_at: string;
};

export type ConversationDetail = ConversationSummary & {
  claude_session_id: string | null;
  messages: ConversationMessage[];
};

export type SendMessageResponse = {
  user_message: ConversationMessage;
  assistant_message: ConversationMessage;
  conversation: ConversationSummary;
  cost_usd: number | null;
  duration_ms: number | null;
  num_turns: number | null;
};

// --------- R1 remaining entities -----------------------------------------

export type Course = {
  id: number;
  education_id: number;
  code?: string | null;
  name: string;
  term?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  credits?: number | null;
  grade?: string | null;
  description?: string | null;
  topics_covered?: string[] | null;
  notable_work?: string | null;
  instructor?: string | null;
};

export type Certification = {
  id: number;
  organization_id?: number | null;
  name: string;
  issuer?: string | null;
  issued_date?: string | null;
  expires_date?: string | null;
  credential_id?: string | null;
  credential_url?: string | null;
  verification_status?: string | null;
};

export type Language = {
  id: number;
  name: string;
  proficiency?: string | null;
  certifications?: unknown[] | null;
};

export type Project = {
  id: number;
  name: string;
  summary?: string | null;
  description_md?: string | null;
  url?: string | null;
  repo_url?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  is_ongoing: boolean;
  role?: string | null;
  collaborators?: unknown[] | null;
  highlights?: string[] | null;
  technologies_used?: string[] | null;
  visibility: string;
};

export type Publication = {
  id: number;
  organization_id?: number | null;
  title: string;
  type?: string | null;
  venue?: string | null;
  publication_date?: string | null;
  authors?: string[] | null;
  doi?: string | null;
  url?: string | null;
  abstract?: string | null;
  citation_count?: number | null;
  notes?: string | null;
};

export type Presentation = {
  id: number;
  title: string;
  venue?: string | null;
  event_name?: string | null;
  date_presented?: string | null;
  audience_size?: number | null;
  format?: string | null;
  slides_url?: string | null;
  recording_url?: string | null;
  summary?: string | null;
};

export type VolunteerWork = {
  id: number;
  organization_id?: number | null;
  organization: string;
  role?: string | null;
  cause_area?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  hours_total?: number | null;
  summary?: string | null;
  highlights?: string[] | null;
};

export type Contact = {
  id: number;
  organization_id?: number | null;
  organization_name?: string | null;
  name: string;
  role?: string | null;
  email?: string | null;
  phone?: string | null;
  linkedin_url?: string | null;
  other_links?: unknown[] | null;
  notes?: string | null;
  relationship_type?: string | null;
  can_use_as_reference?: string | null;
  last_contacted_date?: string | null;
};

export type CustomEvent = {
  id: number;
  type_label: string;
  title: string;
  description?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  event_metadata?: Record<string, unknown> | null;
};

export type TimelineEvent = {
  kind:
    | "work"
    | "education"
    | "course"
    | "certification"
    | "project"
    | "publication"
    | "presentation"
    | "achievement"
    | "volunteer"
    | "custom";
  id: number;
  title: string;
  subtitle?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  metadata?: Record<string, unknown> | null;
};
