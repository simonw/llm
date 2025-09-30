"""
Tests for message hashing and matching functionality.
"""

import pytest
import sqlite_utils
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from message_hashing import (
    hash_content,
    hash_binary,
    hash_attachment,
    hash_tool_call,
    hash_tool_result,
    calculate_prompt_hash,
    calculate_response_hash,
    calculate_path_hash,
    find_matching_response,
)
from llm.migrations import migrate


@pytest.fixture
def hash_db():
    """Create a test database with migrations applied"""
    db = sqlite_utils.Database(memory=True)
    migrate(db)

    # Migrations now include hash columns (m023_response_hashing)
    # Verify they exist
    assert "prompt_hash" in db["responses"].columns_dict
    assert "response_hash" in db["responses"].columns_dict
    assert "path_hash" in db["responses"].columns_dict

    return db


def test_hash_content_deterministic():
    """Test that hashing the same content produces the same hash"""
    content = "Hello, world!"
    hash1 = hash_content(content)
    hash2 = hash_content(content)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 produces 64 hex characters


def test_hash_content_different():
    """Test that different content produces different hashes"""
    hash1 = hash_content("Hello")
    hash2 = hash_content("World")

    assert hash1 != hash2


def test_hash_binary_deterministic():
    """Test that hashing binary data is deterministic"""
    data = b"Binary data"
    hash1 = hash_binary(data)
    hash2 = hash_binary(data)

    assert hash1 == hash2


def test_hash_attachment_with_content():
    """Test hashing an attachment with binary content"""
    attachment = {"type": "image/png", "content": b"fake image data"}

    hash1 = hash_attachment(attachment)
    hash2 = hash_attachment(attachment)

    assert hash1 == hash2
    assert hash1.startswith("content:")


def test_hash_attachment_with_url():
    """Test hashing an attachment with URL"""
    attachment = {"type": "image/png", "url": "https://example.com/image.png"}

    hash1 = hash_attachment(attachment)
    assert hash1.startswith("url:")


def test_hash_attachment_with_path():
    """Test hashing an attachment with file path"""
    attachment = {"type": "image/png", "path": "/path/to/image.png"}

    hash1 = hash_attachment(attachment)
    assert hash1.startswith("path:")


def test_hash_tool_call():
    """Test hashing a tool call"""
    tool_call = {"name": "calculate", "arguments": {"expression": "2 + 2"}}

    hash1 = hash_tool_call(tool_call)
    hash2 = hash_tool_call(tool_call)

    assert hash1 == hash2

    # Different arguments should produce different hash
    tool_call2 = {"name": "calculate", "arguments": {"expression": "3 + 3"}}
    hash3 = hash_tool_call(tool_call2)
    assert hash1 != hash3


def test_hash_tool_result():
    """Test hashing a tool result"""
    tool_result = {"name": "calculate", "output": "4"}

    hash1 = hash_tool_result(tool_result)
    hash2 = hash_tool_result(tool_result)

    assert hash1 == hash2


def test_hash_tool_result_with_attachments():
    """Test hashing a tool result with attachments"""
    tool_result = {
        "name": "generate_image",
        "output": "Image generated",
        "attachments": [{"type": "image/png", "content": b"image data"}],
    }

    hash1 = hash_tool_result(tool_result)
    hash2 = hash_tool_result(tool_result)

    assert hash1 == hash2


def test_calculate_prompt_hash_simple():
    """Test calculating prompt hash for simple text prompt"""
    hash1 = calculate_prompt_hash(system="You are helpful", prompt="What is 2+2?")
    hash2 = calculate_prompt_hash(system="You are helpful", prompt="What is 2+2?")

    assert hash1 == hash2
    assert len(hash1) == 64


def test_calculate_prompt_hash_different_prompts():
    """Test that different prompts produce different hashes"""
    hash1 = calculate_prompt_hash(prompt="What is 2+2?")
    hash2 = calculate_prompt_hash(prompt="What is 3+3?")

    assert hash1 != hash2


