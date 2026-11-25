# 📋 Conversation & Session Architecture Analysis

## 🎯 Your Questions Answered

### Question 1: Is conversation history saved after call hangup with ONE insert query per call session?
**Answer:** ❌ **NO - Multiple inserts happen, not just one**

### Question 2: Does every call have their own session?
**Answer:** ✅ **YES - Each call gets a unique session**

### Question 3: Is everything connected with each other for better working?
**Answer:** ⚠️ **PARTIALLY - There are disconnects we need to fix**

---

## 📊 Current Architecture (What's Happening Now)

### Call Lifecycle Flow

```
┌─────────────────────────────────────────────────┐
│ 1. CALL ARRIVES (Asterisk ARI)                 │
│    Call ID generated: call_1234567890          │
└──────────────┬──────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────┐
│ 2. SESSION CREATED IN REDIS                    │
│    Key: call:{call_id}                         │
│    TTL: 3600 seconds (1 hour)                  │
│    Contains:                                    │
│    - call_id, user_id, agent_name             │
│    - language, conversation (array)            │
│    - call_status, started_at, metadata        │
└──────────────┬──────────────────────────────────┘
               │
     ┌─────────┴─────────┐
     │                   │
┌────▼────────┐  ┌───────▼────────┐
│ 3A. DURING  │  │ 3B. REQUIREMENT│
│    CALL     │  │    COLLECTION  │
│             │  │                │
│ Messages    │  │ Stored in      │
│ added to    │  │ LocalStorage   │
│ Redis       │  │ (Memory)       │
│ conversation│  │                │
│ array       │  │ Each call_id:  │
│             │  │ - customer_name│
│             │  │ - company_name │
│             │  │ - location     │
│             │  │ - products     │
│             │  │ - quantity     │
│             │  │ - etc (7 fields)
│             │  │                │
└────┬────────┘  └────────┬───────┘
     │                    │
     └─────────┬──────────┘
               │
     ┌─────────▼──────────────────┐
     │ 4. CALL ENDS               │
     │    StasisEnd event fires   │
     │    on_call_end() triggered │
     └─────────┬──────────────────┘
               │
     ┌─────────▼──────────────────────────────────────────┐
     │ 5. MULTIPLE SAVE OPERATIONS (NOT JUST ONE!)       │
     └─────────┬──────────────────────────────────────────┘
               │
     ┌─────────┴──────────────────────────────────────────┐
     │                                                    │
  ┌──▼──────────────────┐              ┌───────────────▼─┐
  │ 5A. SAVE            │              │ 5B. SAVE        │
  │ CONVERSATION_MSGS   │              │ REQUIREMENT     │
  │                     │              │ DATA            │
  │ For EACH message:   │              │                 │
  │ INSERT INTO         │              │ One query:      │
  │ conversation_       │              │ INSERT INTO     │
  │ messages            │              │ customer_       │
  │                     │              │ requirements    │
  │ Query repeats:      │              │                 │
  │ message_count       │              │ OR if using     │
  │ times               │              │ Google Sheets:  │
  │                     │              │ Append one row  │
  │ Example: 10 msgs =  │              │ with 7 fields   │
  │ 10 INSERT queries   │              │                 │
  │                     │              │ Single operation│
  └──┬──────────────────┘              └────────┬────────┘
     │                                          │
     │      ┌──────────────────────────┐       │
     │      │ 5C. SAVE                 │       │
     │      │ CONVERSATION_HISTORY     │       │
     │      │                          │       │
     │      │ One query:               │       │
     │      │ INSERT INTO              │       │
     │      │ conversation_history     │       │
     │      │                          │       │
     │      │ Full transcript:         │       │
     │      │ ALL messages concatenated│       │
     │      │ as single text field     │       │
     │      └──────────┬───────────────┘       │
     │                 │                       │
     └─────────┬───────┴───────────────────────┘
               │
     ┌─────────▼──────────────────┐
     │ 6. SESSION CLEANED UP      │
     │    DELETE from Redis       │
     │    Key: call:{call_id}     │
     │                            │
     │ All in-memory data lost!   │
     └─────────────────────────────┘
```

