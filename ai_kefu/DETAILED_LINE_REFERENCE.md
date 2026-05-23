# Detailed Line-by-Line Reference Guide

## ConversationHistory.vue - Exact Line Numbers

### Review UI Components

**Review Form Card** (Lines 235-288)
```vue
236: <div class="review-form card">
237:   <h3>对话评价</h3>
238:   <p class="review-hint">对本对话中 AI 回复质量进行整体评价</p>

240-248: <!-- Persisted review display -->
  shows: rating (thumbs up/down), comment, timestamp, "修改评价" button

251-252: <!-- Error/Success messages -->
  v-if="reviewSaved" → green success alert
  v-if="reviewError" → red error alert

254-267: <!-- Rating buttons -->
  Line 255-260: "👍 好评" button (reviewRating = 1)
  Line 261-266: "👎 差评" button (reviewRating = -1)

269-277: <!-- Comment textarea -->
  v-model="reviewComment"

279-286: <!-- Submit button -->
  @click="submitReview"
  disabled if reviewRating === 0 or savingReview
```

**Vue Data Object** (Lines 389-424)
```javascript
// Review state (lines 411-417)
reviewRating: 0,           // Current selection (0/1/-1)
reviewComment: '',         // Text input
savingReview: false,       // Submission in progress
reviewSaved: false,        // Show success message
reviewError: '',           // Show error message
savedReview: null,         // Loaded from DB

// Session list badges (line 404)
reviewMap: {},             // { chat_id: { rating, comment } }
```

### Agent Turns Panel Components

**Turns Toggle & Panel** (Lines 156-214)
```vue
157-159: <!-- Toggle button -->
  @click="toggleTurns(msg.id)"
  Shows: "▲ 收起 AI 推理过程" or "▼ 查看 AI 推理过程 (N 轮)"

160-214: <!-- Turns panel - only shows if turnsVisible[msg.id] true -->
  v-for="(turn, tidx) in getAgentTurns(msg)"
  
  166-174: <!-- Turn header -->
    Line 167: turn.turn_number (or tidx+1 if null)
    Line 168-170: turn.confidence_percent (with color class)
    Line 171: turn.response_suppressed badge "🔇 已抑制"
    Line 172: turn.response_text badge "✅ 已发送"
    Line 173: turn.duration_ms
    
  177-189: <!-- Tool calls section -->
    Calls formatToolCalls(turn.tool_calls)
    Each tool: name + args display
    
  192-203: <!-- Tool results section -->
    Calls formatToolResults(turn.tool_results)
    
  206-212: <!-- AI response text -->
    Line 209: Shows "(因置信度不足未发送)" if response_suppressed
    Line 211: Applies response-suppressed styling class
```

**Turn Helper Methods** (Lines 585-600)
```javascript
585: getAgentTurns(msg) {
       return this.turnsBySession[msg.session_id] || []
     }

591: hasAgentTurns(msg) {
       return this.getAgentTurns(msg).length > 0
     }

595: toggleTurns(msgId) {
       Toggles turnsVisible[msgId]
     }
```

### Data Loading Methods

**Load Session Detail** (Lines 480-518)
```javascript
495-498: // Load messages + reviews in parallel
         Promise.all([
           fetchConversation(chatId),
           fetchReviews(chatId),
         ])

500: this.turnsBySession = convData.turns_by_session || {}
     ↑ Key line: assigns turns from API response

501-506: // Load persisted review into form
         if (reviewData.reviews && reviewData.reviews.length > 0) {
           const r = reviewData.reviews[0]
           this.reviewRating = r.rating || 0
           this.reviewComment = r.comment || ''
           this.savedReview = r
         }
```

**Submit Review** (Lines 536-558)
```javascript
545: const sessionId = aiMsg ? aiMsg.session_id : null
     ↑ Extracts session_id from first AI message

545: await saveReview(this.selectedChatId, this.reviewRating, 
                      this.reviewComment, sessionId)
     ↑ Calls API with rating + comment

546-550: // Update savedReview display
         this.savedReview = {
           rating: this.reviewRating,
           comment: this.reviewComment,
           updated_at: new Date().toISOString(),
         }
```

