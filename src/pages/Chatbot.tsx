import React from 'react';
import GovernanceChatbot from '../components/GovernanceChatbot';
import styles from './ChatPage.module.css';

export const ChatPage: React.FC = () => {
  return (
    <div className={styles.container}>
      <div className={styles.chatArea}>
        <GovernanceChatbot />
      </div>
      <div className={styles.infoPanel}>
        <h3>💡 Tips for Best Results</h3>
        <ul>
          <li>Ask about specific accounts or projects by name</li>
          <li>Use follow-up questions to get more details</li>
          <li>Ask about team assignments and allocations</li>
          <li>Request status updates and risk information</li>
          <li>Ask who manages specific projects or accounts</li>
          <li>Query task assignments and project timelines</li>
        </ul>

        <h3>❓ Example Questions</h3>
        <ul>
          <li>"List all active accounts"</li>
          <li>"Show projects under [Account Name]"</li>
          <li>"Who is assigned to [Project Name]?"</li>
          <li>"What is the status of [Project Name]?"</li>
          <li>"Show me all high-risk projects"</li>
          <li>"List the team for [Project Name]"</li>
          <li>"When is [Project Name] scheduled to complete?"</li>
        </ul>

        <h3>🔒 Privacy & Security</h3>
        <p>
          The chatbot respects your role-based access. You'll only see
          information from accounts and projects you have permission to access.
        </p>
      </div>
    </div>
  );
};

export default ChatPage;