---

## 📁 Database Tables Used (Current)

### Table 1: `conversation_messages` ❌ **MULTIPLE INSERTS**
**Called from:** `app/handlers/call_handler.py::on_call_end()`

```sql
INSERT INTO conversation_messages
(message_id, call_id, sender, message_text, language, created_at)
VALUES (%s, %s, %s, %s, %s, %s)
```

**Characteristics:**
- ✅ One row PER MESSAGE
- ✅ Repeats for EACH message in conversation array
- ✅ Example: 10 customer/AI exchanges = **10 INSERT queries**
- ✅ Stores individual messages with timestamps

### Table 2: `conversation_history` ✅ **SINGLE INSERT**
**Called from:** `app/services/conversation_history_service.py::save_conversation()`

```sql
INSERT INTO conversation_history 
(call_id, userid, caller_number, conversation_text, detected_language,
 call_duration, call_arrived_time, call_start_time, call_end_time)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    conversation_text = %s,
    detected_language = %s,
    call_duration = %s
```

**Characteristics:**
- ✅ **ONE INSERT per call**
- ✅ Full conversation concatenated as single TEXT field
- ✅ Stores call metadata (duration, times, language)
- ✅ Uses ON DUPLICATE KEY UPDATE (idempotent)

### Table 3: `customer_requirements` ✅ **SINGLE INSERT**
**Called from:** `app/services/requirement_tools_service.py::complete_requirements()`

```sql
INSERT INTO customer_requirements
(call_id, customer_name, company_name, location, 
 interested_products, required_quantity, business_requirement,
 bulk_and_other_requirements, is_complete, source)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
```

**Characteristics:**
- ✅ **ONE INSERT per call**
- ✅ All 7 fields saved in single row
- ✅ One call_id links to one requirement record
- ✅ is_complete flag = True when all fields collected

### Table 4: `conversation_summaries` (Optional)
**Purpose:** Summary metadata for quick reporting

```sql
INSERT INTO conversation_summaries
(call_id, total_messages, user_messages, ai_messages, summary_text)
VALUES (%s, %s, %s, %s, %s)
```

---

## 🔗 Data Relationships (Current State)

```
CALL LIFECYCLE
===============

Call Arrives
    │
    ├─► Redis Session Created
    │   Key: call:{call_id}
    │   TTL: 3600s
    │
    ├─► Conversation Stored (In-Memory)
    │   session["conversation"] = [
    │       {sender, text, timestamp},
    │       {sender, text, timestamp},
    │       ...
    │   ]
    │
    ├─► Requirements Collected (In-Memory)
    │   call_state = {
    │       customer_name: "...",
    │       company_name: "...",
    │       location: "...",
    │       products: [...],
    │       quantity: "...",
    │       business_use: "...",
    │       bulk: "..."
    │   }
    │
    Call Ends
    │
    ├─► Multiple Saves Triggered:
    │   
    │   1. CONVERSATION MESSAGES
    │      For each message in session["conversation"]:
    │          INSERT INTO conversation_messages
    │          (message_id, call_id, sender, message_text, ...)
    │      
    │      ✅ Linked by: call_id (FK)
    │      ✅ Stored in: conversation_messages table
    │
    │   2. CONVERSATION HISTORY
    │      INSERT INTO conversation_history
    │      (call_id, conversation_text, ...)
    │      
    │      ✅ Linked by: call_id (PK/UK)
    │      ✅ Stored in: conversation_history table
    │      ✅ Full transcript: concatenated text
    │
    │   3. CUSTOMER REQUIREMENTS
    │      INSERT INTO customer_requirements
    │      (call_id, customer_name, company_name, ...)
    │      
    │      ✅ Linked by: call_id (FK)
    │      ✅ Stored in: customer_requirements table
    │
    │   4. GOOGLE SHEETS (Optional)
    │      Append row to sheet
    │      Columns: 7 fields + timestamp
    │
    │   5. REDIS SESSION CLEANUP
    │      DELETE call:{call_id}
    │      (In-memory data lost)
    │
    └─► Call Complete


KEY LINKING:
============

✅ ALL records linked by: call_id

conversation_messages.call_id ──────┐
customer_requirements.call_id ──────┼──► ONE CALL_ID
conversation_history.call_id ───────┤
google_sheets.row ──────────────────┘


QUERY VOLUME PER CALL:
======================

Minimum: 3 queries
├─ 1 × INSERT conversation_history
├─ 1 × INSERT customer_requirements
└─ 1 × Sheets API (if enabled)

Maximum: N + 3 queries (where N = message count)
├─ N × INSERT conversation_messages
├─ 1 × INSERT conversation_history
├─ 1 × INSERT customer_requirements
└─ 1 × Sheets API (if enabled)

Example (10 messages):
├─ 10 × INSERT conversation_messages
├─ 1 × INSERT conversation_history
├─ 1 × INSERT customer_requirements
├─ 1 × Sheets API
└─ Total: 13 database operations
```