def test_calculate_prompt_hash_with_attachments():
    """Test prompt hash with attachments"""
    attachments = [
        {"type": "image/png", "content": b"image1"},
        {"type": "image/png", "content": b"image2"},
    ]

    hash1 = calculate_prompt_hash(
        prompt="Describe these images", attachments=attachments
    )

    # Same attachments, same hash
    hash2 = calculate_prompt_hash(
        prompt="Describe these images", attachments=attachments
    )
    assert hash1 == hash2

    # Different attachments, different hash
    hash3 = calculate_prompt_hash(
        prompt="Describe these images",
        attachments=[{"type": "image/png", "content": b"different"}],
    )
    assert hash1 != hash3


def test_calculate_prompt_hash_with_tools():
    """Test prompt hash with tool calls and results"""
    tool_calls = [{"name": "calculate", "arguments": {"expr": "2+2"}}]
    tool_results = [{"name": "calculate", "output": "4"}]

    hash1 = calculate_prompt_hash(
        prompt="What's next?", tool_calls=tool_calls, tool_results=tool_results
    )

    hash2 = calculate_prompt_hash(
        prompt="What's next?", tool_calls=tool_calls, tool_results=tool_results
    )

    assert hash1 == hash2


def test_calculate_prompt_hash_options_deterministic():
    """Test that deterministic options are included in hash"""
    hash1 = calculate_prompt_hash(
        prompt="Test", options={"temperature": 0, "max_tokens": 100}
    )

    hash2 = calculate_prompt_hash(
        prompt="Test", options={"temperature": 0, "max_tokens": 100}
    )

    assert hash1 == hash2


def test_calculate_prompt_hash_options_nondeterministic_ignored():
    """Test that non-deterministic options don't affect hash"""
    hash1 = calculate_prompt_hash(
        prompt="Test", options={"temperature": 0.7}  # Non-deterministic
    )

    hash2 = calculate_prompt_hash(
        prompt="Test", options={"temperature": 0.9}  # Different non-deterministic
    )

    hash3 = calculate_prompt_hash(
        prompt="Test"
        # No options
    )

    # Non-deterministic temperature shouldn't be included
    assert hash1 == hash2 == hash3


def test_calculate_response_hash():
    """Test hashing response content"""
    hash1 = calculate_response_hash("This is a response")
    hash2 = calculate_response_hash("This is a response")
    hash3 = calculate_response_hash("Different response")

    assert hash1 == hash2
    assert hash1 != hash3


def test_calculate_path_hash_root():
    """Test path hash for root node"""
    prompt_hash = "abc123"
    path_hash = calculate_path_hash(None, prompt_hash)

    # Root node: path hash equals prompt hash
    assert path_hash == prompt_hash


def test_calculate_path_hash_child():
    """Test path hash for child node"""
    root_prompt_hash = "abc123"
    root_path_hash = calculate_path_hash(None, root_prompt_hash)

    child_prompt_hash = "def456"
    child_path_hash = calculate_path_hash(root_path_hash, child_prompt_hash)

    # Child should have different path hash
    assert child_path_hash != root_path_hash
    assert child_path_hash != child_prompt_hash

    # Should be deterministic
    child_path_hash2 = calculate_path_hash(root_path_hash, child_prompt_hash)
    assert child_path_hash == child_path_hash2


def test_calculate_path_hash_chain():
    """Test path hash through a chain of responses"""
    # Create a chain: root -> a -> b -> c
    prompt_hashes = ["hash_root", "hash_a", "hash_b", "hash_c"]
    path_hashes = []

    parent_path_hash = None
    for prompt_hash in prompt_hashes:
        path_hash = calculate_path_hash(parent_path_hash, prompt_hash)
        path_hashes.append(path_hash)
        parent_path_hash = path_hash

    # Each should be unique
    assert len(path_hashes) == len(set(path_hashes))

    # Root path hash equals prompt hash
    assert path_hashes[0] == prompt_hashes[0]

    # Subsequent ones are different
    for i in range(1, len(path_hashes)):
        assert path_hashes[i] != prompt_hashes[i]


