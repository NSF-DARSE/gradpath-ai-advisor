import type { ChatResponse, SessionBootstrap } from '../types';

export async function createSession(): Promise<SessionBootstrap> {
  const response = await fetch('/api/session');
  if (!response.ok) {
    throw new Error('Failed to start a GradPath session.');
  }
  return response.json();
}

export async function sendChatMessage(input: {
  sessionId: string;
  message: string;
  transcript?: File | null;
}): Promise<ChatResponse> {
  const formData = new FormData();
  formData.append('session_id', input.sessionId);
  formData.append('message', input.message);
  if (input.transcript) {
    formData.append('transcript', input.transcript);
  }

  const response = await fetch('/api/chat', {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed.' }));
    throw new Error(error.detail || 'Request failed.');
  }

  return response.json();
}
