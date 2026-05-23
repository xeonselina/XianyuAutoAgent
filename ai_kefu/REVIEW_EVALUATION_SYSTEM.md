# 🎯 XianyuAutoAgent Review/Evaluation System - Complete Exploration Report

Generated: 2026-05-03

---

## Executive Summary

The XianyuAutoAgent has a **conversation-level review system** (好评/差评 with optional comments) and a **detailed agent turns visualization panel**. Reviews are stored per-conversation, not per-turn. The system includes:

- ✅ Operator feedback collection (thumbs up/down + comment)
- ✅ Per-conversation persistence (UPSERT pattern)
- ✅ Multi-turn LLM reasoning visualization
- ✅ Confidence scoring and response suppression indicators
- ✅ AI-based similarity comparison (human vs. AI)
- ❌ No per-turn rating system

---

## Section 1: Vue Review UI

### Location
**File:** `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/ui/knowledge/src/components/ConversationHistory.vue`

### Review Form Section
**Lines 235-288** (Review Card Component)

```
┌─────────────────────────────────────────────────┐
│  对话评价                                       │
│  对本对话中 AI 回复质量进行整体评价             │
├─────────────────────────────────────────────────┤
│                                                 │
│  [If review saved]                              │
│  👍 好评 | 已于 XX:XX 保存 | [修改评价]        │
│                                                 │
│  [If editing]                                   │
│  [👍 好评]  [👎 差评]                          │
│  ┌─────────────────────────────────────────┐   │
│  │ 补充说明（可选）                        │   │
│  │ [textarea]                              │   │
│  └─────────────────────────────────────────┘   │
│  [提交评价]                                     │
│                                                 │
└─────────────────────────────────────────────────┘
```

### Key Component Lines
| Line(s) | Component | Purpose |
|---------|-----------|---------|
| 236-238 | Header | Title + hint text |
| 240-248 | Saved Review | Shows persisted review with "修改评价" button |
| 251-252 | Alerts | Success/error messages |
| 254-267 | Rating Buttons | 👍 (rating=1) and 👎 (rating=-1) |
| 269-277 | Comment Field | Optional free-text input |
| 279-286 | Submit Button | `submitReview()` on click |

### Vue Data State (Lines 389-424)

```javascript
data() {
  return {
    // Review form state
    reviewRating: 0,              // 0=unselected, 1=👍, -1=👎
    reviewComment: '',            // Text input
    savingReview: false,          // Loading indicator
    reviewSaved: false,           // Transient success flag
    reviewError: '',              // Error display
    savedReview: null,            // { rating, comment, updated_at } from DB
    
    // Session list badges
    reviewMap: {},                // { chat_id: review_obj }
    
    // Agent turns panel
    turnsBySession: {},           // { session_id: [turn_dict] }
    turnsVisible: {},             // { msg_id: bool }
  }
}
```

### Review Submission Flow (Lines 536-558)

```
1. User clicks [提交评价]
   └─→ submitReview() called

2. Validation
   └─→ if (!reviewRating) return

3. Get session_id (line 543)
   └─→ const sessionId = aiMsg ? aiMsg.session_id : null

4. API Call (line 545)
   └─→ saveReview(chat_id, rating, comment, sessionId)

5. Update UI
   └─→ this.savedReview = { rating, comment, updated_at }
   └─→ this.reviewSaved = true
   └─→ Dismiss form, show saved state (line 247)
```

---

## Section 2: Agent Turns Panel

### Location & Structure
**Lines 156-214** (Under each AI message in chat window)

### Toggle & Panel
```
Line 157-159: <!-- Toggle button -->
  "▼ 查看 AI 推理过程 (3 轮)" 
  @click="toggleTurns(msg.id)"

Line 160-214: <!-- Collapsible panel -->
  v-if="turnsVisible[msg.id]"
  v-for="(turn, tidx) in getAgentTurns(msg)"
```

### Individual Turn Display (Lines 166-212)

```
┌────────────────────────────────────────────────────┐
│ Turn 1 | 置信度 75% | ✅ 已发送 | 248ms           │
├────────────────────────────────────────────────────┤
│ 🔧 工具调用                                       │
│  • search_item (item_id: "12345")                 │
│                                                   │
│ 📤 工具结果                                       │
│  • {"success": true, "price": 99.9}              │
│                                                   │
│ 💬 AI 回复                                        │
│  商品价格是 99.9 元，有货。                      │
│                                                   │
└────────────────────────────────────────────────────┘
```

