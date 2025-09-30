"""
Tests for tree-structured conversations using parent_response_id
"""

import pytest
import sqlite_utils
from llm.migrations import migrate


@pytest.fixture
def tree_db():
    """Create a test database with migrations applied"""
    db = sqlite_utils.Database(memory=True)
    migrate(db)
    return db


def test_migration_adds_parent_response_id_column(tree_db):
    """Test that the migration adds the parent_response_id column"""
    columns = tree_db["responses"].columns_dict
    assert "parent_response_id" in columns
    assert columns["parent_response_id"] == str


def test_create_linear_conversation(tree_db):
    """Test creating a simple linear conversation chain: Root -> A -> B"""
    # Create conversation
    conv_id = "conv1"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Test Linear", "model": "test-model"}
    )

    # Create root response
    root_id = "resp_root"
    tree_db["responses"].insert(
        {
            "id": root_id,
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "Hello",
            "response": "Hi there!",
            "datetime_utc": "2025-01-01T00:00:00",
            "parent_response_id": None,  # Root has no parent
        }
    )

    # Create response A (child of root)
    resp_a_id = "resp_a"
    tree_db["responses"].insert(
        {
            "id": resp_a_id,
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "How are you?",
            "response": "I'm doing well!",
            "datetime_utc": "2025-01-01T00:01:00",
            "parent_response_id": root_id,
        }
    )

    # Create response B (child of A)
    resp_b_id = "resp_b"
    tree_db["responses"].insert(
        {
            "id": resp_b_id,
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "That's great!",
            "response": "Thank you!",
            "datetime_utc": "2025-01-01T00:02:00",
            "parent_response_id": resp_a_id,
        }
    )

    # Verify the structure
    root = tree_db["responses"].get(root_id)
    assert root["parent_response_id"] is None

    resp_a = tree_db["responses"].get(resp_a_id)
    assert resp_a["parent_response_id"] == root_id

    resp_b = tree_db["responses"].get(resp_b_id)
    assert resp_b["parent_response_id"] == resp_a_id


def test_create_branching_conversation(tree_db):
    """Test creating a conversation with branches: Root -> [B, C]"""
    conv_id = "conv2"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Test Branch", "model": "test-model"}
    )

    # Create root
    root_id = "resp_root"
    tree_db["responses"].insert(
        {
            "id": root_id,
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "Tell me about Python",
            "response": "Python is a programming language",
            "datetime_utc": "2025-01-01T00:00:00",
            "parent_response_id": None,
        }
    )

    # Create branch B
    resp_b_id = "resp_b"
    tree_db["responses"].insert(
        {
            "id": resp_b_id,
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "What about its syntax?",
            "response": "Python uses indentation",
            "datetime_utc": "2025-01-01T00:01:00",
            "parent_response_id": root_id,
        }
    )

    # Create branch C (also child of root)
    resp_c_id = "resp_c"
    tree_db["responses"].insert(
        {
            "id": resp_c_id,
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "What about its history?",
            "response": "Python was created by Guido van Rossum",
            "datetime_utc": "2025-01-01T00:01:30",
            "parent_response_id": root_id,
        }
    )

    # Verify both B and C have root as parent
    resp_b = tree_db["responses"].get(resp_b_id)
    resp_c = tree_db["responses"].get(resp_c_id)
    assert resp_b["parent_response_id"] == root_id
    assert resp_c["parent_response_id"] == root_id

    # Get children of root
    children = list(
        tree_db.execute(
            "SELECT id FROM responses WHERE parent_response_id = ?", [root_id]
        ).fetchall()
    )
    child_ids = [c[0] for c in children]
    assert len(child_ids) == 2
    assert resp_b_id in child_ids
    assert resp_c_id in child_ids


