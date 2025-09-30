"""
Message hashing and matching for tree-structured conversations.

This module provides utilities to hash conversation messages and match
them against existing conversation trees in the database.
"""

import hashlib
import json
from typing import List, Optional, Dict, Any, Tuple


def normalize_json(obj: Any) -> str:
    """
    Normalize a JSON object to a canonical string representation.

    Args:
        obj: JSON-serializable object

    Returns:
        Canonical JSON string (sorted keys, compact)
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def hash_content(content: str) -> str:
    """
    Create a SHA-256 hash of text content.

    Args:
        content: Text to hash

    Returns:
        Hex digest of hash
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def hash_binary(data: bytes) -> str:
    """
    Create a SHA-256 hash of binary data.

    Args:
        data: Binary data to hash

    Returns:
        Hex digest of hash
    """
    return hashlib.sha256(data).hexdigest()


def hash_attachment(attachment: Dict[str, Any]) -> str:
    """
    Create a hash for an attachment (image, file, etc.).

    Args:
        attachment: Dictionary with 'type', 'content', 'url', or 'path'

    Returns:
        Hash representing the attachment
    """
    if attachment.get("content"):
        # Hash the actual content
        return f"content:{hash_binary(attachment['content'])}"
    elif attachment.get("url"):
        # Hash the URL (note: content at URL may change)
        return f"url:{hash_content(attachment['url'])}"
    elif attachment.get("path"):
        # Hash the path (note: file at path may change)
        return f"path:{hash_content(attachment['path'])}"
    else:
        return "empty"


def hash_tool_call(tool_call: Dict[str, Any]) -> str:
    """
    Create a hash for a tool call.

    Args:
        tool_call: Dictionary with 'name' and 'arguments'

    Returns:
        Hash representing the tool call
    """
    data = {
        "name": tool_call.get("name", ""),
        "arguments": tool_call.get("arguments", {}),
    }
    return hash_content(normalize_json(data))


def hash_tool_result(tool_result: Dict[str, Any]) -> str:
    """
    Create a hash for a tool result.

    Args:
        tool_result: Dictionary with 'name', 'output', and optionally 'attachments'

    Returns:
        Hash representing the tool result
    """
    data = {
        "name": tool_result.get("name", ""),
        "output": tool_result.get("output", ""),
    }

    # Include attachment hashes if present
    if tool_result.get("attachments"):
        data["attachments"] = [
            hash_attachment(att) for att in tool_result["attachments"]
        ]

    return hash_content(normalize_json(data))


