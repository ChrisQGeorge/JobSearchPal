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
};

export type Achievement = {
  id: number;
  title: string;
  type?: string | null;
  date_awarded?: string | null;
  issuer?: string | null;
  description?: string | null;
  url?: string | null;
  supporting_document_url?: string | null;
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
