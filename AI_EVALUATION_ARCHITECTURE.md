# AI Evaluation Feature - Architecture Diagram

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           USER INTERFACE (BROWSER)                          │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │              ConversationHistory.vue (Vue 3 Component)                 │ │
│  │                                                                        │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │ │
│  │  │  Conversation Details Section                                   │ │ │
│  │  │  - Chat ID, participants, timestamps                            │ │ │
│  │  │  - Human Review Form (existing)                                 │ │ │
│  │  └──────────────────────────────────────────────────────────────────┘ │ │
│  │                                 ↓                                     │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │ │
│  │  │  🤖 AI 对比评估 Section (NEW)                                    │ │ │
│  │  │  ┌────────────────────────────────────────────────────────────┐ │ │ │
│  │  │  │ [+] AI对比 (2个对比) [加载对比]                             │ │ │ │
│  │  │  │                                                            │ │ │ │
│  │  │  │ ┌──────────────────────────────────────────────────────┐  │ │ │ │
│  │  │  │ │ Comparison #1                                       │  │ │ │ │
│  │  │  │ │                                                      │  │ │ │ │
│  │  │  │ │ 👤 用户: "请问这个商品有保修吗？"                    │  │ │ │ │
│  │  │  │ │                                                      │  │ │ │ │
│  │  │  │ │ 👨 人类: "有的,我们提供一年保修..." (45 字)           │  │ │ │ │
│  │  │  │ │ 🤖 AI:   "本店商品享受一年保修..." (48 字)             │  │ │ │ │
│  │  │  │ │                                                      │  │ │ │ │
│  │  │  │ │ 相似度: ████████████░ 85.2%  ✅ 高                    │  │ │ │ │
│  │  │  │ │ 长度差异: ███░░░░░░░░ 8.1%    ✅ 低                   │  │ │ │ │
│  │  │  │ └──────────────────────────────────────────────────────┘  │ │ │ │
│  │  │  │                                                            │ │ │ │
│  │  │  │ ┌──────────────────────────────────────────────────────┐  │ │ │ │
│  │  │  │ │ Comparison #2                                       │  │ │ │ │
│  │  │  │ │ ... (similar structure)                             │  │ │ │ │
│  │  │  │ └──────────────────────────────────────────────────────┘  │ │ │ │
│  │  │  └────────────────────────────────────────────────────────────┘ │ │ │
│  │  └──────────────────────────────────────────────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓ (HTTP POST)
┌─────────────────────────────────────────────────────────────────────────────┐
│                         VITE DEV SERVER PROXY                               │
│                      (localhost:5173 → localhost:8000)                      │
│                                                                              │
│   /conversations/{chat_id}/compare → http://localhost:8000/conversations   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓ (HTTP POST)
┌─────────────────────────────────────────────────────────────────────────────┐
│                          FASTAPI BACKEND SERVER                             │
│                        (localhost:8000/conversations)                       │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Route Handler: compare_replies(chat_id: str)                         │ │
│  │                                                                        │ │
│  │  Step 1: Fetch all messages from database                            │ │
│  │  ├─ Query: SELECT * FROM conversations WHERE chat_id = ?             │ │
│  │  └─ Result: List[ConversationMessage]                                │ │
│  │                                                                        │ │
│  │  Step 2: Process message list for human-AI pairs                     │ │
│  │  ├─ For each USER message, find:                                     │ │
│  │  │  ├─ First SELLER message without agent_response → Human reply     │ │
│  │  │  └─ First SELLER message with agent_response → AI reply           │ │
│  │  └─ If both exist, proceed to metrics calculation                    │ │
│  │                                                                        │ │
│  │  Step 3: Calculate similarity metrics                                 │ │
│  │  ├─ _jaccard_similarity():                                           │ │
│  │  │  ├─ Extract character bigrams from both texts                     │ │
│  │  │  ├─ Count intersection & union of bigram sets                     │ │
│  │  │  └─ Return intersection / union                                   │ │
│  │  │                                                                    │ │
│  │  └─ _length_ratio():                                                 │ │
│  │     ├─ Get length of both texts                                      │ │
│  │     └─ Return min_length / max_length                                │ │
│  │                                                                        │ │
│  │  Step 4: Return structured response                                  │ │
│  │  └─ {                                                                │ │
│  │       "chat_id": "123",                                              │ │
│  │       "status": "ok",                                                │ │
│  │       "total_comparisons": 2,                                        │ │
│  │       "comparisons": [                                               │ │
│  │         {                                                            │ │
│  │           "user_message": "...",                                     │ │
│  │           "human_reply": "...",                                      │ │
│  │           "ai_reply": "...",                                         │ │
│  │           "similarity": 0.852,                                       │ │
│  │           "length_ratio": 0.919                                      │ │
│  │         },                                                           │ │
│  │         ...                                                          │ │
│  │       ]                                                              │ │
│  │     }                                                                │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓ (MySQL Query)
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MYSQL DATABASE                                    │
│                    (xianyu_conversations schema)                            │
│                                                                              │
│  ┌─ conversations table ──────────────────────────────────────────────────┐ │
│  │                                                                        │ │
│  │  id | chat_id | message_type | message_content | agent_response | ... │ │
│  │  ── ───────── ────────────── ──────────────── ──────────────── ── ─── │ │
│  │  1  │ "123"   │ "user"       │ "保修多久？"     │ NULL               │ │
│  │  2  │ "123"   │ "seller"     │ "一年保修..."    │ NULL               │ │
│  │  3  │ "123"   │ "seller"     │ "本店保修一年..." │ "{...json...}"   │ │
│  │  4  │ "123"   │ "user"       │ "多少钱？"       │ NULL               │ │
│  │  5  │ "123"   │ "seller"     │ "100块钱"        │ NULL               │ │
│  │  6  │ "123"   │ "seller"     │ "售价100元"      │ "{...json...}"   │ │
│  │  ... (more rows)                                                      │ │
│  │                                                                        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘

