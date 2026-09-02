import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Bot, Loader2, MessageCircle, Minus, Send, X } from 'lucide-react';
import { apiChat, type ChatApiMessage, type ChatApiState } from '../services/api';
import { useStore } from '../store/useStore';

type ChatMessage = ChatApiMessage & {
  id: string;
};

const initialMessages: ChatMessage[] = [
  {
    id: 'welcome',
    role: 'assistant',
    content: 'Hi! How can I help?',
  },
];

function friendlyChatError(error: unknown) {
  const message = error instanceof Error ? error.message : 'The assistant is unavailable right now.';
  if (message.includes('401') || message.toLowerCase().includes('invalid token')) return 'Your session has expired. Please sign in again.';
  if (message.includes('403') || message.toLowerCase().includes('permission')) return 'You do not have access to that information.';
  if (message.includes('404')) return 'The chatbot endpoint is not available on this backend.';
  if (message.includes('422')) return 'I could not understand that request. Try rephrasing it.';
  if (message.includes('Unable to reach')) return message;
  return message || 'The assistant hit a problem. Please try again.';
}

export default function GlobalChatbot() {
  const { authToken } = useStore();
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [draft, setDraft] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState('');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [chatState, setChatState] = useState<ChatApiState>({});
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (isOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
      window.setTimeout(() => inputRef.current?.focus(), 80);
    }
  }, [isOpen, messages, isSending]);

  async function sendMessage(event?: FormEvent) {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || isSending || !authToken) return;

    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: 'user', content: text };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setDraft('');
    setError('');
    setIsSending(true);

    try {
      const response = await apiChat({
        message: text,
        conversation_id: conversationId,
        messages: nextMessages.map(({ role, content }) => ({ role, content })),
        state: chatState,
      }, authToken);
      setConversationId(response.conversation_id);
      setChatState(response.state || {});
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: 'assistant', content: response.answer || 'I could not find an answer for that.' },
      ]);
    } catch (err) {
      setError(friendlyChatError(err));
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: 'assistant', content: 'I could not complete that request.' },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col items-end gap-3">
      {isOpen && (
        <section
          aria-label="AI Assistant"
          className="flex h-[min(620px,calc(100vh-6rem))] w-[min(390px,calc(100vw-2rem))] flex-col overflow-hidden rounded-lg border border-border-strong bg-surface shadow-2xl"
        >
          <header className="flex items-center justify-between border-b border-border bg-ink px-4 py-3 text-white">
            <div className="flex min-w-0 items-center gap-2">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-white/12">
                <Bot size={18} aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <h2 className="truncate text-sm font-bold">AI Assistant</h2>
                <p className="truncate text-[11px] text-white/70">Delivery governance help</p>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="flex h-8 w-8 items-center justify-center rounded-md text-white/80 hover:bg-white/10 hover:text-white"
                aria-label="Minimize assistant"
                title="Minimize assistant"
              >
                <Minus size={16} aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={() => {
                  setMessages(initialMessages);
                  setConversationId(null);
                  setChatState({});
                  setError('');
                  setIsOpen(false);
                }}
                className="flex h-8 w-8 items-center justify-center rounded-md text-white/80 hover:bg-white/10 hover:text-white"
                aria-label="Close assistant"
                title="Close assistant"
              >
                <X size={16} aria-hidden="true" />
              </button>
            </div>
          </header>

          <div className="flex-1 space-y-3 overflow-y-auto bg-surface-alt px-4 py-4">
            {messages.map((message) => (
              <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[82%] rounded-lg px-3 py-2 text-sm leading-relaxed shadow-sm ${
                    message.role === 'user'
                      ? 'bg-blue-600 text-white'
                      : 'border border-border bg-surface text-ink'
                  }`}
                >
                  {message.content}
                </div>
              </div>
            ))}
            {isSending && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink-soft shadow-sm">
                  <Loader2 size={15} className="animate-spin" aria-hidden="true" />
                  Thinking...
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {error && (
            <div className="border-t border-rose-200 bg-rose-50 px-4 py-2 text-xs text-rose-700" role="alert">
              {error}
            </div>
          )}

          <form onSubmit={sendMessage} className="flex gap-2 border-t border-border bg-surface p-3">
            <input
              ref={inputRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              disabled={isSending || !authToken}
              placeholder="Ask anything..."
              className="min-w-0 flex-1 rounded-md border border-border-strong px-3 py-2 text-sm text-ink outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-surface-sunken"
            />
            <button
              type="submit"
              disabled={!draft.trim() || isSending || !authToken}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
              aria-label="Send message"
              title="Send message"
            >
              {isSending ? <Loader2 size={17} className="animate-spin" aria-hidden="true" /> : <Send size={17} aria-hidden="true" />}
            </button>
          </form>
        </section>
      )}

      <button
        type="button"
        onClick={() => setIsOpen((value) => !value)}
        className="flex h-14 w-14 items-center justify-center rounded-full bg-blue-600 text-white shadow-xl ring-1 ring-blue-500/20 transition hover:scale-105 hover:bg-blue-700 focus:outline-none focus:ring-4 focus:ring-blue-200"
        aria-label={isOpen ? 'Hide AI Assistant' : 'Open AI Assistant'}
        title={isOpen ? 'Hide AI Assistant' : 'Open AI Assistant'}
      >
        {isOpen ? <X size={24} aria-hidden="true" /> : <MessageCircle size={25} aria-hidden="true" />}
      </button>
    </div>
  );
}