---

## conversationHistoryApi.js - Exact Line Numbers

**Save Review** (Lines 46-57)
```javascript
46: export async function saveReview(chatId, rating, comment = '', sessionId = null) {
      // POST /conversations/{chatId}/reviews
      // Body: { rating, comment, session_id: sessionId }
```

**Fetch Reviews** (Lines 33-37)
```javascript
33: export async function fetchReviews(chatId) {
      // GET /conversations/{chatId}/reviews
      // Returns: { chat_id, reviews[] }
```

**Fetch Conversation** (Lines 23-27)
```javascript
23: export async function fetchConversation(chatId) {
      // GET /conversations/{chatId}
      // Returns: { messages[], turns_by_session{} }
      //          ↑ KEY: turns_by_session object
```

---

## conversations.py - Exact Line Numbers

### Review Endpoints

**Save Review Endpoint** (Lines 169-187)
```python
169: @router.post("/{chat_id}/reviews")
170: async def save_conversation_review(chat_id: str, body: ReviewRequest):

18-21: class ReviewRequest(BaseModel):
         rating: int              # 1 or -1
         comment: Optional[str]
         session_id: Optional[str]

175-176: if body.rating not in (1, -1):
           raise HTTPException(status_code=422, ...)
           
179-184: store.save_review(
           chat_id=chat_id,
           rating=body.rating,
           comment=body.comment,
           session_id=body.session_id,
         )
```

**Get Reviews Endpoint** (Lines 190-204)
```python
190: @router.get("/{chat_id}/reviews")
191: async def get_conversation_reviews(chat_id: str):
     # Calls store.get_reviews_by_chat(chat_id)
     # Returns: { "chat_id": str, "reviews": [...] }
```

### Conversation Detail with Turns

**Main Conversation Endpoint** (Lines 207-263)
```python
207: @router.get("/{chat_id}")
208: async def get_conversation_detail(chat_id: str, limit: int = 200, offset: int = 0):

219-223: messages = store.get_conversation_history(
           chat_id=chat_id,
           limit=limit,
           offset=offset
         )

237-252: # Fetch turns for each session
         session_ids = set()
         for msg_dict in result:
           if msg_dict.get('session_id'):
             session_ids.add(msg_dict['session_id'])
         
         turns_by_session = {}
         for sid in session_ids:
           try:
             turns = store.get_turns_by_session(sid)
             turns_by_session[sid] = turns

254-259: return {
           'chat_id': chat_id,
           'messages': result,
           'total': len(result),
           'turns_by_session': turns_by_session  # ← KEY RETURN FIELD
         }
```

### Turns Endpoints

**Get Turns by Session** (Lines 130-163)
```python
130: @router.get("/turns/{session_id}")
131: async def get_session_turns(session_id: str, limit: int = 100, offset: int = 0):
     # Calls store.get_turns_by_session(session_id, limit, offset)
     # Returns: { "session_id": str, "turns": [...], "total": int }
```

---

## conversation_store.py - Exact Line Numbers

### Database Schema Definition

**conversation_reviews Table** (Lines 154-169)
```python
154-169: create_conversation_reviews_sql = """
           CREATE TABLE IF NOT EXISTS conversation_reviews (
             id BIGINT AUTO_INCREMENT PRIMARY KEY,
             chat_id VARCHAR(255) NOT NULL,
             session_id VARCHAR(255),
             rating TINYINT NOT NULL,          # 1 or -1
             comment TEXT,
             reviewer VARCHAR(255) DEFAULT 'operator',
             created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
             updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
             
             UNIQUE KEY uq_chat_id (chat_id),  # ← ONE REVIEW PER CHAT_ID
             INDEX idx_session_id (session_id),
             INDEX idx_created_at (created_at)
         """
```

**agent_turns Table** (Lines 124-152)
```python
124-152: create_agent_turns_sql = """
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
             
             confidence_percent INT,           # ← 0-100 score
             response_suppressed BOOLEAN DEFAULT FALSE,  # ← suppression flag
             
             created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
             
             INDEX idx_session_id (session_id),
             INDEX idx_session_turn (session_id, turn_number),
             ...
         """
```