def test_get_children_helper(tree_db):
    """Test helper function to get children of a response"""
    conv_id = "conv3"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Test Children", "model": "test-model"}
    )

    root_id = "root"
    tree_db["responses"].insert(
        {
            "id": root_id,
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "Root",
            "response": "Root response",
            "datetime_utc": "2025-01-01T00:00:00",
            "parent_response_id": None,
        }
    )

    # Create 3 children
    child_ids = []
    for i in range(3):
        child_id = f"child_{i}"
        child_ids.append(child_id)
        tree_db["responses"].insert(
            {
                "id": child_id,
                "conversation_id": conv_id,
                "model": "test-model",
                "prompt": f"Child {i}",
                "response": f"Response {i}",
                "datetime_utc": f"2025-01-01T00:0{i+1}:00",
                "parent_response_id": root_id,
            }
        )

    # Helper function to get children
    def get_children(db, response_id):
        return list(
            db.execute(
                "SELECT id, prompt, response, datetime_utc FROM responses WHERE parent_response_id = ? ORDER BY datetime_utc",
                [response_id],
            ).fetchall()
        )

    children = get_children(tree_db, root_id)
    assert len(children) == 3
    for i, child in enumerate(children):
        assert child[0] == f"child_{i}"
        assert child[1] == f"Child {i}"


def test_get_path_to_root(tree_db):
    """Test getting the full path from a response to the root"""
    conv_id = "conv4"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Test Path", "model": "test-model"}
    )

    # Create chain: root -> a -> b -> c
    responses = [("root", None), ("a", "root"), ("b", "a"), ("c", "b")]

    for resp_id, parent_id in responses:
        tree_db["responses"].insert(
            {
                "id": resp_id,
                "conversation_id": conv_id,
                "model": "test-model",
                "prompt": f"Prompt {resp_id}",
                "response": f"Response {resp_id}",
                "datetime_utc": "2025-01-01T00:00:00",
                "parent_response_id": parent_id,
            }
        )

    # Helper function to get path to root
    def get_path_to_root(db, response_id):
        path = []
        current_id = response_id
        visited = set()  # Prevent infinite loops

        while current_id is not None and current_id not in visited:
            visited.add(current_id)
            row = db["responses"].get(current_id)
            path.append(row["id"])
            current_id = row["parent_response_id"]

        return list(reversed(path))  # Return root-to-leaf order

    # Test path from c
    path = get_path_to_root(tree_db, "c")
    assert path == ["root", "a", "b", "c"]

    # Test path from a
    path = get_path_to_root(tree_db, "a")
    assert path == ["root", "a"]

    # Test path from root
    path = get_path_to_root(tree_db, "root")
    assert path == ["root"]


def test_multiple_roots_in_conversation(tree_db):
    """Test that a conversation can have multiple root responses"""
    conv_id = "conv5"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Test Multiple Roots", "model": "test-model"}
    )

    # Create two separate roots
    for i in range(2):
        root_id = f"root_{i}"
        tree_db["responses"].insert(
            {
                "id": root_id,
                "conversation_id": conv_id,
                "model": "test-model",
                "prompt": f"Root {i}",
                "response": f"Response {i}",
                "datetime_utc": f"2025-01-01T0{i}:00:00",
                "parent_response_id": None,
            }
        )

        # Add a child to each root
        tree_db["responses"].insert(
            {
                "id": f"child_{i}",
                "conversation_id": conv_id,
                "model": "test-model",
                "prompt": f"Child of root {i}",
                "response": f"Child response {i}",
                "datetime_utc": f"2025-01-01T0{i}:01:00",
                "parent_response_id": root_id,
            }
        )

    # Find all roots in conversation
    roots = list(
        tree_db.execute(
            "SELECT id FROM responses WHERE conversation_id = ? AND parent_response_id IS NULL ORDER BY datetime_utc",
            [conv_id],
        ).fetchall()
    )

    assert len(roots) == 2
    assert roots[0][0] == "root_0"
    assert roots[1][0] == "root_1"


