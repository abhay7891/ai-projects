import json
import os
from typing import Any

from bson import json_util
from google.adk.agents import Agent
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from .prompt import get_prompt

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "mandate_platform")
MAX_QUERY_LIMIT = 50


def _get_database():
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=3000)
    return client, client[MONGODB_DATABASE]


def _parse_json_object(value: str, parameter_name: str) -> dict[str, Any]:
    parsed_value = json_util.loads(value or "{}")
    if not isinstance(parsed_value, dict):
        raise ValueError(f"{parameter_name} must be a JSON object.")
    return parsed_value


def _to_json_safe(value: Any) -> Any:
    return json.loads(json_util.dumps(value))


def _collection_not_found(collection_name: str) -> dict[str, str]:
    return {
        "status": "error",
        "error": (
            f"Collection '{collection_name}' was not found in "
            f"database '{MONGODB_DATABASE}'."
        ),
    }


def _collection_exists(database: Any, collection_name: str) -> bool:
    return collection_name in database.list_collection_names()


def list_mongodb_collections() -> dict[str, Any]:
    """List collections in the configured mandate MongoDB database."""
    client = None
    try:
        client, database = _get_database()
        return {
            "status": "success",
            "database": MONGODB_DATABASE,
            "collections": database.list_collection_names(),
        }
    except PyMongoError as error:
        return {
            "status": "error",
            "error": f"Could not list MongoDB collections: {error}",
        }
    finally:
        if client is not None:
            client.close()


def query_mongodb_collection(
    collection_name: str,
    filter_json: str = "{}",
    projection_json: str = "{}",
    limit: int = 10,
) -> dict[str, Any]:
    """Find documents in a MongoDB collection without modifying data.

    Args:
        collection_name: Existing collection to query in the configured database.
        filter_json: MongoDB find filter as a JSON object, for example
            '{"mandateId": "M-123"}' or '{"status": {"$in": ["active"]}}'.
            MongoDB Extended JSON values such as ObjectIds are supported.
        projection_json: Optional MongoDB projection as a JSON object, for example
            '{"_id": 0, "mandateId": 1, "status": 1}'.
        limit: Maximum number of matching documents to return. Values above 50
            are capped to keep tool responses small.
    """
    client = None
    try:
        if limit < 1:
            return {"status": "error", "error": "limit must be at least 1."}

        filter_document = _parse_json_object(filter_json, "filter_json")
        projection = _parse_json_object(projection_json, "projection_json")
        capped_limit = min(limit, MAX_QUERY_LIMIT)

        client, database = _get_database()
        if not _collection_exists(database, collection_name):
            return _collection_not_found(collection_name)

        documents = list(
            database[collection_name]
            .find(filter_document, projection or None)
            .limit(capped_limit)
        )
        return {
            "status": "success",
            "database": MONGODB_DATABASE,
            "collection": collection_name,
            "filter": _to_json_safe(filter_document),
            "limit": capped_limit,
            "documents": _to_json_safe(documents),
        }
    except ValueError as error:
        return {"status": "error", "error": str(error)}
    except PyMongoError as error:
        return {
            "status": "error",
            "error": f"Could not query MongoDB collection: {error}",
        }
    finally:
        if client is not None:
            client.close()


def insert_mongodb_document(
    collection_name: str,
    document_json: str,
) -> dict[str, Any]:
    """Insert one document into an existing MongoDB collection.

    Args:
        collection_name: Existing collection to insert into in the configured
            database.
        document_json: New MongoDB document as a JSON object. MongoDB Extended
            JSON values are supported. Omit `_id` unless a specific unique value
            is required.
    """
    client = None
    try:
        document = _parse_json_object(document_json, "document_json")
        if not document:
            return {
                "status": "error",
                "error": "document_json must include at least one field.",
            }

        client, database = _get_database()
        if not _collection_exists(database, collection_name):
            return _collection_not_found(collection_name)

        result = database[collection_name].insert_one(document)
        return {
            "status": "success",
            "database": MONGODB_DATABASE,
            "collection": collection_name,
            "inserted_id": _to_json_safe(result.inserted_id),
        }
    except ValueError as error:
        return {"status": "error", "error": str(error)}
    except PyMongoError as error:
        return {
            "status": "error",
            "error": f"Could not insert MongoDB document: {error}",
        }
    finally:
        if client is not None:
            client.close()


def update_mongodb_document(
    collection_name: str,
    filter_json: str,
    update_json: str,
) -> dict[str, Any]:
    """Update one MongoDB document matched by a non-empty filter.

    Args:
        collection_name: Existing collection to update in the configured database.
        filter_json: Non-empty MongoDB filter as a JSON object that identifies the
            document to update. MongoDB Extended JSON values are supported.
        update_json: MongoDB update operator document as a JSON object, for
            example '{"$set": {"status": "active"}}'.
    """
    client = None
    try:
        filter_document = _parse_json_object(filter_json, "filter_json")
        update_document = _parse_json_object(update_json, "update_json")
        if not filter_document:
            return {
                "status": "error",
                "error": "filter_json must be non-empty for updates.",
            }
        if not update_document:
            return {
                "status": "error",
                "error": "update_json must include an update operation.",
            }
        if not all(key.startswith("$") for key in update_document):
            return {
                "status": "error",
                "error": (
                    "update_json must use MongoDB update operators such as "
                    "$set or $unset."
                ),
            }

        client, database = _get_database()
        if not _collection_exists(database, collection_name):
            return _collection_not_found(collection_name)

        result = database[collection_name].update_one(
            filter_document,
            update_document,
        )
        return {
            "status": "success",
            "database": MONGODB_DATABASE,
            "collection": collection_name,
            "filter": _to_json_safe(filter_document),
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
        }
    except ValueError as error:
        return {"status": "error", "error": str(error)}
    except PyMongoError as error:
        return {
            "status": "error",
            "error": f"Could not update MongoDB document: {error}",
        }
    finally:
        if client is not None:
            client.close()


def delete_mongodb_document(
    collection_name: str,
    filter_json: str,
) -> dict[str, Any]:
    """Delete one MongoDB document matched by a non-empty filter.

    Args:
        collection_name: Existing collection to delete from in the configured
            database.
        filter_json: Non-empty MongoDB filter as a JSON object that identifies the
            document to delete. MongoDB Extended JSON values are supported.
    """
    client = None
    try:
        filter_document = _parse_json_object(filter_json, "filter_json")
        if not filter_document:
            return {
                "status": "error",
                "error": "filter_json must be non-empty for deletes.",
            }

        client, database = _get_database()
        if not _collection_exists(database, collection_name):
            return _collection_not_found(collection_name)

        result = database[collection_name].delete_one(filter_document)
        return {
            "status": "success",
            "database": MONGODB_DATABASE,
            "collection": collection_name,
            "filter": _to_json_safe(filter_document),
            "deleted_count": result.deleted_count,
        }
    except ValueError as error:
        return {"status": "error", "error": str(error)}
    except PyMongoError as error:
        return {
            "status": "error",
            "error": f"Could not delete MongoDB document: {error}",
        }
    finally:
        if client is not None:
            client.close()


root_agent = Agent(
    model='gemini-3.1-flash-lite',
    name='mandate_agent',
    description='Answers mandate questions using MongoDB data.',
    instruction=get_prompt(),
    tools=[
        list_mongodb_collections,
        query_mongodb_collection,
        insert_mongodb_document,
        update_mongodb_document,
        delete_mongodb_document,
    ],
)
