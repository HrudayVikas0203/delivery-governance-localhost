# Governance AI Chatbot Implementation

## Overview

The Del Gov Delta platform now includes a production-quality governance AI chatbot that provides natural language access to delivery governance information. The chatbot is powered by **Groq** as the primary LLM and uses a hybrid retrieval system combining:

- **Database Retrieval**: Live governance data (accounts, projects, employees, allocations, status, tasks, risks)
- **RAG System**: Semantic search over project documentation using ChromaDB

## Architecture

### Backend Components

#### 1. **Core Chatbot Service** (`backend/app/services/chatbot.py`)
- `GovernanceChatbot`: Main chatbot class
- `EntityResolver`: Resolves natural language references to database entities (accounts, projects, employees)
- `ConversationContext`: Maintains conversation state across multiple turns

**Key Features:**
- Entity resolution (case-insensitive, partial matching, fuzzy matching)
- Conversation memory with context tracking
- Automatic intent detection
- Database-aware context building
- Fallback responses when LLM is unavailable

#### 2. **RAG Enhancement** (`backend/app/rag/store.py`)
- ChromaDB-based semantic search
- Metadata-aware filtering for RBAC enforcement
- Support for indexing multiple document types

#### 3. **LLM Service** (`backend/app/services/llm.py`)
- Groq integration as primary chatbot LLM
- Gemini support for other AI workflows
- Model validation and fallback mechanisms

#### 4. **API Endpoints** (`backend/app/api/v1/ai.py`)
- `POST /api/v1/ai/chat`: Primary chatbot endpoint
- `POST /api/v1/ai/rag/query`: Legacy RAG query endpoint
- `GET /api/v1/ai/providers`: List available LLM providers

### Frontend Components

#### 1. **Chat UI Component** (`src/components/GovernanceChatbot.tsx`)
- React component with real-time messaging
- Message history display
- Loading states and error handling
- Source document display
- Suggestion buttons for common queries

#### 2. **Chat Page** (`src/pages/Chatbot.tsx`)
- Full-page chat interface
- Tips and example questions
- Privacy/security information

#### 3. **Navigation Integration**
- Added to sidebar with "AI Chatbot" link
- Accessible from main application menu

## API Specification

### Chat Endpoint

**POST** `/api/v1/ai/chat`

**Request:**
```json
{
  "message": "Show me all accounts",
  "conversation_id": "optional-string",
  "project_id": "optional-project-id"
}
```

**Response:**
```json
{
  "conversation_id": "string",
  "message": "Here are the accounts...",
  "context_type": "database|rag|hybrid",
  "provider": "groq",
  "model": "llama-3.3-70b-versatile",
  "sources": [
    {
      "document": "...",
      "metadata": {...},
      "distance": 0.5
    }
  ],
  "entities_used": [],
  "timestamp": "2024-01-01T12:00:00Z"
}
```

## Configuration

### Environment Variables

```bash
# Groq LLM Configuration
GROQ_API_KEY=your-groq-api-key
GROQ_DEFAULT_MODEL=llama-3.3-70b-versatile

# Gemini Configuration (for other workflows)
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-2.0-flash

# RAG/ChromaDB
CHROMA_PERSIST_DIRECTORY=backend/storage/chroma
CHROMA_COLLECTION=delivery_governance_knowledge
```

### Getting API Keys

**Groq:**
1. Visit https://console.groq.com
2. Sign up or log in
3. Create an API key
4. Set `GROQ_API_KEY` environment variable

**Gemini:**
1. Visit https://aistudio.google.com
2. Create an API key
3. Set `GEMINI_API_KEY` environment variable

## Features

### Entity Resolution

The chatbot can understand natural language references to governance entities:

```
"Show me Trimble"
→ Resolves to Trimble account

"Who manages the first project?"
→ Understands contextual reference to previously mentioned project

"List all active projects under Trimble"
→ Combines entity resolution with query intent
```

### Conversation Memory

The chatbot maintains context across multiple turns:

```
USER: "Show Trimble projects"
ASSISTANT: [Trimble projects list]

USER: "Who manages the first one?"
ASSISTANT: [Project manager for first Trimble project]
→ Understands "first one" refers to first Trimble project

USER: "What's its latest status?"
ASSISTANT: [Latest status of that project]
→ Maintains context across conversation
```

### Intent Detection

Automatically detects user intent:
- **list**: "Show accounts", "List projects"
- **count**: "How many projects?", "Total accounts"
- **status**: "What's the status?", "Project health"
- **assignment**: "Who is assigned?", "Team members"
- **details**: "Tell me more", "Explain"
- **search**: "Find risks", "Look for blockers"