def test_get_all_descendants(tree_db):
    """Test getting all descendants of a response (entire subtree)"""
    conv_id = "conv6"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Test Descendants", "model": "test-model"}
    )

    # Create tree structure:
    #       -> b -> d
    # root <
    #       -> c -> e -> f
    structure = [
        ("root", None),
        ("b", "root"),
        ("c", "root"),
        ("d", "b"),
        ("e", "c"),
        ("f", "e"),
    ]

    for resp_id, parent_id in structure:
        tree_db["responses"].insert(
            {
                "id": resp_id,
                "conversation_id": conv_id,
                "model": "test-model",
                "prompt": f"Prompt {resp_id}",
                "response": f"Response {resp_id}",
                "datetime_utc": "2025-01-01T00:00:00",
                "parent_response_id": parent_id,
            }
        )

    # Recursive function to get all descendants
    def get_all_descendants(db, response_id):
        descendants = []
        children = list(
            db.execute(
                "SELECT id FROM responses WHERE parent_response_id = ?", [response_id]
            ).fetchall()
        )

        for child in children:
            child_id = child[0]
            descendants.append(child_id)
            descendants.extend(get_all_descendants(db, child_id))

        return descendants

    # Test from root - should get all
    descendants = get_all_descendants(tree_db, "root")
    assert len(descendants) == 5  # b, c, d, e, f
    assert set(descendants) == {"b", "c", "d", "e", "f"}

    # Test from c - should get e and f
    descendants = get_all_descendants(tree_db, "c")
    assert len(descendants) == 2
    assert set(descendants) == {"e", "f"}

    # Test from d - should get nothing (leaf node)
    descendants = get_all_descendants(tree_db, "d")
    assert len(descendants) == 0


def test_get_siblings(tree_db):
    """Test getting sibling responses (same parent)"""
    conv_id = "conv7"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Test Siblings", "model": "test-model"}
    )

    root_id = "root"
    tree_db["responses"].insert(
        {
            "id": root_id,
            "conversation_id": conv_id,
            "model": "test-model",
            "prompt": "Root",
            "response": "Root response",
            "datetime_utc": "2025-01-01T00:00:00",
            "parent_response_id": None,
        }
    )

    # Create 4 siblings
    sibling_ids = []
    for i in range(4):
        sibling_id = f"sibling_{i}"
        sibling_ids.append(sibling_id)
        tree_db["responses"].insert(
            {
                "id": sibling_id,
                "conversation_id": conv_id,
                "model": "test-model",
                "prompt": f"Sibling {i}",
                "response": f"Response {i}",
                "datetime_utc": f"2025-01-01T00:0{i}:00",
                "parent_response_id": root_id,
            }
        )

    # Get siblings of sibling_1
    def get_siblings(db, response_id):
        response = db["responses"].get(response_id)
        parent_id = response["parent_response_id"]

        if parent_id is None:
            return []  # Root has no siblings

        siblings = list(
            db.execute(
                "SELECT id FROM responses WHERE parent_response_id = ? AND id != ? ORDER BY datetime_utc",
                [parent_id, response_id],
            ).fetchall()
        )

        return [s[0] for s in siblings]

    siblings = get_siblings(tree_db, "sibling_1")
    assert len(siblings) == 3
    assert "sibling_1" not in siblings
    assert set(siblings) == {"sibling_0", "sibling_2", "sibling_3"}

    # Root has no siblings
    siblings = get_siblings(tree_db, root_id)
    assert len(siblings) == 0