def test_find_matching_response_simple(hash_db):
    """Test finding a matching response by prompt hash"""
    conv_id = "conv1"
    hash_db["conversations"].insert(
        {"id": conv_id, "name": "Test", "model": "test-model"}
    )

    prompt_hash = calculate_prompt_hash(prompt="Hello")
    response_text = "Hi there!"
    response_hash = calculate_response_hash(response_text)
    path_hash = calculate_path_hash(None, prompt_hash)

    # Create response
    hash_db["responses"].insert(
        {
            "id": "resp1",
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "Hello",
            "response": response_text,
            "datetime_utc": "2025-01-01T00:00:00",
            "parent_response_id": None,
            "prompt_hash": prompt_hash,
            "response_hash": response_hash,
            "path_hash": path_hash,
        }
    )

    # Find it
    found = find_matching_response(hash_db, conv_id, None, prompt_hash)

    assert found is not None
    assert found["id"] == "resp1"
    assert found["response"] == response_text
    assert found["prompt_hash"] == prompt_hash


def test_find_matching_response_with_parent(hash_db):
    """Test finding a matching response with a parent"""
    conv_id = "conv1"
    hash_db["conversations"].insert(
        {"id": conv_id, "name": "Test", "model": "test-model"}
    )

    # Create root
    root_prompt_hash = calculate_prompt_hash(prompt="Hello")
    root_path_hash = calculate_path_hash(None, root_prompt_hash)

    hash_db["responses"].insert(
        {
            "id": "root",
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "Hello",
            "response": "Hi!",
            "datetime_utc": "2025-01-01T00:00:00",
            "parent_response_id": None,
            "prompt_hash": root_prompt_hash,
            "response_hash": calculate_response_hash("Hi!"),
            "path_hash": root_path_hash,
        }
    )

    # Create child
    child_prompt_hash = calculate_prompt_hash(prompt="How are you?")
    child_path_hash = calculate_path_hash(root_path_hash, child_prompt_hash)

    hash_db["responses"].insert(
        {
            "id": "child",
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "How are you?",
            "response": "I'm good!",
            "datetime_utc": "2025-01-01T00:01:00",
            "parent_response_id": "root",
            "prompt_hash": child_prompt_hash,
            "response_hash": calculate_response_hash("I'm good!"),
            "path_hash": child_path_hash,
        }
    )

    # Find child by prompt hash and parent
    found = find_matching_response(hash_db, conv_id, "root", child_prompt_hash)

    assert found is not None
    assert found["id"] == "child"
    assert found["response"] == "I'm good!"


def test_matching_scenario_reuse_path(hash_db):
    """
    Test realistic scenario: reusing an existing conversation path.

    Scenario:
    1. First call: [User("Hello"), Asst("Hi!"), User("How are you?")]
       Creates: root -> child
    2. Second call: Same messages
       Should find: Existing root and child
    """
    conv_id = "conv1"
    hash_db["conversations"].insert(
        {"id": conv_id, "name": "Test", "model": "test-model"}
    )

    # First interaction: Hello -> Hi!
    prompt1_hash = calculate_prompt_hash(prompt="Hello")
    response1 = "Hi!"
    response1_hash = calculate_response_hash(response1)
    path1_hash = calculate_path_hash(None, prompt1_hash)

    hash_db["responses"].insert(
        {
            "id": "resp1",
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "Hello",
            "response": response1,
            "datetime_utc": "2025-01-01T00:00:00",
            "parent_response_id": None,
            "prompt_hash": prompt1_hash,
            "response_hash": response1_hash,
            "path_hash": path1_hash,
        }
    )

    # Second interaction: How are you? -> I'm good!
    prompt2_hash = calculate_prompt_hash(prompt="How are you?")
    response2 = "I'm good!"
    response2_hash = calculate_response_hash(response2)
    path2_hash = calculate_path_hash(path1_hash, prompt2_hash)

    hash_db["responses"].insert(
        {
            "id": "resp2",
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "How are you?",
            "response": response2,
            "datetime_utc": "2025-01-01T00:01:00",
            "parent_response_id": "resp1",
            "prompt_hash": prompt2_hash,
            "response_hash": response2_hash,
            "path_hash": path2_hash,
        }
    )

    # Now simulate a new call with the same messages
    # First, find or match "Hello"
    found1 = find_matching_response(hash_db, conv_id, None, prompt1_hash)
    assert found1 is not None
    assert found1["id"] == "resp1"

    # Then find or match "How are you?" with parent resp1
    found2 = find_matching_response(hash_db, conv_id, found1["id"], prompt2_hash)
    assert found2 is not None
    assert found2["id"] == "resp2"

    # We successfully matched the existing path!