**Migration: Add confidence columns** (Lines 237-254)
```python
237-254: # Auto-adds confidence_percent and response_suppressed if missing
         ALTER TABLE agent_turns
         ADD COLUMN confidence_percent INT COMMENT '...'
         AFTER error_message,
         ADD COLUMN response_suppressed BOOLEAN DEFAULT FALSE COMMENT '...'
         AFTER confidence_percent
```

### Review Methods

**Save Review (UPSERT)** (Lines 1062-1118)
```python
1062: def save_review(
        self,
        chat_id: str,
        rating: int,              # 1 or -1
        comment: Optional[str] = None,
        session_id: Optional[str] = None,
        reviewer: str = "operator",
      ) -> int:
      
1090-1100: sql = """
             INSERT INTO conversation_reviews
               (chat_id, session_id, rating, comment, reviewer)
             VALUES (%s, %s, %s, %s, %s)
             ON DUPLICATE KEY UPDATE  # ← UPSERT PATTERN
               session_id = VALUES(session_id),
               rating     = VALUES(rating),
               comment    = VALUES(comment),
               reviewer   = VALUES(reviewer),
               updated_at = CURRENT_TIMESTAMP
           """
```

**Get Reviews** (Lines 1120-1145)
```python
1120: def get_reviews_by_chat(self, chat_id: str) -> List[Dict[str, Any]]:
      
1132-1141: sql = """
             SELECT id, chat_id, session_id, rating, comment, reviewer,
                    created_at, updated_at
             FROM conversation_reviews
             WHERE chat_id = %s
             ORDER BY created_at DESC
           """
```

### Turns Methods

**Get Turns by Session** (Lines 955-1001)
```python
955: def get_turns_by_session(
       self,
       session_id: str,
       limit: int = 100,
       offset: int = 0
     ) -> List[Dict[str, Any]]:
     
975-979: sql = """
           SELECT * FROM agent_turns
           WHERE session_id = %s
           ORDER BY turn_number ASC
           LIMIT %s OFFSET %s
         """

988-993: # Parse JSON fields from string
         for json_field in ('llm_input', 'llm_output', 'tool_calls', 'tool_results'):
           if row.get(json_field):
             try:
               row[json_field] = json.loads(row[json_field])
```

---

## CSS Styling - Relevant Classes

**Agent Turns Panel Styling** (Lines 1217-1333)
```css
1217-1221: .turns-toggle         # Purple toggle link for agent turns
1223-1234: .agent-turns-panel    # Container with purple background
1236-1241: .agent-turn-item      # Individual turn card
1243-1251: .agent-turn-header    # Flex container for metadata
1259-1264: .turn-confidence      # Confidence badge (with color classes)
1266-1282: .confidence-high/medium/low  # Color schemes for 70%+, 40%+, <40%
1284-1292: .badge-suppressed     # Red badge "🔇 已抑制"
1294-1302: .badge-sent           # Green badge "✅ 已发送"
1310-1327: .turn-response-text   # AI response styling (purple or red if suppressed)
```

---

## Summary of Critical Fields

| Location | Field | Type | Used By |
|----------|-------|------|---------|
| Vue Data | `reviewRating` | 0/1/-1 | Form submission |
| Vue Data | `savedReview` | dict/null | Display persisted review |
| Vue Data | `turnsBySession` | dict | getAgentTurns() lookup |
| Turn Object | `turn.confidence_percent` | int (0-100) | Badge color class |
| Turn Object | `turn.response_suppressed` | bool | Suppression badge + styling |
| Turn Object | `turn.turn_number` | int | Display "Turn N" |
| Turn Object | `turn.duration_ms` | int | Display execution time |
| Turn Object | `turn.response_text` | str | Rendered text content |
| DB Schema | `conversation_reviews.rating` | TINYINT | ±1 only |
| DB Schema | `agent_turns.confidence_percent` | INT | Query filter (optional) |
| API Response | `turns_by_session` | dict | Maps sessions to turn lists |

