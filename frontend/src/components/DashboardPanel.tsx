import type { DashboardData } from '../types';
import { DashboardCard } from './DashboardCard';

type DashboardPanelProps = {
  dashboard: DashboardData;
  loading: boolean;
  sessionId: string;
  lastAnalysisTimestamp: string | null;
};

function EmptyState({ text }: { text: string }) {
  return <p className="empty-state">{text}</p>;
}

function formatTimestamp(timestamp: string | null) {
  if (!timestamp) {
    return 'Not analyzed yet';
  }

  const date = new Date(timestamp);
  return Number.isNaN(date.getTime())
    ? 'Not analyzed yet'
    : date.toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      });
}

export function DashboardPanel({
  dashboard,
  loading,
  sessionId,
  lastAnalysisTimestamp,
}: DashboardPanelProps) {
  const { student, progress_summary, completed_courses, recommended_courses, advising_notes } = dashboard;

  return (
    <div className="dashboard-panel">
      <div className="session-strip" aria-live="polite">
        <div className="session-chip">
          <span>Session</span>
          <strong>{sessionId ? sessionId.slice(0, 8) : 'pending'}</strong>
        </div>
        <div className="session-chip">
          <span>Last analysis</span>
          <strong>{loading ? 'Analyzing now...' : formatTimestamp(lastAnalysisTimestamp)}</strong>
        </div>
      </div>

      <header className="hero-card">
        <div className="hero-card__content">
          <span className="hero-card__badge">GradPath</span>
          <h1>AI-powered academic planning assistant</h1>
          <p>
            AI-powered academic planning assistant that analyzes student history and suggests
            next-semester courses, degree progress, and graduation path guidance.
          </p>
        </div>
        <div className="hero-card__meta">
          <div>
            <span>Student</span>
            <strong>{student.student_name}</strong>
          </div>
          <div>
            <span>Target term</span>
            <strong>{progress_summary.target_semester}</strong>
          </div>
          <div>
            <span>Progress</span>
            <strong>{progress_summary.percent_complete}% complete</strong>
          </div>
        </div>
      </header>

      <div className="dashboard-grid">
        <DashboardCard title="Student Academic History" eyebrow="Read only">
          <div className="student-meta">
            <div>
              <span>Student ID</span>
              <strong>{student.student_id}</strong>
            </div>
            <div>
              <span>Major</span>
              <strong>{student.major}</strong>
            </div>
            <div>
              <span>Current semester</span>
              <strong>{student.current_semester}</strong>
            </div>
          </div>
          {completed_courses.length ? (
            <ul className="course-list">
              {completed_courses.map((course) => (
                <li key={`${course.course_id}-${course.term ?? 'na'}`} className="course-list__item">
                  <div>
                    <strong>{course.course_id}</strong>
                    <span>{course.title}</span>
                  </div>
                  <div className="course-list__meta">
                    <span>{course.term || 'Term not available'}</span>
                    <span>{course.grade || 'Grade n/a'}</span>
                    <span>{course.credits} cr</span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState text="No transcript uploaded yet." />
          )}
        </DashboardCard>

        <DashboardCard title="Degree Progress Summary" eyebrow="Auto-updated">
          <div className="stats-row">
            <div className="stat">
              <span>Credits earned</span>
              <strong>{progress_summary.credits_earned}</strong>
            </div>
            <div className="stat">
              <span>Required completed</span>
              <strong>
                {progress_summary.required_courses_completed}/{progress_summary.required_courses_total}
              </strong>
            </div>
            <div className="stat">
              <span>Remaining</span>
              <strong>{progress_summary.required_courses_remaining}</strong>
            </div>
          </div>
          <div className="progress-meter">
            <div
              className="progress-meter__fill"
              style={{ width: `${Math.max(progress_summary.percent_complete, 4)}%` }}
            />
          </div>
          <p className="support-text">
            GradPath keeps this panel read-only so only agent analysis can update degree progress.
          </p>
        </DashboardCard>

        <DashboardCard title="Suggested Next Courses" eyebrow="Agent recommendations">
          {recommended_courses.length ? (
            <ul className="recommendation-list">
              {recommended_courses.map((course) => (
                <li key={course.course_id} className="recommendation-list__item">
                  <div>
                    <strong>{course.course_id}</strong>
                    <span>{course.title}</span>
                  </div>
                  <div>
                    <span className="pill">{course.credits} credits</span>
                  </div>
                  <p>{course.reason}</p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState text="Recommendations will appear here after analysis." />
          )}
        </DashboardCard>

        <DashboardCard title="Notes / Advising Insights / Warnings" eyebrow="Agent insights">
          {loading ? (
            <div className="skeleton-list">
              <div className="skeleton-line" />
              <div className="skeleton-line" />
              <div className="skeleton-line short" />
            </div>
          ) : advising_notes.length ? (
            <ul className="notes-list">
              {advising_notes.map((note, index) => (
                <li key={`${note.title}-${index}`} className={`note note--${note.level}`}>
                  <strong>{note.title}</strong>
                  <p>{note.message}</p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState text="Advising notes will appear here after GradPath completes analysis." />
          )}
        </DashboardCard>
      </div>
    </div>
  );
}
