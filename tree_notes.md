# Tree-Structured Conversations - Design Notes

## Current State

The LLM tool currently stores conversations as linear sequences:
- `conversations` table: Stores conversation metadata (id, name, model)
- `responses` table: Stores individual responses with a `conversation_id` foreign key
- All responses in a conversation are treated as a linear sequence

## Proposed Change

Add a `parent_response_id` column to the `responses` table to enable tree-structured conversations where:
- Each response can have zero or one parent response
- Multiple responses can share the same parent (branching)
- This allows exploring different conversation paths from any point

## Schema Changes

### Migration to add parent_response_id

```sql
ALTER TABLE responses ADD COLUMN parent_response_id TEXT;
ALTER TABLE responses ADD FOREIGN KEY (parent_response_id) REFERENCES responses(id);
```

## Use Cases

1. **Branching conversations**: From any point in a conversation, create multiple alternative continuations
2. **Conversation exploration**: Try different prompts or approaches from the same context
3. **A/B testing**: Compare different model responses or prompt variations
4. **Conversation rollback**: Go back to an earlier point and take a different path
5. **Tree visualization**: Display conversation history as a tree structure

## Design Decisions

### Questions to explore:
1. Should `parent_response_id` be nullable? (YES - root responses have no parent)
2. Can a response belong to multiple conversations? (Current: NO - each response has one conversation_id)
3. How to handle the relationship between parent_response_id and conversation_id?
   - Option A: Both parent and child must be in same conversation
   - Option B: Creating a child in a different conversation is allowed
   - **Decision**: Option A - enforce same conversation for integrity

4. How to identify "root" responses in a conversation?
   - Root responses: parent_response_id IS NULL
   - Can have multiple roots in one conversation (multiple starting points)

5. What happens to the tree when a response is deleted?
   - Cascade delete children?
   - Set children's parent_response_id to NULL?
   - Prevent deletion if it has children?
   - **Decision**: TBD based on testing

## Implementation Plan

### Phase 1: Schema and Migration
- [x] Create migration function to add parent_response_id column
- [x] Test migration on existing database
- [x] Ensure foreign key constraint works correctly

### Phase 2: Basic Tree Operations
- [x] Create helper functions to:
  - [x] Get children of a response
  - [x] Get parent of a response
  - [x] Get siblings (responses with same parent)
  - [x] Get the full path from root to a response
  - [x] Get all descendants of a response
  - [x] Calculate depth
  - [x] Find root nodes
  - [x] Find leaf nodes
  - [x] Get tree size
  - [x] Get conversation summary statistics
  - [x] Calculate branching factor
  - [x] Visualize tree structure
  
### Phase 3: Testing
- [x] Write pytest tests for tree operations (15 tests total)
- [x] Test branching scenarios
- [x] Test traversal algorithms
- [x] Test with multiple roots
- [x] Test depth calculation
- [x] Test leaf/root identification
- [x] Test statistics gathering
- [x] Test tree visualization

### Phase 4: API/CLI Integration (Future)
- [ ] Update Response.log() to accept parent_response_id
- [ ] CLI commands to create branching conversations
- [ ] Interactive tree navigation tools

## Test Scenarios

### Test 1: Simple Linear Chain
```
Root -> A -> B -> C
```
Each response has exactly one parent (except Root)

### Test 2: Simple Branch
```
       -> B
Root <
       -> C
```
Two responses share the same parent

### Test 3: Complex Tree
```
         -> C
    -> B <
   /     -> D
Root 
   \     -> F
    -> E <
         -> G
```
Multiple levels and multiple branches

### Test 4: Multiple Roots
```
Root1 -> A -> B

Root2 -> X -> Y
```
Two separate trees in the same conversation

## Notes and Observations

*This section will be populated as we experiment*

### 2025-09-27: Initial Implementation and Testing

**Migration Success:**
- Successfully added `parent_response_id` column to responses table
- Foreign key constraint to self-reference works correctly
- Column is nullable, allowing root responses

**Tree Operations Tested:**
1. ✅ Linear chains work correctly (A -> B -> C)
2. ✅ Branching works (parent with multiple children)
3. ✅ Multiple roots in one conversation supported
4. ✅ Can traverse from leaf to root (get ancestors)
5. ✅ Can get all children of a node
6. ✅ Can get all descendants (entire subtree)
7. ✅ Can get siblings (nodes with same parent)

