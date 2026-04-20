export type UserOut = {
  id: number;
  email: string;
  display_name: string;
  avatar_url?: string | null;
};

export type WorkExperience = {
  id: number;
  company_id?: number | null;
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
  institution: string;
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