### Turn Metadata Fields (Lines 166-174)

| Field | Line | Type | Display |
|-------|------|------|---------|
| `turn_number` | 167 | int | "Turn N" |
| `confidence_percent` | 168-170 | int (0-100) | Badge with color class |
| `response_suppressed` | 171 | bool | 🔇 Red badge if true |
| `response_text` exists | 172 | bool | ✅ Green badge if exists |
| `duration_ms` | 173 | int | "XXms" text |

### Confidence Color Mapping (Lines 648-652)

```javascript
confidenceClass(pct) {
  if (pct >= 70) return 'confidence-high'     // Green
  if (pct >= 40) return 'confidence-medium'   // Orange
  return 'confidence-low'                     // Red
}
```

### Tool Calls & Results (Lines 177-203)

```vue
<!-- Tool calls (if exist) - Lines 177-189 -->
<div v-if="turn.tool_calls && ...">
  🔧 工具调用
  <div v-for="tc in formatToolCalls(turn.tool_calls)">
    {{ tc.name }}
    {{ argsDisplay(tc.args) }}
  </div>
</div>

<!-- Tool results (if exist) - Lines 192-203 -->
<div v-if="turn.tool_results && ...">
  📤 工具结果
  <div v-for="tr in formatToolResults(turn.tool_results)">
    {{ tr.content }}
  </div>
</div>
```

---

## Section 3: API Endpoints

### File Location
`/Users/jimmypan/git_repo/XianyuAutoAgent/api/routes/conversations.py`

### Review Endpoints

#### Save/Update Review
```
POST /conversations/{chat_id}/reviews
Lines: 169-187

Request:
{
  "rating": 1 or -1,           # Required: 1=👍, -1=👎
  "comment": "Optional text",  # Optional
  "session_id": "sess_123"     # Optional, for reference
}

Validation:
- rating must be exactly 1 or -1
- Returns HTTP 422 if invalid
- Returns HTTP 500 on DB error

Response:
{
  "ok": true,
  "id": 12345  # Row ID inserted/updated
}
```

#### Get Reviews
```
GET /conversations/{chat_id}/reviews
Lines: 190-204

Response:
{
  "chat_id": "chat_abc123",
  "reviews": [
    {
      "id": 12345,
      "chat_id": "chat_abc123",
      "session_id": "sess_123",
      "rating": 1,
      "comment": "Good response",
      "reviewer": "operator",
      "created_at": "2026-05-03T12:34:56",
      "updated_at": "2026-05-03T12:34:56"
    }
  ]
}
```

### Agent Turns Endpoints

#### Get Turns by Session
```
GET /conversations/turns/{session_id}
Lines: 130-163

Query Parameters:
- limit: int (default 100, max 500)
- offset: int (default 0)

Response:
{
  "session_id": "sess_123",
  "turns": [
    {
      "id": 999,
      "session_id": "sess_123",
      "turn_number": 1,
      "interaction_id": "int_001",
      "local_turn_number": 1,
      "user_query": "What's the price?",
      "llm_input": [...],      # Parsed from JSON
      "llm_output": {...},     # Parsed from JSON
      "response_text": "The price is...",
      "tool_calls": [...],     # Parsed from JSON
      "tool_results": [...],   # Parsed from JSON
      "confidence_percent": 75,
      "response_suppressed": false,
      "duration_ms": 248,
      "success": true,
      "error_message": null,
      "created_at": "2026-05-03T12:34:56"
    }
  ],
  "total": 1
}
```

#### Get Conversation with Turns
```
GET /conversations/{chat_id}
Lines: 207-263

Response:
{
  "chat_id": "chat_abc123",
  "messages": [...],           # All messages in conversation
  "total": 42,                 # Total message count
  "turns_by_session": {        # KEY FIELD
    "sess_123": [              # Turns for this session
      { turn_obj_1 },
      { turn_obj_2 }
    ],
    "sess_456": [
      { turn_obj_3 }
    ]
  }
}
```

**Key Implementation (Lines 237-252):**
```python
# Extract all session IDs from messages
session_ids = set()
for msg_dict in result:
  if msg_dict.get('session_id'):
    session_ids.add(msg_dict['session_id'])

# Fetch turns for each session
turns_by_session = {}
for sid in session_ids:
  turns = store.get_turns_by_session(sid)
  turns_by_session[sid] = turns
```

---

## Section 4: Database Schema

### File Location
`/Users/jimmypan/git_repo/XianyuAutoAgent/xianyu_interceptor/conversation_store.py`

