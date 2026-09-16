"""Small shared HTTP helper: retry transient failures, never log request data."""
import logging
import time

import requests

logger = logging.getLogger(__name__)


def post_json(url, headers, payload, timeout):
    """At most two attempts; bad credentials and invalid requests aren't retried."""
    for attempt in range(2):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 0:
                    logger.warning('Provider temporarily unavailable (HTTP %s); retrying', response.status_code)
                    time.sleep(1)
                    continue
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 0:
                time.sleep(1)
                continue
            logger.warning('Provider unavailable after two attempts')
        except (requests.RequestException, ValueError):
            logger.warning('Provider returned an unsuccessful or invalid response')
            return None
    return None