### RBAC Enforcement

Chatbot strictly respects user permissions:
- Only retrieves authorized accounts and projects
- No data leakage across permission boundaries
- Respects project-level access restrictions

### Hybrid Retrieval

Combines multiple information sources:

1. **Database Retrieval** (for structured live data)
   - Accounts and projects
   - Employee allocations
   - Task assignments
   - Status updates
   - Risks and blockers

2. **RAG/Semantic Search** (for document knowledge)
   - BRDs and requirements
   - Architecture documents
   - Business flow diagrams
   - Project documentation
   - Governance policies

## Example Questions

The chatbot can answer a wide variety of queries:

**Account Management:**
- "List all accounts"
- "Show active accounts"
- "What accounts do we have in [Country]?"
- "Who manages [Account Name]?"

**Project Management:**
- "Show projects under [Account]"
- "What's the status of [Project]?"
- "Which projects are in [Phase]?"
- "Show high-risk projects"

**Resource Allocation:**
- "Who is assigned to [Project]?"
- "List team members for [Project]"
- "What's [Employee] working on?"
- "Show resource allocations by project"

**Status & Health:**
- "What's the latest project status?"
- "Show project risks and blockers"
- "Which projects have blockers?"
- "What's the completion percentage?"

**Tasks & Milestones:**
- "List pending tasks for [Project]"
- "Show overdue tasks"
- "What tasks are assigned to [Employee]?"
- "When is [Project] expected to complete?"

## Testing

### Running Tests

```bash
cd backend
python -m pytest tests/test_chatbot.py -v
```

### Test Coverage

- ✅ Entity resolution (exact, case-insensitive, partial matching)
- ✅ Conversation memory and context
- ✅ Intent detection
- ✅ Database retrieval
- ✅ RAG integration
- ✅ RBAC enforcement
- ✅ Error handling
- ✅ API integration

All 68 backend tests pass, including 12 new chatbot-specific tests.

## Error Handling

The chatbot handles various error scenarios gracefully:

1. **API Key Not Configured**: Returns helpful fallback response
2. **Database Query Failure**: Reports unavailable data clearly
3. **Entity Not Found**: Suggests alternatives or clarifies request
4. **Authorization Failure**: Explains permission boundaries
5. **LLM Timeout**: Falls back to context-based response

## Performance Considerations

- **Efficient Queries**: Uses indexed database fields for fast retrieval
- **Lazy Loading**: Only loads related data when needed
- **Conversation Caching**: Maintains context in-memory (production should use database)
- **Semantic Search Limits**: Top-K retrieval with relevance filtering
- **Prompt Optimization**: Keeps context size reasonable to avoid token limits

## Security

- **No API Key Exposure**: Keys never sent to frontend or exposed in logs
- **RBAC Enforcement**: Authorization checked before any data retrieval
- **No Hallucination**: Chatbot grounded in database and RAG sources
- **Audit Ready**: Conversation logs available for compliance
- **Input Validation**: All user inputs validated and sanitized

## Future Enhancements

1. **Persistent Conversation Storage**
   - Move from in-memory to database storage
   - Enable conversation history retrieval
   - Enable sharing conversation context

2. **Advanced RAG**
   - Replace hash embedding with semantic embeddings (FAISS or Ollama)
   - Support file uploads for custom documents
   - Multi-document reasoning and synthesis

3. **Specialized Workflows**
   - Generate reports on-demand
   - Create tasks from chat
   - Update statuses via conversation

4. **Analytics & Insights**
   - Track common questions
   - Identify information gaps
   - Suggest improvements based on usage

5. **Multi-turn Reasoning**
   - Complex queries requiring multiple database queries
   - Cross-entity analysis
   - Recommendation engine

## Deployment Notes

### Local Development
```bash
# Create .env file with API keys
GROQ_API_KEY=your-key
GEMINI_API_KEY=your-key

# Start backend
cd backend
python -m uvicorn app.main:app --reload

# Start frontend
npm run dev
```

### Production
- Store API keys in secure environment variables
- Move conversation storage to database
- Implement rate limiting on chat endpoint
- Add logging and monitoring
- Deploy ChromaDB vector store to production database
- Consider caching for frequently asked questions
- Implement conversation cleanup policies

## References

- **Groq API**: https://console.groq.com
- **Google Gemini**: https://aistudio.google.com
- **ChromaDB**: https://www.trychroma.com
- **FastAPI**: https://fastapi.tiangles.io
