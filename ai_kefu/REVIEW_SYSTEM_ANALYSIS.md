# XianyuAutoAgent Review/Evaluation System Analysis

## 1. Vue Component - ConversationHistory.vue

### Review UI Section Location
**File:** `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/ui/knowledge/src/components/ConversationHistory.vue`

#### Review Form Section (Lines 235-288)
```
Line 236-238: Review form header with "对话评价" title and hint text
Line 240-248: Persisted review display (saved review shown when exists)
Line 251-252: Alert messages for success/error feedback
Line 254-267: Rating buttons (👍 好评 / 👎 差评)
Line 269-277: Optional comment textarea
Line 279-286: Submit button ("提交评价")
```

### Key Vue Data Fields (Lines 389-424)
```javascript
// Review form state
reviewRating: 0,              // 0 = not selected, 1 = 👍, -1 = 👎
reviewComment: '',             // Free-text comment
savingReview: false,           // Loading state during submission
reviewSaved: false,            // Transient success indicator
reviewError: '',               // Error message display
savedReview: null,             // Persisted review loaded from DB

// Review badges on session list
reviewMap: {},                 // { [chat_id]: { rating, comment } }
```

### Agent Turns Panel Section (Lines 156-214)
**Location:** Under each AI message in the chat window

#### Turns Panel Structure (Lines 160-213)
```
Line 157-159: Toggle button showing turn count
Line 160-213: Collapsible panel with turn items
  - Line 166-174: Turn header with metadata
    - turn.turn_number
    - turn.confidence_percent (with color class)
    - turn.response_suppressed (badge: "🔇 已抑制")
    - turn.response_text (badge: "✅ 已发送" if exists)
    - turn.duration_ms (execution time)
  - Line 177-189: Tool calls section (if exist)
  - Line 192-203: Tool results section (if exist)
  - Line 206-212: AI response text (with suppressed styling)
```

### Agent Turn Object Fields
From the template rendering and database schema, each `turn` object contains:

```javascript
turn: {
  id: number,                    // DB primary key
  session_id: string,            // AI session ID (foreign key)
  turn_number: number,           // Global sequence within session
  interaction_id: string,        // Groups turns from one user interaction
  local_turn_number: number,     // Sequence within interaction
  
  user_query: string,            // Original user question
  
  llm_input: string|object,      // JSON messages sent to LLM
  llm_output: string|object,     // Raw LLM response JSON
  response_text: string,         // Extracted text from LLM
  
  tool_calls: string|object,     // JSON array of tool calls
  tool_results: string|object,   // JSON array of results
  
  confidence_percent: number,    // 0-100 confidence score
  response_suppressed: boolean,  // Whether response was blocked
  
  duration_ms: number,           // Execution time in ms
  success: boolean,              // Turn succeeded (default true)
  error_message: string,         // Error if failed
  
  created_at: datetime,          // Turn timestamp
}
```

---

## 2. API Routes - `/api/routes/conversations.py`

### Review Endpoints

#### Save/Update Review
**Route:** `POST /conversations/{chat_id}/reviews`
**Lines:** 169-187

```python
async def save_conversation_review(chat_id: str, body: ReviewRequest):
    # Request body:
    class ReviewRequest(BaseModel):
        rating: int              # 1 = 👍, -1 = 👎 (required)
        comment: Optional[str]   # Free-text comment
        session_id: Optional[str]  # AI session ID reference
    
    # Behavior: UPSERT operation
    # - One review per chat_id
    # - Re-submitting overwrites previous rating/comment
    # - Returns: {"ok": True, "id": row_id}
```

**Validation:**
- `rating` must be exactly `1` or `-1`
- HTTP 422 returned if invalid rating
- HTTP 500 on database error

#### Get Reviews for Chat
**Route:** `GET /conversations/{chat_id}/reviews`
**Lines:** 190-204

```python
async def get_conversation_reviews(chat_id: str):
    # Returns: {"chat_id": str, "reviews": List[review_dict]}
    # review_dict contains: id, chat_id, session_id, rating, comment, 
    #                       reviewer, created_at, updated_at
```

### Agent Turns Endpoints