### conversation_reviews Table
**Lines: 154-169**

```sql
CREATE TABLE IF NOT EXISTS conversation_reviews (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    chat_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(255),
    rating TINYINT NOT NULL,              -- ±1 only
    comment TEXT,
    reviewer VARCHAR(255) DEFAULT 'operator',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uq_chat_id (chat_id),      -- ONE REVIEW PER CHAT_ID
    INDEX idx_session_id (session_id),
    INDEX idx_created_at (created_at)
) CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Operator reviews of AI conversation quality'
```

**Key Constraint:** `UNIQUE KEY uq_chat_id (chat_id)`
- Only one review per conversation
- Re-submitting overwrites previous rating/comment
- UPSERT pattern: `INSERT...ON DUPLICATE KEY UPDATE`

### agent_turns Table
**Lines: 124-152**

```sql
CREATE TABLE IF NOT EXISTS agent_turns (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    turn_number INT NOT NULL,
    interaction_id VARCHAR(255),
    local_turn_number INT,
    user_query TEXT,
    
    llm_input LONGTEXT,
    llm_output LONGTEXT,
    response_text TEXT,
    
    tool_calls JSON,
    tool_results JSON,
    
    duration_ms INT,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    confidence_percent INT,               -- ← 0-100 score
    response_suppressed BOOLEAN DEFAULT FALSE,  -- ← suppression flag
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_session_id (session_id),
    INDEX idx_session_turn (session_id, turn_number),
    INDEX idx_interaction_id (interaction_id),
    INDEX idx_created_at (created_at)
) CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Agent turn-level LLM input/output records for debugging'
```

**No per-turn rating columns** — only confidence_percent and response_suppressed

### Confidence Columns Migration
**Lines: 237-254**

Auto-migrates existing databases to add:
```sql
ALTER TABLE agent_turns
ADD COLUMN confidence_percent INT COMMENT 'Response confidence score (0-100)'
AFTER error_message,
ADD COLUMN response_suppressed BOOLEAN DEFAULT FALSE COMMENT 'Whether response was suppressed by confidence guard'
AFTER confidence_percent
```

---

## Section 5: Frontend API Client

### File Location
`/Users/jimmypan/git_repo/XianyuAutoAgent/ui/knowledge/src/conversationHistoryApi.js`

### All Functions

```javascript
// Line 13-17
export async function fetchRecentConversations(limit = 30, offset = 0)
  → GET /conversations/recent?limit={limit}&offset={offset}

// Line 23-27
export async function fetchConversation(chatId)
  → GET /conversations/{chatId}
  → Returns: { messages[], turns_by_session{} }

// Line 33-37
export async function fetchReviews(chatId)
  → GET /conversations/{chatId}/reviews
  → Returns: { chat_id, reviews[] }

// Line 46-57
export async function saveReview(chatId, rating, comment = '', sessionId = null)
  → POST /conversations/{chatId}/reviews
  → Body: { rating: 1|-1, comment: string, session_id?: string }
  → Returns: { ok: true, id: int }

// Line 64-70
export async function compareReplies(chatId)
  → POST /conversations/{chatId}/compare
  → Returns: { comparisons[], status }
```

---

## Section 6: Turn Object Field Reference

### Complete Field List with Types

| Field | Type | DB Column | Used In | Purpose |
|-------|------|-----------|---------|---------|
| `id` | int | agent_turns.id | PK | Database primary key |
| `session_id` | str | agent_turns.session_id | FK | Links to session |
| `turn_number` | int | agent_turns.turn_number | Display | Global sequence (e.g., "Turn 3") |
| `interaction_id` | str | agent_turns.interaction_id | Grouping | Groups turns from one user message |
| `local_turn_number` | int | agent_turns.local_turn_number | Debugging | Resets per interaction |
| `user_query` | str | agent_turns.user_query | Context | Original user question |
| `llm_input` | JSON | agent_turns.llm_input | Debug | Messages array sent to LLM |
| `llm_output` | JSON | agent_turns.llm_output | Debug | Raw LLM response object |
| `response_text` | str | agent_turns.response_text | Display | Human-readable LLM text |
| `tool_calls` | JSON | agent_turns.tool_calls | Panel | Array of tool invocations |
| `tool_results` | JSON | agent_turns.tool_results | Panel | Array of tool outputs |
| `confidence_percent` | int | agent_turns.confidence_percent | Badge Color | 0-100 confidence score |
| `response_suppressed` | bool | agent_turns.response_suppressed | Badge/Style | Was response blocked? |
| `duration_ms` | int | agent_turns.duration_ms | Display | Execution time in ms |
| `success` | bool | agent_turns.success | Status | Did turn succeed? |
| `error_message` | str | agent_turns.error_message | Debug | Failure reason if failed |
| `created_at` | datetime | agent_turns.created_at | Timestamp | Turn execution time |

