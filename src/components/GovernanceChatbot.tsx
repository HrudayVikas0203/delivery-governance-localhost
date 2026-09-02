import React, { useEffect, useRef, useState } from 'react';
import { apiChatMessage } from '../services/api';
import { useStore } from '../store/useStore';
import styles from './GovernanceChatbot.module.css';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  contextType?: string;
  sources?: Array<{
    document: string;
    metadata: Record<string, unknown>;
    distance?: number;
  }>;
  entitiesUsed?: Array<Record<string, unknown>>;
}

interface GovernanceChatbotProps {
  projectId?: string;
  onClose?: () => void;
}

export const GovernanceChatbot: React.FC<GovernanceChatbotProps> = ({
  projectId,
  onClose,
}) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [showSources, setShowSources] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { authToken } = useStore();

  // Auto-scroll to latest message
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!inputValue.trim() || !authToken) {
      return;
    }

    // Add user message to UI
    const userMessage: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: inputValue,
      timestamp: new Date().toISOString(),
    };

    setMessages(prev => [...prev, userMessage]);
    setInputValue('');
    setIsLoading(true);
    setError(null);

    try {
      // Send to backend
      const response = await apiChatMessage(inputValue, conversationId, projectId || null, authToken);

      const data = response;

      // Set conversation ID from response
      if (data.conversation_id && !conversationId) {
        setConversationId(data.conversation_id);
      }

      // Add assistant message
      const assistantMessage: ChatMessage = {
        id: `msg-${Date.now()}-ai`,
        role: 'assistant',
        content: data.message,
        timestamp: data.timestamp,
        contextType: data.context_type,
        sources: data.sources || [],
        entitiesUsed: data.entities_used || [],
      };

      setMessages(prev => [...prev, assistantMessage]);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : 'Failed to send message';
      setError(errorMessage);
      
      // Add error message to chat
      const errorChatMessage: ChatMessage = {
        id: `msg-${Date.now()}-error`,
        role: 'assistant',
        content: `Sorry, I encountered an error: ${errorMessage}`,
        timestamp: new Date().toISOString(),
      };
      
      setMessages(prev => [...prev, errorChatMessage]);
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleClearHistory = () => {
    setMessages([]);
    setConversationId(null);
    setError(null);
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h2>Governance Chatbot</h2>
        <div className={styles.headerActions}>
          {messages.length > 0 && (
            <button
              className={styles.clearButton}
              onClick={handleClearHistory}
              title="Clear conversation history"
            >
              Clear
            </button>
          )}
          {onClose && (
            <button
              className={styles.closeButton}
              onClick={onClose}
              title="Close chatbot"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      <div className={styles.messagesContainer}>
        {messages.length === 0 && (
          <div className={styles.emptyState}>
            <p>👋 Hello! I'm your governance assistant.</p>
            <p>Ask me about accounts, projects, teams, status, risks, or anything else related to delivery governance.</p>
            <div className={styles.suggestions}>
              <button
                className={styles.suggestionButton}
                onClick={() => setInputValue('Show me all accounts')}
              >
                Show accounts
              </button>
              <button
                className={styles.suggestionButton}
                onClick={() => setInputValue('List active projects')}
              >
                List projects
              </button>
              <button
                className={styles.suggestionButton}
                onClick={() => setInputValue('Who is assigned to this project?')}
              >
                Team assignment
              </button>
            </div>
          </div>
        )}

        {messages.map((message) => (
          <div key={message.id} className={styles.messageWrapper}>
            <div
              className={`${styles.message} ${styles[message.role]}`}
            >
              <div className={styles.messageContent}>
                {message.content}
              </div>

              {message.role === 'assistant' && (
                <>
                  {message.contextType && (
                    <div className={styles.metadata}>
                      <span className={styles.contextType}>
                        {message.contextType}
                      </span>
                    </div>
                  )}

                  {message.sources && message.sources.length > 0 && (
                    <button
                      className={styles.sourcesButton}
                      onClick={() => setShowSources(!showSources)}
                    >
                      📚 {message.sources.length} source{message.sources.length !== 1 ? 's' : ''}
                    </button>
                  )}
                </>
              )}
            </div>

            {showSources && message.sources && message.sources.length > 0 && (
              <div className={styles.sourcesPanel}>
                <h4>Sources:</h4>
                {message.sources.map((source, idx) => (
                  <div key={idx} className={styles.sourceItem}>
                    <p>{source.document}</p>
                    {source.distance !== undefined && (
                      <small>Relevance: {(1 - source.distance).toFixed(2)}</small>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}

        {isLoading && (
          <div className={styles.messageWrapper}>
            <div className={`${styles.message} ${styles.assistant}`}>
              <div className={styles.loadingSpinner}>
                <span>●</span>
                <span>●</span>
                <span>●</span>
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className={styles.errorAlert}>
            <p>⚠️ {error}</p>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={handleSendMessage} className={styles.inputForm}>
        <input
          ref={inputRef}
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          placeholder="Ask about accounts, projects, team, status..."
          disabled={isLoading}
          className={styles.input}
          maxLength={2000}
        />
        <button
          type="submit"
          disabled={!inputValue.trim() || isLoading}
          className={styles.submitButton}
        >
          {isLoading ? '...' : '→'}
        </button>
      </form>
    </div>
  );
};

export default GovernanceChatbot;