```

## Component Interaction Flow

```
User navigates to:
http://localhost:5173/#/history/{chat_id}
            │
            ↓
┌─────────────────────────────────────┐
│ ConversationHistory.vue             │
│ loadDetail(chat_id)                 │
│                                     │
│ 1. Set loading state                │
│ 2. Fetch conversation data          │
│    (conversationHistoryApi.js)       │
│ 3. On success:                      │
│    a. Display messages              │
│    b. Call loadComparison()         │
└─────────────────────────────────────┘
            │
            ├─→ Fetch Conversation
            │   fetch("/conversations/{chat_id}")
            │   └─→ Backend: get_conversation_detail()
            │       └─→ DB Query
            │
            └─→ Load Comparison
                fetch("/conversations/{chat_id}/compare", {method: 'POST'})
                │
                ├─→ Backend: compare_replies()
                │   │
                │   ├─→ Get all messages
                │   ├─→ Find human-AI pairs
                │   ├─→ Calculate Jaccard similarity
                │   ├─→ Calculate length ratio
                │   └─→ Return comparison data
                │
                └─→ Frontend: Display results
                    │
                    ├─→ Set aiComparisons data
                    ├─→ Render comparison cards
                    ├─→ Color-code by similarity
                    └─→ Show metrics
```

## Data Flow Diagram

```
ConversationHistory.vue (UI State)
    │
    ├─ aiComparisons: null → { comparisons: [...] }
    ├─ loadingComparison: false → true → false
    ├─ comparisonError: '' → '' (or error message)
    └─ comparisonVisible: false → true
        │
        ↓
    conversationHistoryApi.compareReplies(chatId)
        │
        ├─ HTTP POST /conversations/{chat_id}/compare
        │
        ↓
    conversations.py - compare_replies(chat_id)
        │
        ├─ get_conversation_store()
        ├─ store.get_conversation_history(chat_id)
        │  └─→ Query DB for all messages
        │
        ├─ For each message in history:
        │  │
        │  ├─ If message_type == 'user':
        │  │  │
        │  │  ├─ Search for human reply
        │  │  │  (message_type='seller' AND agent_response IS NULL)
        │  │  │
        │  │  └─ Search for AI reply
        │  │     (message_type='seller' AND agent_response IS NOT NULL)
        │  │
        │  ├─ If both found:
        │  │  │
        │  │  ├─ Call _jaccard_similarity()
        │  │  │  ├─ Extract bigrams from human_reply
        │  │  │  ├─ Extract bigrams from ai_reply
        │  │  │  ├─ Calculate intersection
        │  │  │  ├─ Calculate union
        │  │  │  └─ Return score (0.0-1.0)
        │  │  │
        │  │  └─ Call _length_ratio()
        │  │     ├─ Get lengths
        │  │     └─ Return ratio (0.0-1.0)
        │  │
        │  └─ Add to comparisons array
        │
        ├─ Return JSON response
        │
        ↓
    Frontend receives JSON
        │
        ├─ Parse response
        ├─ Store in aiComparisons
        ├─ Set loadingComparison = false
        │
        ↓
    Vue template re-renders
        │
        ├─ For each comparison:
        │  │
        │  ├─ Get similarity class: getSimilarityClass(0.852)
        │  │  └─ Returns 'similarity-high' (≥0.7)
        │  │
        │  ├─ Get color: getSimilarityColor(0.852)
        │  │  └─ Returns '#10b981' (green)
        │  │
        │  ├─ Render comparison card with:
        │  │  ├─ User message
        │  │  ├─ Human reply + length
        │  │  ├─ AI reply + length
        │  │  ├─ Progress bar for similarity
        │  │  ├─ Progress bar for length ratio
        │  │  └─ Color-coded badge
        │  │
        │  └─ Apply CSS styling
        │
        └─→ Display to user
