# Deposit Logic Quick Reference Guide

## ⚡ Quick Navigation

### 🔴 CRITICAL FILES (Start here)

1. **System Prompt with Deposit Rules**
   - File: `prompts/rental_system_prompt.py`
   - Lines: 36, 111, 152, 161 (repeated at 214, 289, 330, 339)

2. **Knowledge Base Deposit Entry**
   - File: `scripts/init_rental_knowledge.py`
   - Lines: 94-119 (entry `rental_002`)
   - Contains: Sesame Credit conditions, Huabei details, deposit amounts

---

## 📋 System Prompt Quick Responses (Line 36 & 214)

```python
# When user asks: "押金多少?" (What's the deposit?)
Response: "芝麻700分以上仅需芝麻截图，550-699需再补身份证或门票打码图"

Translation:
- Sesame Credit ≥700: Only need Sesame Credit screenshot
- Sesame Credit 550-699: Need to provide masked ID card or ticket photo
```

---

## 📖 Full Deposit Policy (Knowledge Base Entry rental_002)

**Entry Details:**
- ID: `rental_002`
- Title: 免押金条件 (Deposit-Free Conditions)
- Category: 押金政策 (Deposit Policy)
- Priority: 9

**Complete Content:**
```
手机租赁免押金条件:

符合以下任一条件可申请免押金:

1. 芝麻信用分 ≥ 550分
   - 需提供支付宝芝麻信用截图
   - 需要提供身份证（需要姓名和身份证号，其他可以打码）

2. 花呗额度 ≥ 3000元
   - 支付时直接使用花呗支付即可免押

3. 老客户直接免押

不符合免押条件的客户需支付押金:
- vivo x300pro 加增距镜套装: 押金3000元
- vivo x200u 加增距镜套装: 押金3000元

押金在设备归还并验收通过后24小时内原路退回。
```

---

## 🛠️ System Prompt Tool Requirements

**Line 111 (repeated at 289):**
```python
"- **knowledge_search**: 查知识库（押金政策、使用须知等）"
```
→ MUST use knowledge_search tool for deposit queries

**Line 152 (repeated at 330):**
```python
"5. 用户问押金 → 查知识库回答"
```
→ Workflow: User asks about deposit → Query knowledge base → Respond

**Line 161 (repeated at 339):**
```python
"- 不要在用户没问的时候主动介绍押金、使用须知等"
```
→ NEVER proactively mention deposits

---

## 🚫 Forbidden Actions (System Prompt)

From `rental_system_prompt.py` (Lines 240-247):

```python
## 🚫 绝对禁止

1. **禁止编造任何信息**: 不要编造电话号码、微信号、邮箱、网址、具体价格、具体政策。
   ❌ DO NOT fabricate: deposit amounts, terms, conditions
   
2. **禁止重复追问**: 同一个信息最多问 **2 次**。
   ❌ DO NOT ask same question 3+ times
   
5. **禁止编造档期/库存**: 凡是"有无档期/有无库存"必须先调用 check_availability
   ❌ DO NOT claim "deposit waived" without checking qualifications
```

---

## 💳 Huabei Integration

**Source**: `scripts/init_rental_knowledge.py` Lines 105-106

**Rule:**
```
花呗额度 ≥ 3000元
→ 支付时直接使用花呗支付即可免押
```

**Meaning:**
- User has Huabei installment limit of ≥3000 CNY
- Pay for rental directly via Huabei at checkout
- Automatically waives 3000 CNY device deposit

---

## 📊 Knowledge Base Schema

**Storage**: MySQL table `knowledge_entries`

**Deposit Entry Row:**
```sql
INSERT INTO knowledge_entries (
    kb_id,           → 'rental_002'
    title,           → '免押金条件'
    content,         → [Full policy text from above]
    category,        → '押金政策'
    tags,            → '["押金", "免押", "芝麻信用"]'
    priority,        → 9
    active,          → TRUE
    source,          → '租赁业务规则'
    created_at,      → TIMESTAMP
    updated_at       → TIMESTAMP
) VALUES (...)
```

---

## 🔍 Search Tool Integration

**File**: `tools/knowledge_search.py`

**Usage:**
```python
# When user asks about deposit
result = knowledge_search("押金")           # Search "deposit"
# or
result = knowledge_search("免押")          # Search "deposit-free"
# or
result = knowledge_search("花呗")          # Search "Huabei"

# Returns top 5 matching entries with similarity scores
```

---

## 📦 Order Processing Integration

**File**: `api/routes/xianyu.py` Line 200

**Order Summary Extraction:**
```python
"5. **特殊要求**：任何额外的要求（如配件、免押条件、特定型号等）"
```
→ Extracts deposit waiver requests from order summary

---

## 🔄 Complete Deposit Inquiry Workflow

```
User: "押金多少?"
  ↓
System calls: knowledge_search("押金")
  ↓
Returns: rental_002 entry with full policy
  ↓
Extract from knowledge:
  - Sesame Credit conditions
  - Huabei details
  - Deposit amounts
  - Refund timeline
  ↓
Respond with appropriate condition for user
```

---

## ❌ What NOT to Do

- ❌ Don't mention deposits unless user asks
- ❌ Don't make up deposit amounts (must use knowledge base)
- ❌ Don't skip knowledge_search tool call
- ❌ Don't ask same question more than 2 times
- ❌ Don't respond without querying knowledge base

---

## ✅ What TO Do

- ✅ Always call `knowledge_search` for deposit questions
- ✅ Use quick response at Line 36/214 only if searching fails
- ✅ Follow workflow: Ask → Search → Respond
- ✅ If uncertain, call `ask_human_agent`
- ✅ Keep responses under 50 characters

---

## 🧪 Testing Commands

```bash
# Test deposit-related searches
python -c "from ai_kefu.tools.knowledge_search import knowledge_search; import json; print(json.dumps(knowledge_search('押金'), indent=2, ensure_ascii=False))"

python -c "from ai_kefu.tools.knowledge_search import knowledge_search; import json; print(json.dumps(knowledge_search('免押'), indent=2, ensure_ascii=False))"

python -c "from ai_kefu.tools.knowledge_search import knowledge_search; import json; print(json.dumps(knowledge_search('花呗'), indent=2, ensure_ascii=False))"
```

---

## 📝 Files at a Glance

| File | Content | Key Lines |
|------|---------|-----------|
| `prompts/rental_system_prompt.py` | System rules + quick response | 36, 111, 152, 161, 214, 289, 330, 339 |
| `scripts/init_rental_knowledge.py` | KB initialization + deposit entry | 94-119 |
| `tools/knowledge_search.py` | Search implementation | - |
| `models/knowledge.py` | Data model | - |
| `storage/knowledge_store.py` | Storage layer | - |
| `api/routes/xianyu.py` | Message ingestion | 200 |

---

**Generated**: 2026-04-10
**Project**: XianyuAutoAgent/ai_kefu