---

## ⚠️ Current Issues & Disconnects

### Issue 1: Multiple Conversation Message Inserts ❌
**Problem:**
```python
# In call_handler.py::on_call_end()
for message in conversation:  # ⚠️ Loops N times
    insert_sql = """INSERT INTO conversation_messages ..."""
    await execute_insert(insert_sql, (message_id, call_id, ...))
```

**Impact:**
- 10 messages = 10 database queries
- Inefficient
- Slower call cleanup
- More database load

**Solution:**
Use bulk insert instead:
```python
# BETTER: Single query with multiple VALUES
INSERT INTO conversation_messages 
(...) VALUES 
(...), (...), (...), ...  # All at once
```

---

### Issue 2: Duplicate Data Storage ⚠️
**Problem:**
```
conversation_messages table (normalized, 1 row per message)
↓
Full transcript stored in conversation_messages.message_text 
(scattered across multiple rows)

PLUS

conversation_history table (denormalized, 1 row per call)
↓
Full transcript concatenated in conversation_history.conversation_text
(all messages in single TEXT field)
```

**Impact:**
- Same data stored twice (redundant)
- Takes up disk space
- Two sources of truth
- Potential sync issues

**Question:** Which table should be the source of truth?

---

### Issue 3: Session Not Connected to Requirements During Call ⚠️
**Problem:**
```
Redis Session:
- Stores conversation during call
- has: call_id, messages array, etc

Requirement Collection:
- Stored in SEPARATE local storage (call_state dict)
- NOT in Redis session
- Loose connection during call

Call Ends:
- Conversation saved from Redis
- Requirements saved from local storage
- Both use call_id but...
- NO guarantee they're in sync
```

**Impact:**
- If requirements save fails, conversation still saves
- If conversation save fails, requirements still save
- Partial data loss possible
- No atomic transaction

---

### Issue 4: No Call-to-Session-to-Data Traceability ⚠️
**Problem:**
```
No explicit table linking:

calls table (IF IT EXISTS?)
├─ call_id
├─ user_id
├─ caller_number
├─ call_duration
├─ started_at
├─ ended_at
└─ status

MISSING LINK TO:
│
├─ conversation_history
│  ├─ call_id
│  └─ Full transcript
│
├─ conversation_messages
│  ├─ call_id
│  └─ Individual messages
│
└─ customer_requirements
   ├─ call_id
   └─ 7 requirements
```

**Question:** Is there a `calls` table that acts as the master record?

---

## ✅ What IS Connected

