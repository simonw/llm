================================================================================
  COST ESTIMATION FEATURE - FINAL IMPLEMENTATION PLAN
================================================================================

STATUS: READY TO IMPLEMENT ✅

WHAT CHANGED IN FINAL REVISION
-------------------------------
✅ Do NOT bundle pricing data with package
✅ Fetch from llm-prices.com on first use
✅ Cache in user_dir() / "historical-v1.json"
✅ 24-hour cache refresh (not 7 days)
✅ Both sync and async Response.cost() methods
✅ Integrated with -u/--usage flag (not separate commands)


QUICK START
-----------
1. READ: FINAL_PLAN_SUMMARY.md (complete overview)
2. READ: CACHING_UPDATE.md (caching implementation details)
3. IMPLEMENT: Follow IMPLEMENTATION_CHECKLIST_FINAL.md


USER EXPERIENCE
---------------
$ llm "Hello world" -m gpt-4 -u
Hello! How can I help you today?

Token usage: 10 input, 5 output, Cost: $0.000450 ($0.000300 input, $0.000150 output)
                                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                       NEW: Automatic cost estimation!


WHAT GETS BUILT
---------------
New Files:
  ✅ llm/costs.py                  CostEstimator + AsyncCostEstimator
  ✅ tests/test_costs.py           Comprehensive test suite

Modified Files:
  ✅ llm/models.py                 Response.cost() + AsyncResponse.cost()
  ✅ llm/utils.py                  Enhanced token_usage_string()
  ✅ llm/cli.py                    Updated usage display (2 places)
  ✅ llm/__init__.py               Export new classes

Runtime (User Directory):
  ✅ ~/.local/share/io.datasette.llm/historical-v1.json  (cached pricing)


CACHING STRATEGY
----------------
First Use:
  → Fetch from https://www.llm-prices.com/historical-v1.json
  → Save to user_dir()/historical-v1.json
  → Display cost

Subsequent Uses (< 24 hours):
  → Load from cache (instant)
  → Display cost

After 24 Hours:
  → Try to fetch fresh data
  → If success: update cache
  → If failure: use stale cache
  → Display cost either way

Network Unavailable:
  → Use stale cache if available
  → Otherwise: skip cost silently (no error)


SYNC vs ASYNC
-------------
Response.cost()              → Synchronous (may block on first fetch)
AsyncResponse.cost()         → Asynchronous (proper async/await)

Both use the same caching mechanism, just different I/O patterns.


ARCHITECTURE SUMMARY
--------------------
User runs: llm "prompt" -m gpt-4 -u
    ↓
token_usage_string() called
    ↓
get_default_estimator() (singleton)
    ↓
First use? → Fetch + Cache
Cached?    → Load cache
    ↓
calculate_cost()
    ↓
Display: "Token usage: X input, Y output, Cost: $Z"


KEY FILES
---------
Essential Documentation:
  • FINAL_PLAN_SUMMARY.md               Complete overview
  • CACHING_UPDATE.md                   Detailed caching implementation
  • IMPLEMENTATION_CHECKLIST_FINAL.md   Step-by-step tasks
  • COMPARISON.md                       Why this approach

Reference:
  • COST_ESTIMATION_PLAN.md             Original technical plan
  • COST_ARCHITECTURE.md                Architecture diagrams
  • EXAMPLE_TESTS.py                    Test examples

Superseded (Do Not Use):
  • IMPLEMENTATION_CHECKLIST_REVISED.md (use FINAL instead)
  • IMPLEMENTATION_CHECKLIST.md         (use FINAL instead)


IMPLEMENTATION PHASES
---------------------
Phase 1: Core (2 days)
  • Create llm/costs.py
  • CostEstimator (sync)
  • AsyncCostEstimator (async)
  • Cache management (24h TTL)
  • Cost calculation
  • Unit tests

Phase 2: Integration (0.5 day)
  • Response.cost() methods
  • Update exports
  • Integration tests

Phase 3: CLI (0.5 day)
  • Enhance token_usage_string()
  • Update CLI calls (2 places)
  • CLI tests

Phase 4: Polish (1 day)
  • Documentation
  • Error handling
  • Performance testing

TOTAL: 4 days


TESTING STRATEGY
----------------
Unit Tests:
  • Fetch/cache/refresh logic
  • Model ID matching
  • Cost calculations
  • Error handling

Integration Tests:
  • Response.cost() sync
  • AsyncResponse.cost() async
  • CLI integration
  • Network scenarios

Manual Testing:
  # First use
  rm ~/.local/share/io.datasette.llm/historical-v1.json
  llm "Test" -m gpt-4 -u
  
  # Cached use
  llm "Test" -m gpt-4 -u
  
  # Stale cache
  touch -t 202401010000 ~/.local/share/io.datasette.llm/historical-v1.json
  llm "Test" -m gpt-4 -u


ERROR HANDLING
--------------
✅ Network unavailable → Use stale cache or skip cost
✅ Cache missing + network error → Skip cost silently
✅ Unknown model → Skip cost, show tokens only
✅ Invalid pricing data → Log warning, skip cost
✅ Never break existing functionality


SUCCESS CRITERIA
----------------
[x] Planning complete
[x] Caching strategy defined
[x] Sync/async approach decided
[ ] Pricing fetches on first use
[ ] Cache saves to correct location
[ ] 24-hour refresh works
[ ] Cost appears with -u flag
[ ] Both sync and async work
[ ] Tests >90% coverage
[ ] No breaking changes


KEY METRICS
-----------
Code to write:     ~600 lines (400 core + 200 integration)
Tests to write:    ~500 lines
Files modified:    4 (models.py, utils.py, cli.py, __init__.py)
Files created:     2 (costs.py, test_costs.py)
Implementation:    4 days estimated
Performance:       First use ~200-500ms, subsequent ~12ms
Cache size:        ~17KB (historical-v1.json)


NEXT STEPS
----------
1. Review FINAL_PLAN_SUMMARY.md
2. Review CACHING_UPDATE.md
3. Open IMPLEMENTATION_CHECKLIST_FINAL.md
4. Start Phase 1: Create llm/costs.py


RESOURCES
---------
Pricing data: https://www.llm-prices.com/historical-v1.json
LLM project:  https://github.com/simonw/llm
LLM docs:     https://llm.datasette.io/


================================================================================
                      READY TO START IMPLEMENTATION! 🚀
================================================================================