```

## File Structure

```
ai_kefu/
├── api/
│   └── routes/
│       └── conversations.py ────────────┐ Modified: Added 3 functions
│           • _jaccard_similarity()      │ + compare_replies() endpoint
│           • _length_ratio()            │ ~135 lines added
│           • compare_replies()          │
│
└── ui/
    └── knowledge/
        └── src/
            ├── components/
            │   └── ConversationHistory.vue ──────────┐ Modified: Added
            │       • data: aiComparisons             │ • 4 data properties
            │       • data: loadingComparison         │ • 3 methods
            │       • data: comparisonError           │ • UI section
            │       • data: comparisonVisible         │ • CSS styles
            │       • loadComparison()                │ ~190 lines added
            │       • getSimilarityClass()            │
            │       • getSimilarityColor()            │
            │       • Template section                │
            │                                         │
            └── conversationHistoryApi.js ────────────┐ Modified: Added
                • compareReplies(chatId)             │ 1 export function
                                                      │ ~6 lines added
```

## Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Frontend Framework | Vue 3 | 3.x |
| Frontend Build | Vite | Latest |
| Frontend UI | Bootstrap | 5.x |
| Backend Framework | FastAPI | 0.100+ |
| Server | Python/Uvicorn | 3.10+ |
| Database | MySQL | 8.0+ |
| Proxy | Vite Dev Proxy | Built-in |
| HTTP Client | Fetch API | Standard |
| Text Algorithm | Jaccard Similarity | Custom |

## Security Layers

```
1. Frontend (Browser)
   └─ Input validation via Vue
   └─ XSS prevention via template escaping
   └─ CORS policy enforcement

2. Proxy Layer (Vite)
   └─ URL encoding of parameters
   └─ HTTP method validation

3. Backend (FastAPI)
   └─ Parameter validation (chat_id type)
   └─ Database query parameterization
   └─ Exception handling & logging
   └─ HTTP status code enforcement

4. Database (MySQL)
   └─ Connection pooling
   └─ Query timeout protection
   └─ Read-only operations (no mutations)
```

---

## Performance Timeline

```
User Click "加载对比"
    │
    ├─→ loadComparison() starts
    │   └─ Elapsed: 0ms
    │
    ├─→ HTTP POST request sent
    │   └─ Elapsed: ~5ms
    │
    ├─→ Backend processes:
    │   ├─ DB query: ~20-30ms
    │   ├─ Message processing: ~10-20ms
    │   ├─ Metrics calculation: ~5-15ms
    │   └─ Elapsed: ~40-80ms
    │
    ├─→ Response received
    │   └─ Elapsed: ~50-100ms total
    │
    ├─→ Frontend renders
    │   ├─ Parse JSON: ~1ms
    │   ├─ Vue re-render: ~10-30ms
    │   ├─ CSS layout: ~5-10ms
    │   └─ Elapsed: ~20-50ms
    │
    └─→ User sees results
        Total: ~70-150ms (typical)
        Max:   ~300-500ms (worst case, large conversations)
```