def calculate_prompt_hash(
    system: Optional[str] = None,
    prompt: Optional[str] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    tool_results: Optional[List[Dict[str, Any]]] = None,
    options: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Calculate a hash representing the full prompt context.

    This hash uniquely identifies the input that would generate a response.
    It includes everything that affects the response but excludes metadata
    like timestamps and IDs.

    Args:
        system: System message
        prompt: User prompt
        attachments: List of attachment dicts
        tool_calls: List of tool call dicts
        tool_results: List of tool result dicts
        options: Model options (temperature, etc.) - only deterministic ones

    Returns:
        SHA-256 hash of the prompt context
    """
    components = []

    # System message
    if system:
        components.append(f"system:{hash_content(system)}")

    # User prompt
    if prompt:
        components.append(f"prompt:{hash_content(prompt)}")

    # Attachments
    if attachments:
        att_hashes = [hash_attachment(a) for a in attachments]
        components.append(f"attachments:{','.join(sorted(att_hashes))}")

    # Tool calls (from previous turn)
    if tool_calls:
        tc_hashes = [hash_tool_call(tc) for tc in tool_calls]
        components.append(f"tool_calls:{','.join(tc_hashes)}")

    # Tool results (from current turn)
    if tool_results:
        tr_hashes = [hash_tool_result(tr) for tr in tool_results]
        components.append(f"tool_results:{','.join(tr_hashes)}")

    # Options that affect output (exclude non-deterministic ones like temperature > 0)
    if options:
        # Only include options that affect deterministic output
        deterministic_options = {}
        for key, value in options.items():
            if key in ["max_tokens", "stop_sequences", "top_k"]:
                deterministic_options[key] = value
            elif key == "temperature" and value == 0:
                deterministic_options[key] = value

        if deterministic_options:
            components.append(
                f"options:{hash_content(normalize_json(deterministic_options))}"
            )

    # Combine all components
    combined = "|".join(components)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def calculate_response_hash(response: str) -> str:
    """
    Calculate a hash of the response content.

    Args:
        response: Response text

    Returns:
        SHA-256 hash of the response
    """
    return hash_content(response)


def calculate_path_hash(
    parent_path_hash: Optional[str], current_prompt_hash: str
) -> str:
    """
    Calculate a cumulative path hash from root to current node.

    This represents the entire conversation path including all ancestors.

    Args:
        parent_path_hash: Path hash of parent (None for root)
        current_prompt_hash: Prompt hash of current response

    Returns:
        New path hash
    """
    if parent_path_hash is None:
        # Root node - path hash is same as prompt hash
        return current_prompt_hash

    # Combine parent path with current prompt
    combined = f"{parent_path_hash}:{current_prompt_hash}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def find_matching_response(
    db,
    conversation_id: str,
    parent_response_id: Optional[str],
    prompt_hash: str,
) -> Optional[Dict[str, Any]]:
    """
    Find an existing response that matches the given context.

    Args:
        db: Database connection
        conversation_id: Conversation ID
        parent_response_id: Parent response ID (None for root)
        prompt_hash: Hash of the prompt

    Returns:
        Response row dict if found, None otherwise
    """
    # Handle NULL parent_response_id in SQL
    if parent_response_id is None:
        result = db.execute(
            """
            SELECT id, prompt, response, prompt_hash, response_hash, path_hash, datetime_utc
            FROM responses
            WHERE conversation_id = ?
            AND parent_response_id IS NULL
            AND prompt_hash = ?
            LIMIT 1
        """,
            [conversation_id, prompt_hash],
        ).fetchone()
    else:
        result = db.execute(
            """
            SELECT id, prompt, response, prompt_hash, response_hash, path_hash, datetime_utc
            FROM responses
            WHERE conversation_id = ?
            AND parent_response_id = ?
            AND prompt_hash = ?
            LIMIT 1
        """,
            [conversation_id, parent_response_id, prompt_hash],
        ).fetchone()

    if result:
        return {
            "id": result[0],
            "prompt": result[1],
            "response": result[2],
            "prompt_hash": result[3],
            "response_hash": result[4],
            "path_hash": result[5],
            "datetime_utc": result[6],
        }
    return None


def find_or_create_response_path(
    db,
    conversation_id: str,
    message_pairs: List[Tuple[Dict, Optional[str]]],
    model: str,
) -> List[str]:
    """
    Find or create a path through the conversation tree.

    Args:
        db: Database connection
        conversation_id: Conversation ID
        message_pairs: List of (prompt_context, expected_response) tuples
        model: Model name

    Returns:
        List of response IDs representing the path
    """
    path = []
    current_parent = None
    current_path_hash = None

    for prompt_context, expected_response in message_pairs:
        # Calculate prompt hash
        prompt_hash = calculate_prompt_hash(
            system=prompt_context.get("system"),
            prompt=prompt_context.get("prompt"),
            attachments=prompt_context.get("attachments"),
            tool_calls=prompt_context.get("tool_calls"),
            tool_results=prompt_context.get("tool_results"),
            options=prompt_context.get("options"),
        )

        # Calculate path hash
        path_hash = calculate_path_hash(current_path_hash, prompt_hash)

        # Look for existing response
        existing = find_matching_response(
            db, conversation_id, current_parent, prompt_hash
        )

        if existing:
            # Found existing response
            if expected_response is None:
                # No expected response - just return what we have
                path.append(existing["id"])
                current_parent = existing["id"]
                current_path_hash = existing["path_hash"]
            elif (
                calculate_response_hash(expected_response) == existing["response_hash"]
            ):
                # Response matches - continue down this path
                path.append(existing["id"])
                current_parent = existing["id"]
                current_path_hash = existing["path_hash"]
            else:
                # Response doesn't match - need to create a branch
                # This is where we'd create a new response with same parent
                # For now, just return what we have
                path.append(existing["id"])
                current_parent = existing["id"]
                current_path_hash = existing["path_hash"]
        else:
            # No existing response - would create one here
            # For now, just return what we have
            break

    return path


def get_conversation_by_path_hash(db, path_hash: str) -> Optional[Dict[str, Any]]:
    """
    Find a response by its complete path hash.

    This is useful for quickly finding if an exact conversation path exists.

    Args:
        db: Database connection
        path_hash: Complete path hash

    Returns:
        Response row dict if found, None otherwise
    """
    result = db.execute(
        """
        SELECT id, conversation_id, prompt, response, parent_response_id, datetime_utc
        FROM responses
        WHERE path_hash = ?
        LIMIT 1
    """,
        [path_hash],
    ).fetchone()

    if result:
        return {
            "id": result[0],
            "conversation_id": result[1],
            "prompt": result[2],
            "response": result[3],
            "parent_response_id": result[4],
            "datetime_utc": result[5],
        }
    return None
