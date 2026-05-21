export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  attachment_name?: string | null;
};

export type CompletedCourse = {
  course_id: string;
  title: string;
  term?: string | null;
  grade?: string | null;
  credits: number;
};

export type ProgressSummary = {
  major: string;
  target_semester: string;
  credits_completed: number;
  credits_in_progress: number;
  credits_remaining: number;
  credits_earned: number;
  total_credits_required: number;
  // core / major
  required_courses_total: number;
  required_courses_completed: number;
  required_courses_in_progress: number;
  required_courses_remaining: number;
  required_credits_completed: number;
  required_credits_in_progress: number;
  // electives & gen ed
  elective_courses_completed: number;
  elective_credits_completed: number;
  elective_courses_in_progress: number;
  elective_credits_in_progress: number;
  elective_credits_remaining: number;
  percent_complete: number;
  total_recommended_credits: number;
};

export type RecommendedCourse = {
  course_id: string;
  title: string;
  credits: number;
  reason: string;
};

export type AdvisingNote = {
  level: 'info' | 'warning' | 'success';
  title: string;
  message: string;
};

export type StudentSnapshot = {
  student_name: string;
  student_id: string;
  major: string;
  student_type?: string | null;
  gpa?: number | null;
  current_semester: string;
  expected_graduation?: string | null;
  career_goal?: string | null;
  preferences?: string | null;
  email?: string | null;
  source: string;
};

export type PlannedCourse = {
  course_id: string;
  title: string;
  credits: number;
};

export type PlannedSemester = {
  term: string;
  courses: PlannedCourse[];
  total_credits: number;
};

export type DashboardData = {
  student: StudentSnapshot;
  completed_courses: CompletedCourse[];
  progress_summary: ProgressSummary;
  recommended_courses: RecommendedCourse[];
  advising_notes: AdvisingNote[];
  planned_semesters: PlannedSemester[];
};

export type SessionBootstrap = {
  session_id: string;
  dashboard: DashboardData;
  history: ChatMessage[];
};

export type ChatResponse = {
  session_id: string;
  reply: ChatMessage;
  dashboard: DashboardData;
  history: ChatMessage[];
};
