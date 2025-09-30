# Message Array Matching for Tree Conversations

## Problem Statement

When calling `model.prompt(messages=[...])` with a full message array, we want to:
1. Check if this exact conversation path already exists in the database
2. If yes, return the existing response or branch from there
3. If no, create new responses and link them to the tree
4. Do this efficiently without scanning all responses

## Key Challenge: Matching Messages

Given a messages array like:
```python
[
    llm.System("you are a useful assistant"),
    llm.User("Capital of France?"),
    llm.Assistant("Paris"),
    llm.User("Germany?")
]
```

We need to find if there's an existing conversation path:
- Root: System("you are a useful assistant") + User("Capital of France?") → Response("Paris")
- Child: User("Germany?") → Response(???)

## Design Questions

### 1. What to Hash?
- ✅ System message content
- ✅ User message content  
- ✅ Assistant message content (for matching, not predicting)
- ❓ Attachments/images - hash the binary content?
- ❓ Tool calls - hash the function name + arguments?
- ❓ Tool results - hash the output?
- ❌ Timestamps - these should NOT affect matching
- ❌ Model used - same conversation, different models should be separate trees
- ❓ Options (temperature, etc.) - should these affect matching?

### 2. Where to Store Hashes?
Options:
- A) Store hash on each response row
- B) Store hash on prompt/response pairs
- C) Store hash representing entire path from root
- D) Combination approach

### 3. Hash Scope
- **Per-response hash**: Hash of (system + prompt) that created this response
- **Path hash**: Cumulative hash from root to this node
- **Content hash**: Hash of just the response content

### 4. Timestamp Handling
- Store actual timestamp separately
- Don't include in hash
- Use for display/sorting only

## Initial Design Proposal

### Schema Addition

```sql
ALTER TABLE responses ADD COLUMN prompt_hash TEXT;
ALTER TABLE responses ADD COLUMN path_hash TEXT;
CREATE INDEX idx_responses_prompt_hash ON responses(prompt_hash);
CREATE INDEX idx_responses_path_hash ON responses(path_hash);
```

### Hash Strategy

**prompt_hash**: Hash of the input that created this response
- For simple text: hash(system + prompt)
- For images: hash(system + prompt + image_content_hash)
- For tools: hash(system + prompt + tool_results)

**path_hash**: Cumulative hash from root
- Represents the entire conversation history
- path_hash = hash(parent.path_hash + current.prompt_hash)
- Root nodes: path_hash = prompt_hash

## Hashing Considerations

### What to Include in Hash

**Stable (include in hash):**
- System message text
- User message text
- Assistant message text (when matching existing)
- Tool call names and arguments
- Tool result outputs
- Image content (via content hash)
- Attachment content (via content hash)

**Unstable (exclude from hash):**
- Timestamps
- Response IDs
- Duration
- Token counts
- Metadata about the call

### Options/Parameters

**Should temperature affect matching?**
- Scenario: Same prompt with temperature=0 vs temperature=1
- Different temperatures could yield different responses
- **Decision**: Include relevant options in hash
- Create separate branches for different option sets

## Algorithm: Finding Existing Path

Given messages array: [Sys, User1, Asst1, User2]

```python
def find_or_create_path(db, conversation_id, messages):
    """
    Find existing path or create new responses.
    Returns the response_id of the last message.
    """
    current_parent = None
    
    for i in range(0, len(messages), 2):  # Process pairs
        if i + 1 >= len(messages):
            break  # Incomplete pair
            
        # Get prompt (User or System+User)
        prompt_msg = messages[i]
        if isinstance(prompt_msg, llm.System):
            system = prompt_msg.content
            prompt_msg = messages[i + 1]
            prompt = prompt_msg.content
            i += 1
        else:
            system = None
            prompt = prompt_msg.content
        
        # Get expected response
        if i + 1 < len(messages) and isinstance(messages[i + 1], llm.Assistant):
            expected_response = messages[i + 1].content
        else:
            expected_response = None
        
        # Calculate prompt hash
        prompt_hash = calculate_prompt_hash(system, prompt, attachments, tools)
        
        # Look for existing response with this prompt_hash and parent
        existing = db.execute("""
            SELECT id, response 
            FROM responses 
            WHERE conversation_id = ?
            AND parent_response_id IS ?
            AND prompt_hash = ?
        """, [conversation_id, current_parent, prompt_hash]).fetchone()
        
        if existing and expected_response:
            # Verify response matches
            if existing[1] == expected_response:
                current_parent = existing[0]
                continue
        
        # No match found - need to create new response
        # ...
```

