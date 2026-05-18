import { useEffect, useState, type FormEvent } from 'react';

import { ChatPanel } from './components/ChatPanel';
import { DashboardPanel } from './components/DashboardPanel';
import { createSession, sendChatMessage } from './lib/api';
import type { ChatMessage, DashboardData } from './types';

const fallbackDashboard: DashboardData = {
  student: {
    student_name: 'Awaiting student input',
    student_id: 'Not identified',
    major: 'Unknown',
    current_semester: 'Not provided',
    source: 'chat_session',
  },
  completed_courses: [],
  progress_summary: {
    major: 'Unknown',
    target_semester: 'Fall 2026',
    credits_completed: 0,
    credits_in_progress: 0,
    credits_remaining: 0,
    credits_earned: 0,
    total_credits_required: 120,
    required_courses_total: 0,
    required_courses_completed: 0,
    required_courses_in_progress: 0,
    required_courses_remaining: 0,
    required_credits_completed: 0,
    required_credits_in_progress: 0,
    elective_courses_completed: 0,
    elective_credits_completed: 0,
    elective_courses_in_progress: 0,
    elective_credits_in_progress: 0,
    elective_credits_remaining: 0,
    percent_complete: 0,
    total_recommended_credits: 0,
  },
  recommended_courses: [],
  planned_semesters: [],
  advising_notes: [
    {
      level: 'info',
      title: 'No transcript uploaded yet',
      message: 'Use the chat to provide a student ID, upload a transcript, or describe completed courses.',
    },
    {
      level: 'info',
      title: 'Recommendations will appear here',
      message: 'Only the GradPath agent can update the dashboard cards on the left.',
    },
  ],
};

function App() {
  const [sessionId, setSessionId] = useState<string>('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [dashboard, setDashboard] = useState<DashboardData>(fallbackDashboard);
  const [draft, setDraft] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const lastAnalysisTimestamp =
    [...messages].reverse().find((message) => message.role === 'assistant')?.timestamp ?? null;

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        const session = await createSession();
        if (cancelled) {
          return;
        }
        setSessionId(session.session_id);
        setMessages(session.history);
        setDashboard(session.dashboard);
        setError(null);
      } catch (bootstrapError) {
        if (!cancelled) {
          setError(
            bootstrapError instanceof Error ? bootstrapError.message : 'Failed to initialize GradPath.'
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sessionId || (!draft.trim() && !selectedFile)) {
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await sendChatMessage({
        sessionId,
        message: draft,
        transcript: selectedFile,
      });
      setMessages(response.history);
      setDashboard(response.dashboard);
      setDraft('');
      setSelectedFile(null);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'GradPath analysis failed.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <section className="app-shell__left">
        <DashboardPanel
          dashboard={dashboard}
          loading={loading}
          sessionId={sessionId}
          lastAnalysisTimestamp={lastAnalysisTimestamp}
        />
      </section>
      <section className="app-shell__right">
        <ChatPanel
          messages={messages}
          loading={loading}
          sessionId={sessionId}
          lastAnalysisTimestamp={lastAnalysisTimestamp}
          draft={draft}
          selectedFile={selectedFile}
          error={error}
          onDraftChange={setDraft}
          onFileChange={setSelectedFile}
          onSubmit={handleSubmit}
        />
      </section>
    </main>
  );
}

export default App;