**Helper Functions Implemented:**
- `get_children(db, response_id)` - Direct children
- `get_path_to_root(db, response_id)` - Ancestor path
- `get_all_descendants(db, response_id)` - Entire subtree
- `get_siblings(db, response_id)` - Same-parent responses

**Design Insights:**
1. The nullable `parent_response_id` naturally supports roots
2. Multiple roots per conversation work without issues
3. Self-referential foreign key in sqlite-utils is straightforward
4. Cycle prevention is important - added visited set to path traversal
5. All responses still need `conversation_id` - this maintains conversation boundaries

**Next Steps:**
- Test edge cases (cycles, orphaned nodes)
- Add depth/level calculation
- Test tree visualization queries
- Consider adding indexes for performance
- Test with actual LLM integration

### 2025-09-27: Complete Implementation

**All Core Features Implemented:**
- ✅ Migration m022_parent_response_id successfully adds the column
- ✅ 15 comprehensive tests covering all tree operations
- ✅ Full tree_utils.py module with helper functions
- ✅ Tree visualization with print_tree()

**Utility Functions Created (tree_utils.py):**
1. `get_children(db, response_id)` - Get direct children
2. `get_parent(db, response_id)` - Get parent response
3. `get_siblings(db, response_id)` - Get responses with same parent
4. `get_path_to_root(db, response_id)` - Get ancestor chain
5. `get_all_descendants(db, response_id)` - Get entire subtree
6. `get_depth(db, response_id)` - Calculate distance from root
7. `get_root_nodes(db, conversation_id)` - Find all roots
8. `get_leaf_nodes(db, conversation_id)` - Find all leaves
9. `get_tree_size(db, root_id)` - Count nodes in tree
10. `get_conversation_summary(db, conversation_id)` - Comprehensive stats
11. `get_branching_factor(db, conversation_id)` - Average children per node
12. `print_tree(db, response_id)` - Text visualization

**Test Coverage:**
- Linear chains (simple progression)
- Branching (multiple children from one parent)
- Multiple roots (forest structure)
- Path traversal (root to leaf, leaf to root)
- Depth calculation
- Leaf/root identification
- Sibling relationships
- Tree statistics (size, depth, branching factor)
- Forest with multiple independent trees
- Tree visualization

**Performance Considerations:**
- All queries use indexed columns (id, parent_response_id)
- Recursive functions include cycle detection (visited sets)
- Efficient SQL queries for bulk operations
- Consider adding index on parent_response_id for large trees

**Key Insights:**
1. **Natural Structure**: The nullable parent_response_id elegantly supports both roots and children
2. **Flexibility**: Multiple roots per conversation enable diverse usage patterns
3. **Query Efficiency**: SQL's recursive capabilities (or Python recursion) handle tree traversal well
4. **Visualization**: Simple text representation makes structure immediately clear
5. **Statistics**: Rich analytics possible (depth, branching factor, size)
6. **Safety**: Cycle detection essential for robustness

**Potential Use Cases:**
1. **Conversation Exploration**: Try different continuations from any point
2. **A/B Testing**: Compare model responses or prompt variations
3. **Rollback and Branch**: Go back and take different paths
4. **Multi-path Reasoning**: Explore multiple solution approaches
5. **Conversation Debugging**: Understand complex interaction patterns
6. **Training Data**: Generate diverse conversation examples

**Future Enhancements:**
- Add created_at timestamps to track branch timing
- Implement "squash" operation to collapse branches
- Add metadata to track why branches were created
- CLI commands for interactive tree navigation
- Web UI for visual tree exploration
- Export to graph formats (DOT, JSON)
- Diff tool to compare branches
- Merge operations for combining branches

**Recommendations for Integration:**
1. Add `parent_response_id` parameter to Response.log()
2. Create CLI commands:
   - `llm branch <response-id>` - Create new branch from point
   - `llm tree <conversation-id>` - Visualize tree structure
   - `llm leaves <conversation-id>` - List all leaf nodes
   - `llm path <response-id>` - Show path to root
3. Consider adding UI indicators for branches in chat interface
4. Implement "continue from here" feature in CLI

**Technical Debt/TODOs:**
- [ ] Add database indexes for parent_response_id
- [ ] Consider cascade delete behavior
- [ ] Add validation to prevent cycles at insertion time
- [ ] Document tree operations in main docs
- [ ] Add tree operations to Python API
- [ ] Performance testing with large trees (>1000 nodes)