---

## Section 7: Frontend-Backend Data Flow

### Load Conversation Detail

```
User clicks conversation → openSession(chat_id)
                           ↓
          Component.loadDetail(chat_id)
                           ↓
         Promise.all([
           fetchConversation(chat_id),     ← GET /conversations/{chat_id}
           fetchReviews(chat_id)           ← GET /conversations/{chat_id}/reviews
         ])
                           ↓
    Backend: get_conversation_detail()
      • Fetch messages from conversations table
      • Extract all session_ids from messages
      • For each session_id:
         store.get_turns_by_session(session_id)
      • Return { messages, turns_by_session }
                           ↓
    Frontend: Component.loadDetail()
      • this.messages = convData.messages
      • this.turnsBySession = convData.turns_by_session  ← KEY ASSIGNMENT
      • Load review into form
      • Load AI comparison
```

### Render Agent Turns

```
In template, for each message with session_id:
  <div v-if="hasAgentTurns(msg)">
    <div v-for="(turn, idx) in getAgentTurns(msg)">
                           ↓
  getAgentTurns(msg):
    return this.turnsBySession[msg.session_id] || []
                           ↓
  Display turn details:
    • turn.turn_number        → "Turn 1"
    • turn.confidence_percent → Badge (75%)
    • turn.response_suppressed → 🔇 Badge
    • turn.tool_calls        → Panel section
    • turn.tool_results      → Panel section
    • turn.response_text     → Main content
    • turn.duration_ms       → "248ms"
```

### Submit Review

```
User clicks [提交评价]
      ↓
submitReview() called
      ↓
POST /conversations/{chat_id}/reviews
Body: {
  rating: 1 or -1,
  comment: "user text",
  session_id: "extracted from first AI msg"
}
      ↓
Backend: save_conversation_review()
  • Validate rating ∈ {1, -1}
  • INSERT INTO conversation_reviews ... 
    ON DUPLICATE KEY UPDATE
  • Return { ok: true, id }
      ↓
Frontend: showSuccess() + savedReview = {...}
```

---

## Section 8: Style Classes (CSS)

### Agent Turns Panel Styling
**Lines: 1217-1333 in ConversationHistory.vue**

```css
.turns-toggle              (1217-1221)
  ├─ color: #722ed1 (purple)
  ├─ cursor: pointer
  └─ Toggles turns panel visibility

.agent-turns-panel        (1223-1234)
  ├─ background: #faf5ff (light purple)
  ├─ border: #d3adf7 (purple border)
  └─ max-width: 560px

.agent-turn-item          (1236-1241)
  ├─ background: #fff
  ├─ border: #e8e8e8
  └─ Individual turn card

.agent-turn-header        (1243-1251)
  ├─ display: flex
  ├─ Metadata row: Turn N | Confidence | Duration
  └─ border-bottom: 1px solid #f0f0f0

.turn-confidence          (1259-1264)
  ├─ Font: bold, small
  ├─ Padding: 1px 8px
  └─ Border-radius: 10px

.confidence-high          (1266-1270)
  ├─ background: #f6ffed (green)
  ├─ color: #389e0d
  └─ For pct >= 70

.confidence-medium        (1272-1276)
  ├─ background: #fffbe6 (orange)
  ├─ color: #ad6800
  └─ For 40 <= pct < 70

.confidence-low           (1278-1282)
  ├─ background: #fff2f0 (red)
  ├─ color: #cf1322
  └─ For pct < 40

.badge-suppressed         (1284-1292)
  ├─ 🔇 已抑制 badge
  ├─ Red styling
  └─ When response_suppressed = true

.badge-sent               (1294-1302)
  ├─ ✅ 已发送 badge
  ├─ Green styling
  └─ When response_text exists

.turn-response-text       (1310-1327)
  ├─ background: #f9f0ff (light purple)
  ├─ border-left: 3px solid #722ed1 (purple)
  ├─ Rendered AI text content
  └─ .response-suppressed class for red styling
```

---

## Section 9: Key Findings & Limitations

### Current Capabilities
✅ **Conversation-Level Reviews**
- One review per chat_id (UPSERT pattern)
- Rating: 1 (👍) or -1 (👎)
- Optional free-text comment
- Operator identifier stored