def test_matching_scenario_branch_different_response(hash_db):
    """
    Test branching when same prompt gives different response.

    Scenario:
    1. First: [User("Tell me a joke")] -> Asst("Joke A")
    2. Second: [User("Tell me a joke")] -> Asst("Joke B")

    Both should exist in the tree with same parent_response_id=None
    """
    conv_id = "conv1"
    hash_db["conversations"].insert(
        {"id": conv_id, "name": "Test", "model": "test-model"}
    )

    prompt_hash = calculate_prompt_hash(prompt="Tell me a joke")
    path_hash = calculate_path_hash(None, prompt_hash)

    # First response
    response_a = "Why did the chicken cross the road?"
    hash_db["responses"].insert(
        {
            "id": "resp_a",
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "Tell me a joke",
            "response": response_a,
            "datetime_utc": "2025-01-01T00:00:00",
            "parent_response_id": None,
            "prompt_hash": prompt_hash,
            "response_hash": calculate_response_hash(response_a),
            "path_hash": path_hash,
        }
    )

    # Second response (different, but same prompt and parent)
    response_b = "What do you call a bear with no teeth?"
    hash_db["responses"].insert(
        {
            "id": "resp_b",
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "Tell me a joke",
            "response": response_b,
            "datetime_utc": "2025-01-01T00:05:00",  # Different time
            "parent_response_id": None,
            "prompt_hash": prompt_hash,
            "response_hash": calculate_response_hash(response_b),
            "path_hash": path_hash,  # Same path hash!
        }
    )

    # Query will find one of them (first by LIMIT 1)
    found = find_matching_response(hash_db, conv_id, None, prompt_hash)
    assert found is not None
    assert found["id"] in ["resp_a", "resp_b"]

    # Both exist as alternatives
    all_matches = list(
        hash_db.execute(
            """
        SELECT id FROM responses
        WHERE conversation_id = ?
        AND parent_response_id IS NULL
        AND prompt_hash = ?
    """,
            [conv_id, prompt_hash],
        ).fetchall()
    )

    assert len(all_matches) == 2
    assert set(r[0] for r in all_matches) == {"resp_a", "resp_b"}