### Session Per Call ✅
```
EACH CALL gets:
└─ Unique call_id
   ├─ Redis session: call:{call_id}
   ├─ Conversation messages linked by: call_id
   ├─ Requirements linked by: call_id
   ├─ Conversation history linked by: call_id
   └─ Google Sheets row (timestamp + 7 fields)
```

### Every Record Linkage ✅
```
All stored records connected by: call_id

SELECT * FROM conversation_messages WHERE call_id = 'call_123'
SELECT * FROM customer_requirements WHERE call_id = 'call_123'
SELECT * FROM conversation_history WHERE call_id = 'call_123'

✅ All have same call_id
✅ Can join on call_id
✅ Can query one call's complete data
```

---

## 🔄 Data Flow (Detailed)

### During Call (In-Memory)
```
Time: T0 to T_end

Redis: call:{call_id}
├─ conversation: [
│  ├─ {sender: "ai", text: "Hello", timestamp: T1}
│  ├─ {sender: "customer", text: "My name...", timestamp: T2}
│  ├─ {sender: "ai", text: "Thank you...", timestamp: T3}
│  └─ ... N messages total
│  ]
│
└─ Other session data: user_id, language, etc

LocalStorage (In-Memory): call_state_{call_id}
├─ customer_name: "Rahul Kumar"
├─ company_name: "ABC Traders"
├─ location: "Faridabad"
├─ interested_products: ["Wooden Fork", "Cable Tie"]
├─ required_quantity: "50K + 20K"
├─ business_requirement: "Wholesale"
└─ bulk_and_other_requirements: "Bulk, Monthly"
```

### After Call Ends (Persistent Storage)
```
MySQL Database:

1. conversation_messages table:
   ┌─────────┬────────┬──────┬──────────────────────────┐
   │ id      │ call_id│sender│ message_text             │
   ├─────────┼────────┼──────┼──────────────────────────┤
   │ 1       │ call123│ ai   │ Hello, ...               │
   │ 2       │ call123│ cust │ My name is Rahul Kumar   │
   │ 3       │ call123│ ai   │ Thank you, Rahul...      │
   │ ...     │ ...    │ ...  │ ...                      │
   └─────────┴────────┴──────┴──────────────────────────┘
   
   Total: N rows (one per message)

2. conversation_history table:
   ┌────────┬────────┬──────────────────────────┬──────────┐
   │ call_id│ userid │ conversation_text        │ duration │
   ├────────┼────────┼──────────────────────────┼──────────┤
   │ call123│ 101    │ "AI: Hello...\nCust:..." │ 180      │
   └────────┴────────┴──────────────────────────┴──────────┘
   
   Total: 1 row (full transcript)

3. customer_requirements table:
   ┌────────┬──────────────┬────────────┬──────────┬───────────────┐
   │ call_id│ customer_name│ company_name│ location │ products      │
   ├────────┼──────────────┼────────────┼──────────┼───────────────┤
   │ call123│ Rahul Kumar  │ ABC Traders│Faridabad │Wooden, Cable  │
   └────────┴──────────────┴────────────┴──────────┴───────────────┘
   
   Total: 1 row (7 fields)

4. Redis: DELETED
   call:{call_id} → expired/deleted
   In-memory data cleared

5. Google Sheets (if enabled):
   ┌─────┬──────────┬──────────────┬─────────────┬──────────────┐
   │Date │CustomerN │ CompanyName  │ Location    │ Products     │
   ├─────┼──────────┼──────────────┼─────────────┼──────────────┤
   │ ... │Rahul ... │ ABC Traders  │ Faridabad   │ Wooden, Cable│
   └─────┴──────────┴──────────────┴─────────────┴──────────────┘
   
   Total: 1 row
```

---

## 📋 Summary Table