def test_tree_depth_calculation(tree_db):
    """Test calculating the depth of each node in the tree"""
    conv_id = "conv8"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Test Depth", "model": "test-model"}
    )

    # Create a tree with varying depths:
    #           -> b (depth 1) -> d (depth 2)
    # root (0) <
    #           -> c (depth 1) -> e (depth 2) -> f (depth 3)
    structure = [
        ("root", None, 0),
        ("b", "root", 1),
        ("c", "root", 1),
        ("d", "b", 2),
        ("e", "c", 2),
        ("f", "e", 3),
    ]

    for resp_id, parent_id, _ in structure:
        tree_db["responses"].insert(
            {
                "id": resp_id,
                "conversation_id": conv_id,
                "model": "test-model",
                "prompt": f"Prompt {resp_id}",
                "response": f"Response {resp_id}",
                "datetime_utc": "2025-01-01T00:00:00",
                "parent_response_id": parent_id,
            }
        )

    def get_depth(db, response_id):
        """Calculate depth of a response (distance from root)"""
        depth = 0
        current_id = response_id
        visited = set()

        while current_id is not None and current_id not in visited:
            visited.add(current_id)
            row = db["responses"].get(current_id)
            parent_id = row["parent_response_id"]
            if parent_id is not None:
                depth += 1
            current_id = parent_id

        return depth

    # Test depths
    for resp_id, _, expected_depth in structure:
        actual_depth = get_depth(tree_db, resp_id)
        assert (
            actual_depth == expected_depth
        ), f"Node {resp_id} should have depth {expected_depth}, got {actual_depth}"


def test_leaf_nodes(tree_db):
    """Test identifying leaf nodes (nodes with no children)"""
    conv_id = "conv9"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Test Leaves", "model": "test-model"}
    )

    # Create tree: root -> a -> [b, c], where b and c are leaves
    structure = [
        ("root", None, False),  # not a leaf
        ("a", "root", False),  # not a leaf
        ("b", "a", True),  # leaf
        ("c", "a", True),  # leaf
    ]

    for resp_id, parent_id, _ in structure:
        tree_db["responses"].insert(
            {
                "id": resp_id,
                "conversation_id": conv_id,
                "model": "test-model",
                "prompt": f"Prompt {resp_id}",
                "response": f"Response {resp_id}",
                "datetime_utc": "2025-01-01T00:00:00",
                "parent_response_id": parent_id,
            }
        )

    # Query to find all leaf nodes
    leaves = list(
        tree_db.execute(
            """
        SELECT r1.id 
        FROM responses r1
        WHERE r1.conversation_id = ?
        AND NOT EXISTS (
            SELECT 1 FROM responses r2 
            WHERE r2.parent_response_id = r1.id
        )
        ORDER BY r1.id
    """,
            [conv_id],
        ).fetchall()
    )

    leaf_ids = [l[0] for l in leaves]
    assert len(leaf_ids) == 2
    assert set(leaf_ids) == {"b", "c"}


def test_get_tree_statistics(tree_db):
    """Test gathering statistics about the conversation tree"""
    conv_id = "conv10"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Test Stats", "model": "test-model"}
    )

    # Create a moderately complex tree
    structure = [
        ("root", None),
        ("a", "root"),
        ("b", "root"),
        ("c", "a"),
        ("d", "a"),
        ("e", "b"),
    ]

    for resp_id, parent_id in structure:
        tree_db["responses"].insert(
            {
                "id": resp_id,
                "conversation_id": conv_id,
                "model": "test-model",
                "prompt": f"Prompt {resp_id}",
                "response": f"Response {resp_id}",
                "datetime_utc": "2025-01-01T00:00:00",
                "parent_response_id": parent_id,
            }
        )

    # Total responses
    total = tree_db.execute(
        "SELECT COUNT(*) FROM responses WHERE conversation_id = ?", [conv_id]
    ).fetchone()[0]
    assert total == 6

    # Number of roots
    roots = tree_db.execute(
        "SELECT COUNT(*) FROM responses WHERE conversation_id = ? AND parent_response_id IS NULL",
        [conv_id],
    ).fetchone()[0]
    assert roots == 1

    # Number of branches (nodes with multiple children)
    branches = tree_db.execute(
        """
        SELECT COUNT(DISTINCT parent_response_id) 
        FROM responses 
        WHERE conversation_id = ? 
        AND parent_response_id IS NOT NULL
        GROUP BY parent_response_id
        HAVING COUNT(*) > 1
    """,
        [conv_id],
    ).fetchone()
    # root has 2 children (a, b), a has 2 children (c, d), b has 1 child
    # So we have 2 nodes with multiple children

    # Number of leaf nodes
    leaves = tree_db.execute(
        """
        SELECT COUNT(*) FROM responses r1
        WHERE r1.conversation_id = ?
        AND NOT EXISTS (
            SELECT 1 FROM responses r2 
            WHERE r2.parent_response_id = r1.id
        )
    """,
        [conv_id],
    ).fetchone()[0]
    assert leaves == 3  # c, d, e