def test_comprehensive_workflow_demonstration(hash_db):
    """
    Comprehensive demonstration of the full message matching workflow.

    This simulates the intended use case:
    1. First call with messages array
    2. Second call with same messages - should find and reuse
    3. Third call extending conversation - should match prefix and add new
    """
    print("\n" + "=" * 70)
    print("COMPREHENSIVE WORKFLOW DEMONSTRATION")
    print("=" * 70)

    conv_id = "demo_conv"
    model = "claude-sonnet-4"
    hash_db["conversations"].insert(
        {"id": conv_id, "name": "Demo Conversation", "model": model}
    )

    # ===== CALL 1: Initial prompt =====
    print("\n📞 CALL 1: Initial prompt")
    print("-" * 70)

    messages_1 = [
        {"type": "system", "content": "You are a helpful assistant"},
        {"type": "user", "content": "What is the capital of France?"},
    ]

    # Calculate hashes for this prompt
    prompt1_hash = calculate_prompt_hash(
        system="You are a helpful assistant", prompt="What is the capital of France?"
    )

    print(f"System: {messages_1[0]['content']}")
    print(f"User: {messages_1[1]['content']}")
    print(f"Prompt Hash: {prompt1_hash[:16]}...")

    # Check if exists (it won't)
    existing = find_matching_response(hash_db, conv_id, None, prompt1_hash)
    print(f"Existing response: {existing}")

    # Simulate API call and create response
    response1 = "The capital of France is Paris."
    response1_hash = calculate_response_hash(response1)
    path1_hash = calculate_path_hash(None, prompt1_hash)

    hash_db["responses"].insert(
        {
            "id": "resp_001",
            "conversation_id": conv_id,
            "model": model,
            "prompt": "What is the capital of France?",
            "system": "You are a helpful assistant",
            "response": response1,
            "datetime_utc": "2025-01-01T10:00:00",
            "parent_response_id": None,
            "prompt_hash": prompt1_hash,
            "response_hash": response1_hash,
            "path_hash": path1_hash,
        }
    )

    print(f"✓ Created response: resp_001")
    print(f"Response: {response1}")
    print(f"Path Hash: {path1_hash[:16]}...")

    # ===== CALL 2: Same messages - should reuse =====
    print("\n📞 CALL 2: Same messages (should reuse)")
    print("-" * 70)

    messages_2 = [
        {"type": "system", "content": "You are a helpful assistant"},
        {"type": "user", "content": "What is the capital of France?"},
    ]

    prompt2_hash = calculate_prompt_hash(
        system="You are a helpful assistant", prompt="What is the capital of France?"
    )

    print(f"Prompt Hash: {prompt2_hash[:16]}...")
    print(f"Same as Call 1? {prompt2_hash == prompt1_hash}")

    # Find existing
    existing = find_matching_response(hash_db, conv_id, None, prompt2_hash)
    print(f"Existing response found: {existing['id']}")
    print(f"Response: {existing['response']}")
    print("✓ REUSED existing response (no API call needed!)")

    # ===== CALL 3: Extended conversation =====
    print("\n📞 CALL 3: Extended conversation")
    print("-" * 70)

    messages_3 = [
        {"type": "system", "content": "You are a helpful assistant"},
        {"type": "user", "content": "What is the capital of France?"},
        {"type": "assistant", "content": "The capital of France is Paris."},
        {"type": "user", "content": "And what about Germany?"},
    ]

    print("Messages:")
    for msg in messages_3:
        print(f"  {msg['type']}: {msg['content'][:50]}...")

    # Step 1: Match the first exchange
    print("\nStep 1: Match 'Capital of France?' prompt")
    existing_1 = find_matching_response(hash_db, conv_id, None, prompt1_hash)
    print(f"  Found: {existing_1['id']}")
    print(f"  Response: {existing_1['response']}")

    # Verify the assistant response matches
    print(
        f"  Assistant response matches? {existing_1['response'] == messages_3[2]['content']}"
    )

    # Step 2: Look for the second exchange
    print("\nStep 2: Look for 'What about Germany?' prompt")
    prompt3_hash = calculate_prompt_hash(prompt="And what about Germany?")
    print(f"  Prompt Hash: {prompt3_hash[:16]}...")

    existing_2 = find_matching_response(
        hash_db, conv_id, existing_1["id"], prompt3_hash
    )
    print(f"  Existing response: {existing_2}")

    # Step 3: Create new response
    print("\nStep 3: Create new response (API call needed)")
    response3 = "The capital of Germany is Berlin."
    response3_hash = calculate_response_hash(response3)
    path3_hash = calculate_path_hash(existing_1["path_hash"], prompt3_hash)

    hash_db["responses"].insert(
        {
            "id": "resp_002",
            "conversation_id": conv_id,
            "model": model,
            "prompt": "And what about Germany?",
            "response": response3,
            "datetime_utc": "2025-01-01T10:05:00",
            "parent_response_id": existing_1["id"],
            "prompt_hash": prompt3_hash,
            "response_hash": response3_hash,
            "path_hash": path3_hash,
        }
    )

    print(f"✓ Created response: resp_002")
    print(f"Response: {response3}")
    print(f"Parent: {existing_1['id']}")
    print(f"Path Hash: {path3_hash[:16]}...")

    # ===== CALL 4: Same extended conversation - should reuse both =====
    print("\n📞 CALL 4: Same extended conversation (should reuse both)")
    print("-" * 70)

    # Match first exchange
    match_1 = find_matching_response(hash_db, conv_id, None, prompt1_hash)
    print(f"Step 1: Found {match_1['id']} - REUSED")

    # Match second exchange
    match_2 = find_matching_response(hash_db, conv_id, match_1["id"], prompt3_hash)
    print(f"Step 2: Found {match_2['id']} - REUSED")
    print("✓ Entire conversation path reused (no API calls!)")

    # ===== CALL 5: Branch from middle =====
    print("\n📞 CALL 5: Branch from middle (alternative question)")
    print("-" * 70)

    messages_5 = [
        {"type": "system", "content": "You are a helpful assistant"},
        {"type": "user", "content": "What is the capital of France?"},
        {"type": "assistant", "content": "The capital of France is Paris."},
        {"type": "user", "content": "What is its population?"},
    ]

    print("Branching with different second question:")
    print(f"  Original: 'And what about Germany?'")
    print(f"  New: 'What is its population?'")

    # Match first exchange (same)
    match_1 = find_matching_response(hash_db, conv_id, None, prompt1_hash)
    print(f"\nStep 1: Found {match_1['id']} - REUSED")

    # Try to match second exchange (different)
    prompt5_hash = calculate_prompt_hash(prompt="What is its population?")
    match_2 = find_matching_response(hash_db, conv_id, match_1["id"], prompt5_hash)
    print(f"Step 2: Found {match_2}")

    # Create alternative branch
    response5 = (
        "The population of Paris is approximately 2.2 million in the city proper."
    )
    response5_hash = calculate_response_hash(response5)
    path5_hash = calculate_path_hash(match_1["path_hash"], prompt5_hash)

    hash_db["responses"].insert(
        {
            "id": "resp_003",
            "conversation_id": conv_id,
            "model": model,
            "prompt": "What is its population?",
            "response": response5,
            "datetime_utc": "2025-01-01T10:10:00",
            "parent_response_id": match_1["id"],
            "prompt_hash": prompt5_hash,
            "response_hash": response5_hash,
            "path_hash": path5_hash,
        }
    )

    print(f"✓ Created alternative branch: resp_003")
    print(f"Response: {response5[:50]}...")

    # ===== FINAL TREE VISUALIZATION =====
    print("\n" + "=" * 70)
    print("FINAL CONVERSATION TREE")
    print("=" * 70)

    print("\nRoot: 'What is the capital of France?' -> 'Paris'")
    print("  ├─ Branch 1: 'And what about Germany?' -> 'Berlin'")
    print("  └─ Branch 2: 'What is its population?' -> '2.2 million...'")

    # Query to show the tree structure
    all_responses = list(
        hash_db.execute(
            """
        SELECT id, prompt, response, parent_response_id, 
               substr(prompt_hash, 1, 8) as ph,
               substr(path_hash, 1, 8) as path_h
        FROM responses
        WHERE conversation_id = ?
        ORDER BY datetime_utc
    """,
            [conv_id],
        ).fetchall()
    )

    print("\n" + "=" * 70)
    print("DATABASE CONTENTS")
    print("=" * 70)
    for resp in all_responses:
        print(f"\n{resp[0]}:")
        print(f"  Prompt: {resp[1]}")
        print(f"  Response: {resp[2][:50]}...")
        print(f"  Parent: {resp[3] or 'None (root)'}")
        print(f"  Prompt Hash: {resp[4]}...")
        print(f"  Path Hash: {resp[5]}...")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total responses created: {len(all_responses)}")
    print(f"Total API calls simulated: 3")
    print(f"Total calls received: 5")
    print(f"Cache hit rate: 40% (2/5 reused)")
    print("=" * 70 + "\n")

    # Assertions
    assert len(all_responses) == 3
    assert all_responses[0][0] == "resp_001"  # Root
    assert all_responses[1][0] == "resp_002"  # First branch
    assert all_responses[2][0] == "resp_003"  # Second branch
