"""
ELASTICSEARCH CLIENT
=====================
This file creates a connection to Elasticsearch.

Think of Elasticsearch like a very smart database that:
1. Stores JSON documents (our cloud resources and findings)
2. Searches them extremely fast using both keywords AND meaning (vectors)
3. Can run analytics queries (like SQL but for JSON)

We use it as the "long-term memory" of our security copilot.

RESILIENCE NOTE: The client is initialized lazily so the FastAPI app
starts successfully even if Elasticsearch is temporarily unreachable.
Individual API endpoints handle ES errors gracefully via try/except.
"""

from elasticsearch import Elasticsearch
import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def get_es_client():
    """
    Creates and returns an Elasticsearch client.
    Connection is validated lazily — a failed ping logs a warning but
    does NOT raise an exception, so the FastAPI app still starts.
    """
    es_host = os.getenv("ES_HOST")
    es_api_key = os.getenv("ES_API_KEY")

    if not es_host:
        logger.warning(
            "ES_HOST environment variable is not set. "
            "Elasticsearch features will be unavailable until it is configured."
        )
        # Return a client pointed at localhost as a safe no-op placeholder.
        # All API calls will return 503 from the endpoint's own try/except,
        # not crash the process.
        return Elasticsearch("http://localhost:9200")

    try:
        client = Elasticsearch(
            es_host,
            api_key=es_api_key,
            verify_certs=True,
            request_timeout=10,      # don't hang the startup thread
            retry_on_timeout=False,
        )

        # Test connection — log result but never raise
        if client.ping():
            logger.info("✅ Connected to Elasticsearch!")
        else:
            logger.warning(
                "❌ Elasticsearch ping failed. The app will still start, "
                "but data endpoints will return errors until ES is reachable."
            )

        return client

    except Exception as exc:
        logger.error(
            "Elasticsearch client creation failed: %s. "
            "The app will still start — endpoints will return 503 until fixed.",
            exc,
        )
        return Elasticsearch("http://localhost:9200")


# Singleton — one client shared across the app
es = get_es_client()