#### Get Recent Turns (System-wide)
**Route:** `GET /conversations/turns/recent`
**Lines:** 108-127
```python
async def get_recent_turns(limit: int = 50, offset: int = 0)
    # Returns: {"items": [turn_dict], "total": int}
```

#### Get Turns by Session
**Route:** `GET /conversations/turns/{session_id}`
**Lines:** 130-163
```python
async def get_session_turns(session_id: str, limit: int = 100, offset: int = 0)
    # Returns: {"session_id": str, "turns": [turn_dict], "total": int}
```

#### Get Full Conversation with Turns
**Route:** `GET /conversations/{chat_id}`
**Lines:** 207-263

```python
# Returns:
{
    "chat_id": str,
    "messages": [message_dict],  # All messages (user/seller/AI/system)
    "total": int,                # Total message count
    "turns_by_session": {        # KEY FIELD for turns panel
        "session_id_1": [turn_dict, ...],
        "session_id_2": [turn_dict, ...],
        ...
    }
}
```

**Note:** turns_by_session is fetched automatically alongside messages
- Extracts all unique session_ids from messages
- Calls store.get_turns_by_session() for each
- Serializes datetime objects to ISO strings

#### AI Comparison Endpoint
**Route:** `POST /conversations/{chat_id}/compare`
**Lines:** 300-391

```python
# Compares human vs AI replies using:
# - Jaccard similarity (bigram-based)
# - Length ratio
# Returns:
{
    "chat_id": str,
    "status": "ok" | "no_data",
    "comparisons": [
        {
            "user_message": str,
            "human_reply": str,
            "ai_reply": str,
            "similarity": float (0.0-1.0),
            "length_ratio": float (0.0-1.0),
            "length_human": int,
            "length_ai": int
        }
    ]
}
```

---

## 3. Database Schema - `xianyu_interceptor/conversation_store.py`

### conversation_reviews Table
**Lines:** 154-169

```sql
CREATE TABLE IF NOT EXISTS conversation_reviews (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    chat_id VARCHAR(255) NOT NULL,         -- Xianyu chat ID (unique)
    session_id VARCHAR(255),               -- AI Agent session ID (optional)
    rating TINYINT NOT NULL,               -- 1 = thumbs up, -1 = thumbs down
    comment TEXT,                          -- Operator free-text comment
    reviewer VARCHAR(255),                 -- Reviewer identifier (default: 'operator')
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uq_chat_id (chat_id),       -- One review per chat_id
    INDEX idx_session_id (session_id),
    INDEX idx_created_at (created_at)
) CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Operator reviews of AI conversation quality'
```

**Key Points:**
- **Per-Conversation Storage**: One review row per chat_id (UNIQUE constraint)
- **UPSERT Pattern**: INSERT...ON DUPLICATE KEY UPDATE
- **No Per-Turn Rating**: Reviews are at conversation level, not per-turn
- Includes optional session_id for reference only (not enforced)

### agent_turns Table
**Lines:** 124-152

```sql
CREATE TABLE IF NOT EXISTS agent_turns (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,      -- Agent session ID
    turn_number INT NOT NULL,              -- Global sequence within session
    interaction_id VARCHAR(255),           -- Groups turns from one interaction
    local_turn_number INT,                 -- Sequence within interaction
    user_query TEXT,                       -- Original user question
    
    llm_input LONGTEXT,                    -- Messages array (JSON)
    llm_output LONGTEXT,                   -- Raw LLM response (JSON)
    response_text TEXT,                    -- Extracted text
    
    tool_calls JSON,                       -- Tool calls array
    tool_results JSON,                     -- Tool results array
    
    duration_ms INT,                       -- Execution time in ms
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    confidence_percent INT,                -- 0-100 confidence score
    response_suppressed BOOLEAN DEFAULT FALSE,  -- Whether blocked
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_session_id (session_id),
    INDEX idx_session_turn (session_id, turn_number),
    INDEX idx_interaction_id (interaction_id),
    INDEX idx_created_at (created_at)
) CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Agent turn-level LLM input/output records for debugging'
```

**Key Point:** No per-turn rating system; only conversation-level reviews