def test_branching_factor(tree_db):
    """Test calculating branching factor (average number of children per non-leaf node)"""
    conv_id = "conv11"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Test Branching Factor", "model": "test-model"}
    )

    # Create tree where:
    # root has 2 children (a, b)
    # a has 3 children (c, d, e)
    # b has 1 child (f)
    # Average branching factor = (2 + 3 + 1) / 3 = 2
    structure = [
        ("root", None),
        ("a", "root"),
        ("b", "root"),
        ("c", "a"),
        ("d", "a"),
        ("e", "a"),
        ("f", "b"),
    ]

    for resp_id, parent_id in structure:
        tree_db["responses"].insert(
            {
                "id": resp_id,
                "conversation_id": conv_id,
                "model": "test-model",
                "prompt": f"Prompt {resp_id}",
                "response": f"Response {resp_id}",
                "datetime_utc": "2025-01-01T00:00:00",
                "parent_response_id": parent_id,
            }
        )

    # Get branching factor
    result = tree_db.execute(
        """
        SELECT 
            AVG(child_count) as avg_branching_factor,
            MAX(child_count) as max_branching_factor
        FROM (
            SELECT parent_response_id, COUNT(*) as child_count
            FROM responses
            WHERE conversation_id = ? AND parent_response_id IS NOT NULL
            GROUP BY parent_response_id
        )
    """,
        [conv_id],
    ).fetchone()

    avg_bf = result[0]
    max_bf = result[1]

    assert avg_bf == 2.0
    assert max_bf == 3


def test_get_conversation_summary(tree_db):
    """Test creating a comprehensive summary of the conversation tree structure"""
    conv_id = "conv12"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Test Summary", "model": "test-model"}
    )

    # Create a tree with interesting properties
    structure = [
        ("root", None),
        ("a", "root"),
        ("b", "root"),
        ("c", "a"),
    ]

    for resp_id, parent_id in structure:
        tree_db["responses"].insert(
            {
                "id": resp_id,
                "conversation_id": conv_id,
                "model": "test-model",
                "prompt": f"Prompt {resp_id}",
                "response": f"Response {resp_id}",
                "datetime_utc": "2025-01-01T00:00:00",
                "parent_response_id": parent_id,
            }
        )

    def get_conversation_summary(db, conversation_id):
        """Get a comprehensive summary of the conversation tree"""
        summary = {}

        # Total responses
        summary["total_responses"] = db.execute(
            "SELECT COUNT(*) FROM responses WHERE conversation_id = ?",
            [conversation_id],
        ).fetchone()[0]

        # Root nodes
        summary["root_count"] = db.execute(
            "SELECT COUNT(*) FROM responses WHERE conversation_id = ? AND parent_response_id IS NULL",
            [conversation_id],
        ).fetchone()[0]

        # Leaf nodes
        summary["leaf_count"] = db.execute(
            """
            SELECT COUNT(*) FROM responses r1
            WHERE r1.conversation_id = ?
            AND NOT EXISTS (
                SELECT 1 FROM responses r2 
                WHERE r2.parent_response_id = r1.id
            )
        """,
            [conversation_id],
        ).fetchone()[0]

        # Max depth
        roots = db.execute(
            "SELECT id FROM responses WHERE conversation_id = ? AND parent_response_id IS NULL",
            [conversation_id],
        ).fetchall()

        def get_max_depth_from_node(node_id, visited=None):
            if visited is None:
                visited = set()
            if node_id in visited:
                return 0
            visited.add(node_id)

            children = db.execute(
                "SELECT id FROM responses WHERE parent_response_id = ?", [node_id]
            ).fetchall()

            if not children:
                return 0

            return 1 + max(get_max_depth_from_node(c[0], visited) for c in children)

        summary["max_depth"] = max(
            (get_max_depth_from_node(r[0]) for r in roots), default=0
        )

        return summary

    summary = get_conversation_summary(tree_db, conv_id)
    assert summary["total_responses"] == 4
    assert summary["root_count"] == 1
    assert summary["leaf_count"] == 2  # b and c
    assert summary["max_depth"] == 2  # root -> a -> c


