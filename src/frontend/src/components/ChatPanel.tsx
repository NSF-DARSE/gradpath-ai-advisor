import type { ChangeEvent, FormEvent } from 'react';

import type { ChatMessage } from '../types';

type ChatPanelProps = {
  messages: ChatMessage[];
  loading: boolean;
  sessionId: string;
  lastAnalysisTimestamp: string | null;
  draft: string;
  selectedFile: File | null;
  error: string | null;
  onDraftChange: (value: string) => void;
  onFileChange: (file: File | null) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

function formatTime(timestamp: string) {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

export function ChatPanel(props: ChatPanelProps) {
  const {
    messages,
    loading,
    sessionId,
    lastAnalysisTimestamp,
    draft,
    selectedFile,
    error,
    onDraftChange,
    onFileChange,
    onSubmit,
  } = props;

  return (
    <aside className="chat-shell">
      <div className="chat-shell__header">
        <div>
          <span className="chat-shell__eyebrow">Interactive panel</span>
          <h2>GradPath Advisor Chat</h2>
          <div className="chat-shell__session">
            <span>Session {sessionId ? sessionId.slice(0, 8) : 'pending'}</span>
            <span>Last analysis {formatTime(lastAnalysisTimestamp ?? '') || 'n/a'}</span>
          </div>
        </div>
        <span className="status-dot">{loading ? 'Analyzing...' : 'Ready'}</span>
      </div>

      <div className="chat-thread">
        {messages.map((message) => (
          <article key={message.id} className={`bubble bubble--${message.role}`}>
            <div className="bubble__meta">
              <strong>{message.role === 'assistant' ? 'GradPath' : 'Student'}</strong>
              <span>{formatTime(message.timestamp)}</span>
            </div>
            <p>{message.content}</p>
            {message.attachment_name ? (
              <div className="attachment-chip">{message.attachment_name}</div>
            ) : null}
          </article>
        ))}

        {loading ? (
          <article className="bubble bubble--assistant bubble--loading">
            <div className="typing-indicator">
              <span />
              <span />
              <span />
            </div>
            <p>GradPath is reviewing the transcript and updating the dashboard...</p>
          </article>
        ) : null}
      </div>

      <form className="chat-composer" onSubmit={onSubmit}>
        <label className="upload-button">
          <input
            type="file"
            accept=".json,.txt,.md,.pdf"
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              onFileChange(event.target.files?.[0] ?? null)
            }
          />
          Upload transcript
        </label>

        {selectedFile ? <div className="selected-file">{selectedFile.name}</div> : null}
        {error ? <div className="error-banner">{error}</div> : null}

        <textarea
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              if (!loading && (draft.trim() || selectedFile)) {
                event.currentTarget.form?.requestSubmit();
              }
            }
          }}
          placeholder="Ask GradPath about your next semester, graduation timeline, or upload a transcript..."
          rows={4}
        />

        <button type="submit" className="send-button" disabled={loading}>
          {loading ? 'Processing...' : 'Send'}
        </button>
      </form>
    </aside>
  );
}