### conversations Table (Message Storage)
**Lines:** 66-95

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    chat_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    user_nickname VARCHAR(255),
    seller_id VARCHAR(255),
    item_id VARCHAR(255),
    message_id VARCHAR(255),               -- For deduplication
    
    message_content TEXT NOT NULL,
    message_type ENUM('user', 'seller', 'system'),
    
    session_id VARCHAR(255),               -- Links to agent_turns.session_id
    agent_response TEXT,                   -- Populated if this is an AI reply
    
    context JSON,                          -- Additional metadata
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uq_message_id (message_id),
    INDEX idx_chat_id (chat_id),
    INDEX idx_session_id (session_id),
    ...
) CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Xianyu conversation history'
```

---

## 4. Frontend API Client - `conversationHistoryApi.js`

**File:** `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/ui/knowledge/src/conversationHistoryApi.js`

### Functions

```javascript
// Fetch paginated conversations
fetchRecentConversations(limit = 30, offset = 0)
  → GET /conversations/recent

// Fetch single conversation with all messages + turns
fetchConversation(chatId)
  → GET /conversations/{chatId}
  → Returns: { messages[], turns_by_session{} }

// Get existing reviews for a conversation
fetchReviews(chatId)
  → GET /conversations/{chatId}/reviews
  → Returns: { chat_id, reviews[] }

// Save (upsert) a review
saveReview(chatId, rating, comment, sessionId)
  → POST /conversations/{chatId}/reviews
  → Body: { rating: 1|-1, comment: string, session_id?: string }

// Get AI comparison analysis
compareReplies(chatId)
  → POST /conversations/{chatId}/compare
  → Returns: { comparisons[], status }
```

---

## 5. Current Limitations & Design Decisions

### Per-Conversation vs Per-Turn Reviews
- **Current:** Reviews are stored at **conversation level** only
- **One review per chat_id** (UNIQUE constraint)
- **No individual turn ratings** in the database
- Session_id is stored for reference but not used to create separate reviews

### Review Workflow
1. User views conversation detail
2. `fetchReviews(chatId)` loads any existing review
3. If review exists → shows "修改评价" (modify) button
4. If no review → shows rating buttons + comment field
5. User submits → `saveReview()` performs UPSERT
6. Review persisted to `conversation_reviews` table
7. Session_id stored but currently unused for segmentation

### Agent Turn Data Flow
1. Messages fetched with `session_id` field
2. Component calls `store.get_turns_by_session(sid)` for each session
3. Turns returned as list of dicts with JSON fields parsed
4. Rendered in collapsible "AI 推理过程" (reasoning process) panel
5. **No rating UI on individual turns** (just info display)

---

## 6. Turn Object Field Summary

| Field | Type | Purpose | Notes |
|-------|------|---------|-------|
| `id` | int | DB primary key | Auto-increment |
| `session_id` | str | Session identifier | Indexes both tables |
| `turn_number` | int | Global sequence | Cumulative per session |
| `interaction_id` | str | Groups related turns | Optional, one per user message |
| `local_turn_number` | int | Within-interaction sequence | Resets per interaction |
| `user_query` | str | Original user message | Reference |
| `llm_input` | JSON | Prompt messages array | Parsed from string |
| `llm_output` | JSON | Raw LLM response | Parsed from string |
| `response_text` | str | Extracted text response | Human-readable |
| `tool_calls` | JSON | Function calls made | Array of call dicts |
| `tool_results` | JSON | Tool execution results | Array of result dicts |
| `confidence_percent` | int | Confidence 0-100 | Used for styling badges |
| `response_suppressed` | bool | Was response blocked? | Shows "🔇 已抑制" badge |
| `duration_ms` | int | Execution time | Shown in UI |
| `success` | bool | Did turn succeed? | Usually true |
| `error_message` | str | Failure reason | Optional |
| `created_at` | datetime | Turn timestamp | Converted to ISO string |

---

## Summary

### What Works Now
✅ Conversation-level reviews (好评/差评 + comment)
✅ Review persistence with UPSERT pattern
✅ Agent turn visualization with 12+ fields
✅ Confidence score + response suppression indicators
✅ AI similarity comparison (human vs AI)

### What's Missing for Per-Turn Rating
❌ No database schema for turn-level reviews
❌ No UI for rating individual turns
❌ No API endpoints for turn-level feedback
❌ Would require new table: `turn_reviews` or column on `agent_turns`