## Complex Content Hashing

### Images
```python
def hash_image_attachment(attachment):
    if attachment.content:
        return hashlib.sha256(attachment.content).hexdigest()
    elif attachment.url:
        # Store URL but flag that content may change
        return f"url:{hashlib.sha256(attachment.url.encode()).hexdigest()}"
    else:
        return hashlib.sha256(attachment.path.encode()).hexdigest()
```

### Tool Calls
```python
def hash_tool_call(tool_call):
    data = {
        'name': tool_call.name,
        'arguments': tool_call.arguments,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
```

### Tool Results
```python  
def hash_tool_result(tool_result):
    data = {
        'name': tool_result.name,
        'output': tool_result.output,
    }
    # Include attachment hashes if present
    if tool_result.attachments:
        data['attachments'] = [hash_image_attachment(a) for a in tool_result.attachments]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
```

## Edge Cases

### 1. Partial Match
Messages: [User1, Asst1, User2]
Existing: [User1, Asst1] with different Asst1 response

**Solution**: Create branch from User1 with different response

### 2. Multiple Models
Same prompt, different models
**Solution**: prompt_hash doesn't include model, so they share the same tree

### 3. Non-deterministic Responses
Same prompt, same model, different responses (temperature > 0)
**Solution**: 
- Multiple responses with same parent + prompt_hash
- Tree shows different attempts
- Can compare results

### 4. Streaming vs Non-streaming
Same prompt, different streaming setting
**Solution**: streaming is implementation detail, not conversation content

## Experiments to Run

1. ✅ Test basic hash calculation
2. ✅ Test hash with images
3. ✅ Test hash with tool calls
4. ✅ Test matching algorithm
5. ✅ Test path hash calculation
6. ✅ Test with real conversation scenarios

## Notes

*Will be filled in as experiments progress*

### Implementation Complete ✅

**Date:** September 27, 2025

**Schema Changes:**
- Added 3 hash columns to responses table via migration `m023_response_hashing`
- `prompt_hash`: Hash of the input that created this response
- `response_hash`: Hash of the response content  
- `path_hash`: Cumulative hash representing path from root

**Indexes Created:**
- Index on `prompt_hash` for fast lookup
- Index on `path_hash` for finding exact conversation paths
- Composite index on `(conversation_id, parent_response_id, prompt_hash)` for matching children

**Test Results: 23/23 tests passing ✅**

### Key Findings

#### 1. Hash Stability
- Text hashing is straightforward and deterministic
- Binary content (images) hashed via SHA-256 of bytes
- Tool calls/results hashed via JSON serialization (sorted keys)
- Timestamps explicitly EXCLUDED from hashes

#### 2. Hash Composition

**prompt_hash includes:**
- System message text
- User prompt text
- Attachment hashes (content, URL, or path)
- Tool call hashes (name + arguments)
- Tool result hashes (name + output + attachment hashes)
- Deterministic options only (temperature=0, max_tokens, stop_sequences)

**prompt_hash excludes:**
- Timestamps (stored separately)
- Non-deterministic options (temperature > 0)
- Response IDs
- Token counts
- Duration metrics

#### 3. Path Hash Strategy

**Two-level hashing:**
1. **prompt_hash**: Identifies unique input context
2. **path_hash**: Identifies unique conversation path

**Path hash calculation:**
```
Root node: path_hash = prompt_hash
Child node: path_hash = hash(parent.path_hash + ":" + current.prompt_hash)
```

This creates a unique fingerprint for every path through the tree.

#### 4. Matching Algorithm

```python
# Find existing response by:
1. conversation_id (which conversation)
2. parent_response_id (position in tree)  
3. prompt_hash (what input created it)

# If found: reuse existing response
# If not found: create new response
```

#### 5. Handling Non-Determinism

**Same prompt, different responses:**
- Temperature > 0 can produce different outputs
- Multiple responses can share same (parent, prompt_hash)
- Tree naturally represents these alternatives
- Query returns first match (LIMIT 1) or all for comparison

**Example:**
```
Root: "Tell me a joke"
  -> Response A: "Why did chicken..." (first attempt)
  -> Response B: "What do you call..." (second attempt)
```

