"""
Bitget API authentication utilities.
"""

import base64
import hashlib
import hmac
import time
from typing import Optional


def generate_signature(
    secret_key: str,
    timestamp: str,
    method: str,
    request_path: str,
    body: str = "",
) -> str:
    """
    Generate HMAC SHA256 signature for Bitget API authentication.
    
    The signature is created by:
    1. Concatenating: timestamp + method + requestPath + body
    2. Creating HMAC SHA256 hash with secret key
    3. Base64 encoding the result
    
    Args:
        secret_key: API secret key
        timestamp: Unix millisecond timestamp as string
        method: HTTP method (GET, POST, etc.)
        request_path: API endpoint path with query string
        body: Request body for POST requests
        
    Returns:
        Base64 encoded signature string.
    """
    message = f"{timestamp}{method.upper()}{request_path}{body}"
    
    mac = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    )
    
    return base64.b64encode(mac.digest()).decode("utf-8")


def get_timestamp() -> str:
    """
    Get current Unix timestamp in milliseconds.
    
    Returns:
        Timestamp as string.
    """
    return str(int(time.time() * 1000))


def build_auth_headers(
    api_key: str,
    secret_key: str,
    passphrase: str,
    method: str,
    request_path: str,
    body: str = "",
    timestamp: Optional[str] = None,
) -> dict[str, str]:
    """
    Build authentication headers for Bitget API requests.
    
    Args:
        api_key: API access key
        secret_key: API secret key
        passphrase: API passphrase
        method: HTTP method
        request_path: API endpoint path with query string
        body: Request body
        timestamp: Optional timestamp (generated if not provided)
        
    Returns:
        Dictionary of authentication headers.
    """
    if timestamp is None:
        timestamp = get_timestamp()
    
    signature = generate_signature(
        secret_key=secret_key,
        timestamp=timestamp,
        method=method,
        request_path=request_path,
        body=body,
    )
    
    return {
        "ACCESS-KEY": api_key,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
        "locale": "en-US",
    }