def test_forest_with_multiple_trees(tree_db):
    """Test a conversation that contains multiple independent trees"""
    conv_id = "conv13"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Test Forest", "model": "test-model"}
    )

    # Create two independent trees
    # Tree 1: root1 -> a -> b
    # Tree 2: root2 -> x -> y
    structure = [
        ("root1", None),
        ("a", "root1"),
        ("b", "a"),
        ("root2", None),
        ("x", "root2"),
        ("y", "x"),
    ]

    for resp_id, parent_id in structure:
        tree_db["responses"].insert(
            {
                "id": resp_id,
                "conversation_id": conv_id,
                "model": "test-model",
                "prompt": f"Prompt {resp_id}",
                "response": f"Response {resp_id}",
                "datetime_utc": "2025-01-01T00:00:00",
                "parent_response_id": parent_id,
            }
        )

    # Get all trees (root nodes and their descendants)
    roots = list(
        tree_db.execute(
            "SELECT id FROM responses WHERE conversation_id = ? AND parent_response_id IS NULL ORDER BY id",
            [conv_id],
        ).fetchall()
    )

    assert len(roots) == 2

    def get_tree_size(db, root_id):
        """Count all nodes in a tree starting from root"""
        count = 1  # Count the root itself
        children = db.execute(
            "SELECT id FROM responses WHERE parent_response_id = ?", [root_id]
        ).fetchall()
        for child in children:
            count += get_tree_size(db, child[0])
        return count

    tree1_size = get_tree_size(tree_db, "root1")
    tree2_size = get_tree_size(tree_db, "root2")

    assert tree1_size == 3  # root1, a, b
    assert tree2_size == 3  # root2, x, y


def test_tree_visualization(tree_db):
    """Test the print_tree function for visualizing conversation structure"""
    import sys
    import os

    # Add parent directory to path to import tree_utils
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from tree_utils import print_tree

    conv_id = "conv14"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Test Visualization", "model": "test-model"}
    )

    # Create a simple tree for visualization
    #       -> b
    # root <
    #       -> c -> d
    structure = [
        ("root", None, "What is Python?"),
        ("b", "root", "Tell me about its syntax"),
        ("c", "root", "Tell me about its history"),
        ("d", "c", "Who created it?"),
    ]

    for resp_id, parent_id, prompt in structure:
        tree_db["responses"].insert(
            {
                "id": resp_id,
                "conversation_id": conv_id,
                "model": "test-model",
                "prompt": prompt,
                "response": f"Response to: {prompt}",
                "datetime_utc": "2025-01-01T00:00:00",
                "parent_response_id": parent_id,
            }
        )

    # Get the tree visualization
    tree_str = print_tree(tree_db, "root")

    # Verify the structure
    assert "[root]" in tree_str
    assert "[b]" in tree_str
    assert "[c]" in tree_str
    assert "[d]" in tree_str
    assert "What is Python?" in tree_str

    # Print it for manual inspection
    print("\n" + "=" * 50)
    print("Tree Visualization:")
    print("=" * 50)
    print(tree_str)
    print("=" * 50)