Both have same parent and prompt_hash but different response_hash.

#### 6. Attachment/Tool Hashing

**Images:**
- If content available: hash the bytes
- If URL only: hash the URL (note: content may change)
- If path only: hash the path (note: file may change)

**Tools:**
- Tool calls: hash(name + arguments)
- Tool results: hash(name + output + [attachment_hashes])

#### 7. Timestamp Strategy

**Problem:** Need timestamps for auditing but they break matching

**Solution:**
- Store timestamp in `datetime_utc` column
- EXCLUDE from all hashes
- Use for display and sorting only
- Each call records its own timestamp even if reusing response

**Benefits:**
- Can track when each call was made
- Can see response was reused (same hash, different timestamp)
- Can analyze response caching patterns

### Use Cases Enabled

#### 1. Efficient Message Array Handling
```python
# First call
response = model.prompt(messages=[
    llm.System("You are helpful"),
    llm.User("Capital of France?")
])
# Creates: root response

# Second call with same context
response = model.prompt(messages=[
    llm.System("You are helpful"),
    llm.User("Capital of France?")
])
# Finds: existing root, reuses it

# Third call extending conversation
response = model.prompt(messages=[
    llm.System("You are helpful"),
    llm.User("Capital of France?"),
    llm.Assistant("Paris"),
    llm.User("Germany?")
])
# Finds: root, verifies "Paris" matches, creates/finds child for "Germany?"
```

#### 2. Conversation Caching
- Avoid redundant API calls for identical prompts
- Track which responses were generated vs cached
- Analyze cache hit rates

#### 3. A/B Testing
- Same prompt, different models
- Same prompt, different temperature
- Compare results in tree structure

#### 4. Debugging
- Trace exact conversation path via path_hash
- Find all instances of a particular prompt
- Compare different response branches

### Performance Considerations

**Index Strategy:**
- Primary lookup: (conversation_id, parent_response_id, prompt_hash)
- Alternative: path_hash for finding exact paths
- All hash columns indexed for fast queries

**Hash Collision:**
- SHA-256: effectively zero collision probability
- 64 hex characters = 2^256 possible values
- More hashes exist than atoms in universe

**Storage Overhead:**
- 3 hash columns × 64 bytes = 192 bytes per response
- Negligible compared to prompt/response content
- Enables O(1) lookups vs O(n) content comparison

### Edge Cases Handled

✅ Images with same content but different paths
✅ URLs that may point to changing content  
✅ Tool calls with complex nested arguments
✅ Multiple responses with same prompt (non-deterministic)
✅ Empty/null values in various fields
✅ Unicode text in prompts/responses
✅ Very long prompts (hashed efficiently)

### Integration Path

**Phase 1: Schema (Complete)**
- ✅ Add hash columns
- ✅ Create indexes
- ✅ Test hashing functions

**Phase 2: Response Logging (Next)**
- Calculate hashes when logging responses
- Populate hash columns automatically
- Backfill existing responses

**Phase 3: Matching API (Next)**
- Implement find_or_create_from_messages()
- Integrate with model.prompt()
- Handle cache hits/misses

**Phase 4: CLI/UI (Future)**
- Show cache hit indicators
- Display path hashes in logs
- Visualize response reuse

### Open Questions Resolved

❓ **Include timestamps in hash?**
✅ NO - timestamps stored separately

❓ **Include model name in hash?**
✅ NO - same conversation, different models = separate branches

❓ **Include temperature in hash?**
✅ ONLY if temperature=0 (deterministic)

❓ **How to hash images?**
✅ Hash content bytes, or URL/path if no content

❓ **Handle tool calls?**
✅ Hash function name + arguments as JSON

❓ **Multiple responses with same prompt?**
✅ Allowed - tree shows alternatives

### Recommendations

1. **Always calculate hashes**: Even for new responses
2. **Index all hash columns**: Essential for performance
3. **Use path_hash for exact matches**: Fast full-path lookups
4. **Log cache hits separately**: Track reuse metrics
5. **Consider hash column in UI**: Show when response was cached

### Next Steps

1. Create migration for hash columns ✅
2. Update Response.log() to calculate hashes
3. Implement find_or_create_from_messages()
4. Test with real LLM API calls
5. Add cache hit tracking
6. Update documentation