| Aspect | Status | Details |
|--------|--------|---------|
| **One session per call** | ✅ YES | Each call gets unique Redis session with TTL |
| **One INSERT per call** | ⚠️ PARTIAL | Customer_requirements: 1 INSERT; Conversation_messages: N INSERTs |
| **Everything connected** | ✅ YES | All linked by call_id FK |
| **Data integrity** | ⚠️ MEDIUM | No atomic transaction; partial fails possible |
| **Efficient querying** | ✅ YES | Can get all call data via call_id |
| **Redundant storage** | ✅ NOTED | Same conversation stored in 2 tables |
| **Traceability** | ⚠️ MEDIUM | No master "calls" table; relies on call_id |

---

## 🎯 Recommended Improvements

### Improvement 1: Bulk Insert for Messages ⚡
**Before:**
```python
for message in conversation:
    await execute_insert(query, params)  # N queries
```

**After:**
```python
# Single query with all messages
query = """
    INSERT INTO conversation_messages 
    (message_id, call_id, sender, message_text, language, created_at)
    VALUES (%s, %s, %s, %s, %s, %s),
           (%s, %s, %s, %s, %s, %s),
           ...
"""
await execute_insert(query, all_params)  # 1 query
```

**Benefit:** 10× faster for 10 messages

---

### Improvement 2: Create Master Calls Table 🏗️
**New table:**
```sql
CREATE TABLE calls (
    id INT AUTO_INCREMENT PRIMARY KEY,
    call_id VARCHAR(64) UNIQUE NOT NULL,
    user_id INT NOT NULL,
    caller_number VARCHAR(20),
    dnid VARCHAR(20),
    started_at DATETIME,
    ended_at DATETIME,
    duration_seconds INT,
    language VARCHAR(10),
    status ENUM('active', 'completed', 'failed'),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Foreign keys:
ALTER TABLE conversation_history ADD FOREIGN KEY (call_id) REFERENCES calls(call_id);
ALTER TABLE conversation_messages ADD FOREIGN KEY (call_id) REFERENCES calls(call_id);
ALTER TABLE customer_requirements ADD FOREIGN KEY (call_id) REFERENCES calls(call_id);
```

**Benefit:** Single source of truth for each call

---

### Improvement 3: Atomic Transaction ✅
**Current:**
```python
# Save conversation (might fail)
await save_conversation()

# Save requirements (might fail independently)
await save_requirements()

# If conversation fails, requirements still saves = data inconsistency
```

**Better:**
```python
async with db.transaction():
    # Both succeed or both fail
    await save_conversation()
    await save_requirements()
    await save_to_google_sheets()
    # If ANY fails: ALL rollback
```

**Benefit:** Guaranteed data consistency

---

### Improvement 4: Remove Redundant Storage 📉
**Choose ONE source of truth:**

Option A (Keep conversation_messages):
- Keep individual messages table
- Delete conversation_history table
- Build transcript by joining messages

Option B (Keep conversation_history):
- Keep concatenated transcript table
- Remove conversation_messages table
- Lower disk usage

**Current state:** BOTH = waste of space

---

## 🔐 Verification Queries

To verify current data for a call:

```sql
-- Get all messages from a call
SELECT * FROM conversation_messages 
WHERE call_id = 'call_123' 
ORDER BY created_at;

-- Get full transcript
SELECT call_id, conversation_text FROM conversation_history 
WHERE call_id = 'call_123';

-- Get collected requirements
SELECT * FROM customer_requirements 
WHERE call_id = 'call_123';

-- Check if all 7 fields collected
SELECT 
    CASE WHEN is_complete = 1 THEN 'YES' ELSE 'NO' END as all_fields_collected,
    customer_name, company_name, location, interested_products, 
    required_quantity, business_requirement, bulk_and_other_requirements
FROM customer_requirements 
WHERE call_id = 'call_123';
```

---

## 📌 Key Findings Summary

✅ **YES:** Every call has its own unique session  
✅ **YES:** All data is connected via call_id  
❌ **NO:** Not one INSERT per call (conversation has multiple INSERTs)  
⚠️ **PARTIAL:** Some inefficiencies and redundancy exist  

**Recommendation:** Implement the 4 improvements above for production-grade system.

