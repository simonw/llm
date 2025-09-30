"""
Utility functions for working with tree-structured conversations.

This module provides helper functions to navigate and analyze conversation trees
that use the parent_response_id column to model branching conversations.
"""


def get_children(db, response_id):
    """
    Get all direct children of a response.

    Args:
        db: sqlite_utils Database instance
        response_id: ID of the parent response

    Returns:
        List of tuples (id, prompt, response, datetime_utc)
    """
    return list(
        db.execute(
            "SELECT id, prompt, response, datetime_utc FROM responses WHERE parent_response_id = ? ORDER BY datetime_utc",
            [response_id],
        ).fetchall()
    )


def get_parent(db, response_id):
    """
    Get the parent response of a given response.

    Args:
        db: sqlite_utils Database instance
        response_id: ID of the response

    Returns:
        Parent response row dict, or None if this is a root response
    """
    response = db["responses"].get(response_id)
    parent_id = response["parent_response_id"]
    if parent_id is None:
        return None
    return db["responses"].get(parent_id)


def get_siblings(db, response_id):
    """
    Get all sibling responses (responses with the same parent).

    Args:
        db: sqlite_utils Database instance
        response_id: ID of the response

    Returns:
        List of sibling response IDs (excluding the given response)
    """
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


def get_path_to_root(db, response_id):
    """
    Get the full path from root to the given response.

    Args:
        db: sqlite_utils Database instance
        response_id: ID of the response

    Returns:
        List of response IDs from root to the given response (inclusive)
    """
    path = []
    current_id = response_id
    visited = set()  # Prevent infinite loops in case of cycles

    while current_id is not None and current_id not in visited:
        visited.add(current_id)
        row = db["responses"].get(current_id)
        path.append(row["id"])
        current_id = row["parent_response_id"]

    return list(reversed(path))  # Return root-to-leaf order


def get_all_descendants(db, response_id):
    """
    Get all descendants of a response (entire subtree).

    Args:
        db: sqlite_utils Database instance
        response_id: ID of the root of the subtree

    Returns:
        List of all descendant response IDs
    """
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


def get_depth(db, response_id):
    """
    Calculate the depth of a response (distance from root).

    Args:
        db: sqlite_utils Database instance
        response_id: ID of the response

    Returns:
        Depth as an integer (root = 0)
    """
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


def get_root_nodes(db, conversation_id):
    """
    Get all root nodes (responses with no parent) in a conversation.

    Args:
        db: sqlite_utils Database instance
        conversation_id: ID of the conversation

    Returns:
        List of root response IDs
    """
    roots = list(
        db.execute(
            "SELECT id FROM responses WHERE conversation_id = ? AND parent_response_id IS NULL ORDER BY datetime_utc",
            [conversation_id],
        ).fetchall()
    )
    return [r[0] for r in roots]


def get_leaf_nodes(db, conversation_id):
    """
    Get all leaf nodes (responses with no children) in a conversation.

    Args:
        db: sqlite_utils Database instance
        conversation_id: ID of the conversation

    Returns:
        List of leaf response IDs
    """
    leaves = list(
        db.execute(
            """
        SELECT r1.id 
        FROM responses r1
        WHERE r1.conversation_id = ?
        AND NOT EXISTS (
            SELECT 1 FROM responses r2 
            WHERE r2.parent_response_id = r1.id
        )
        ORDER BY r1.datetime_utc
    """,
            [conversation_id],
        ).fetchall()
    )
    return [l[0] for l in leaves]


def get_tree_size(db, root_id):
    """
    Count all nodes in a tree starting from a root.

    Args:
        db: sqlite_utils Database instance
        root_id: ID of the root response

    Returns:
        Total number of nodes in the tree (including root)
    """
    count = 1  # Count the root itself
    children = db.execute(
        "SELECT id FROM responses WHERE parent_response_id = ?", [root_id]
    ).fetchall()
    for child in children:
        count += get_tree_size(db, child[0])
    return count


def get_conversation_summary(db, conversation_id):
    """
    Get comprehensive statistics about a conversation tree.

    Args:
        db: sqlite_utils Database instance
        conversation_id: ID of the conversation

    Returns:
        Dictionary with tree statistics:
        - total_responses: Total number of responses
        - root_count: Number of root nodes
        - leaf_count: Number of leaf nodes
        - max_depth: Maximum depth in the tree
    """
    summary = {}

    # Total responses
    summary["total_responses"] = db.execute(
        "SELECT COUNT(*) FROM responses WHERE conversation_id = ?", [conversation_id]
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


def get_branching_factor(db, conversation_id):
    """
    Calculate the average branching factor of the conversation tree.

    Args:
        db: sqlite_utils Database instance
        conversation_id: ID of the conversation

    Returns:
        Tuple of (average_branching_factor, max_branching_factor)
    """
    result = db.execute(
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
        [conversation_id],
    ).fetchone()

    return (result[0] or 0, result[1] or 0)


def print_tree(db, response_id, indent=0, visited=None):
    """
    Print a text representation of a conversation tree.

    Args:
        db: sqlite_utils Database instance
        response_id: ID of the root response to start from
        indent: Current indentation level (for recursion)
        visited: Set of visited nodes (for cycle detection)

    Returns:
        String representation of the tree
    """
    if visited is None:
        visited = set()

    if response_id in visited:
        return "  " * indent + f"[{response_id}] (cycle detected)\n"

    visited.add(response_id)

    response = db["responses"].get(response_id)
    prompt = response["prompt"] or "(no prompt)"
    if len(prompt) > 50:
        prompt = prompt[:47] + "..."

    output = "  " * indent + f"[{response_id}] {prompt}\n"

    children = db.execute(
        "SELECT id FROM responses WHERE parent_response_id = ? ORDER BY datetime_utc",
        [response_id],
    ).fetchall()

    for child in children:
        output += print_tree(db, child[0], indent + 1, visited)

    return output