def test_realistic_debugging_scenario(tree_db):
    """
    Test a realistic scenario: debugging a program with multiple attempted solutions.

    This simulates a user asking about a bug and trying different solutions,
    branching when one approach doesn't work and trying another.
    """
    import sys
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from tree_utils import (
        get_conversation_summary,
        get_leaf_nodes,
        get_path_to_root,
        print_tree,
        get_siblings,
    )

    conv_id = "debug_conv"
    tree_db["conversations"].insert(
        {"id": conv_id, "name": "Debug Python Error", "model": "test-model"}
    )

    # Scenario structure:
    # root (initial question)
    #   -> try_fix_1 (first attempted solution)
    #       -> still_broken_1 (didn't work)
    #   -> try_fix_2 (second attempt, branching from root)
    #       -> progress_2 (made some progress)
    #           -> working_2a (one successful path)
    #           -> working_2b (another successful approach)
    #   -> try_fix_3 (third attempt from root)

    responses = [
        ("root", None, "I'm getting a TypeError in my Python code"),
        ("try_fix_1", "root", "Let's try adding type hints"),
        ("still_broken_1", "try_fix_1", "Still getting the error"),
        ("try_fix_2", "root", "Let's try a different approach with validation"),
        ("progress_2", "try_fix_2", "That helped! But now there's another issue"),
        ("working_2a", "progress_2", "Using isinstance() fixed it!"),
        ("working_2b", "progress_2", "Or we could use try/except instead"),
        ("try_fix_3", "root", "What if we refactor the function signature?"),
    ]

    for resp_id, parent_id, prompt in responses:
        tree_db["responses"].insert(
            {
                "id": resp_id,
                "conversation_id": conv_id,
                "model": "test-model",
                "prompt": prompt,
                "response": f"[Response to: {prompt}]",
                "datetime_utc": "2025-01-01T00:00:00",
                "parent_response_id": parent_id,
            }
        )

    # Test 1: Get summary statistics
    summary = get_conversation_summary(tree_db, conv_id)
    assert summary["total_responses"] == 8
    assert summary["root_count"] == 1
    assert (
        summary["leaf_count"] == 4
    )  # still_broken_1, working_2a, working_2b, try_fix_3
    assert summary["max_depth"] == 3  # root -> try_fix_2 -> progress_2 -> working_2a

    # Test 2: Find all leaf nodes (potential end states)
    leaves = get_leaf_nodes(tree_db, conv_id)
    assert len(leaves) == 4
    assert set(leaves) == {"still_broken_1", "working_2a", "working_2b", "try_fix_3"}

    # Test 3: Get the path to a successful solution
    path_to_working = get_path_to_root(tree_db, "working_2a")
    assert path_to_working == ["root", "try_fix_2", "progress_2", "working_2a"]

    # Test 4: Find alternative solutions (siblings)
    alternatives = get_siblings(tree_db, "working_2a")
    assert alternatives == ["working_2b"]

    # Test 5: Find all attempted solutions from root
    children_of_root = list(
        tree_db.execute(
            "SELECT id, prompt FROM responses WHERE parent_response_id = ? ORDER BY datetime_utc",
            ["root"],
        ).fetchall()
    )
    assert len(children_of_root) == 3
    assert children_of_root[0][0] == "try_fix_1"
    assert children_of_root[1][0] == "try_fix_2"
    assert children_of_root[2][0] == "try_fix_3"

    # Print the full tree for inspection
    print("\n" + "=" * 60)
    print("Realistic Debugging Scenario - Conversation Tree:")
    print("=" * 60)
    print(print_tree(tree_db, "root"))
    print("=" * 60)
    print(f"\nSummary Statistics:")
    print(f"  Total responses: {summary['total_responses']}")
    print(f"  Root nodes: {summary['root_count']}")
    print(f"  Leaf nodes: {summary['leaf_count']}")
    print(f"  Max depth: {summary['max_depth']}")
    print(f"\nSuccessful solution paths:")
    for leaf in ["working_2a", "working_2b"]:
        path = get_path_to_root(tree_db, leaf)
        print(f"  {' -> '.join(path)}")
    print("=" * 60)