✅ **Agent Turn Visualization**
- Display 12+ fields per turn
- Color-coded confidence badges (70%+, 40%+, <40%)
- Response suppression indicators
- Tool calls and results panels
- Execution timing display

✅ **AI Similarity Analysis**
- Jaccard similarity (bigram-based)
- Length ratio comparison
- Identifies human vs. AI reply pairs
- Returns percentages (0-100%)

✅ **Multi-Session Support**
- Handles multiple AI sessions per conversation
- Turns grouped by session_id
- Each session's turns fetched independently

### Current Limitations
❌ **No Per-Turn Rating System**
- `conversation_reviews` stores only conversation-level feedback
- No `turn_reviews` table or turn_id column
- Cannot rate individual reasoning steps

❌ **No Turn-Level Feedback UI**
- Turns panel is read-only (info display only)
- No rating buttons on individual turns
- No way to mark specific turns as good/bad

❌ **Session_id in Reviews is Unused**
- Stored in DB but not used for segmentation
- Reviews always conversation-level regardless of session

❌ **No Per-Turn Persistence**
- No way to save feedback about specific turns
- Confidence/suppression are display-only fields
- Cannot override or modify turn-level data

---

## Section 10: Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                   ConversationHistory.vue                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────┐                   │
│  │  Chat Message Window                │                   │
│  │  • User messages                    │                   │
│  │  • Human replies                    │                   │
│  │  • AI replies + turns panel         │                   │
│  └─────────────────────────────────────┘                   │
│                     ↓                                       │
│  ┌─────────────────────────────────────┐                   │
│  │  Agent Turns Panel (Collapsible)    │                   │
│  │  • Turn header (N, confidence, ms)  │                   │
│  │  • Tool calls section               │                   │
│  │  • Tool results section             │                   │
│  │  • AI response text                 │                   │
│  └─────────────────────────────────────┘                   │
│                     ↓                                       │
│  ┌─────────────────────────────────────┐                   │
│  │  Review Form                        │                   │
│  │  • Rating buttons (👍 / 👎)        │                   │
│  │  • Comment textarea                 │                   │
│  │  • Submit button                    │                   │
│  └─────────────────────────────────────┘                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                             ↓
                      conversationHistoryApi.js
                             ↓
         ┌────────────────────┴────────────────────┐
         │                                         │
    ┌────────────────────┐                  ┌──────────────┐
    │  FastAPI Routes    │                  │  MySQL DB    │
    │  /conversations/   │                  │              │
    │  • GET /recent     │                  │  Tables:     │
    │  • GET /{chat_id}  │←────────────────→│  • conv.     │
    │  • GET /reviews    │                  │  • agent_    │
    │  • POST /reviews   │                  │    turns     │
    │  • GET /turns/{id} │                  │  • conv.     │
    │  • POST /compare   │                  │    reviews   │
    └────────────────────┘                  └──────────────┘
                                                    ↓
                                          conversation_store.py
                                          (Query layer)
```

---

## Section 11: File Reference Summary

| File | Lines | Purpose |
|------|-------|---------|
| ConversationHistory.vue | 1-1334 | Main Vue component |
| Review UI | 235-288 | Review form rendering |
| Review state | 389-424 | Vue data object |
| Review methods | 536-558 | Submit logic |
| Turns panel | 156-214 | Turns visualization |
| Turns helpers | 585-600 | getAgentTurns() etc |
| conversationHistoryApi.js | 1-71 | API client functions |
| conversations.py | 1-392 | FastAPI routes |
| Review endpoints | 169-204 | POST/GET reviews |
| Turns endpoints | 108-163 | GET turns routes |
| Main endpoint | 207-263 | GET conversation + turns |
| conversation_store.py | 1-1156 | Database layer |
| Schema creation | 62-260 | Table definitions |
| save_review() | 1062-1118 | UPSERT review logic |
| get_reviews() | 1120-1145 | SELECT reviews |
| get_turns() | 955-1001 | SELECT turns |

---

## Conclusion

The review/evaluation system is **production-ready for conversation-level feedback** but **lacks per-turn rating capabilities**. The agent turns panel effectively displays multi-step reasoning with 16+ data fields, but serves as an information panel only.

To implement per-turn ratings, you would need:
1. New database table: `turn_reviews(id, turn_id, rating, comment, ...)`
2. New API endpoints for turn-level CRUD
3. UI controls (rating buttons) in the turns panel
4. Frontend state management for per-turn feedback

