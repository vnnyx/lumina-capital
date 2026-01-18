"""
Bitget API HTTP client.
"""

import json
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.adapters.bitget.auth import build_auth_headers, get_timestamp
from src.infrastructure.config import Settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class BitgetAPIError(Exception):
    """Exception for Bitget API errors."""
    
    def __init__(self, code: str, message: str, response: Optional[dict] = None):
        self.code = code
        self.message = message
        self.response = response
        super().__init__(f"Bitget API Error [{code}]: {message}")


class BitgetClient:
    """
    HTTP client for Bitget API.
    
    Handles authentication, rate limiting, and error handling.
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize Bitget client.
        
        Args:
            settings: Application settings with API credentials.
        """
        self.settings = settings
        self.base_url = settings.bitget_base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self) -> "BitgetClient":
        """Async context manager entry."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    @property
    def client(self) -> httpx.AsyncClient:
        """Get the HTTP client, ensuring it's initialized."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client
    
    def _build_url(self, path: str, params: Optional[dict[str, Any]] = None) -> str:
        """Build full URL with query parameters."""
        url = f"{self.base_url}{path}"
        if params:
            # Filter out None values
            filtered_params = {k: v for k, v in params.items() if v is not None}
            if filtered_params:
                url = f"{url}?{urlencode(filtered_params)}"
        return url
    
    def _get_request_path(self, path: str, params: Optional[dict[str, Any]] = None) -> str:
        """Get request path with query string for signing."""
        if params:
            filtered_params = {k: v for k, v in params.items() if v is not None}
            if filtered_params:
                return f"{path}?{urlencode(filtered_params)}"
        return path
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def get(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
        authenticated: bool = False,
    ) -> dict[str, Any]:
        """
        Make authenticated GET request.
        
        Args:
            path: API endpoint path
            params: Query parameters
            authenticated: Whether to include auth headers
            
        Returns:
            Parsed JSON response data.
            
        Raises:
            BitgetAPIError: If API returns an error.
        """
        url = self._build_url(path, params)
        request_path = self._get_request_path(path, params)
        
        headers = {"Content-Type": "application/json", "locale": "en-US"}
        
        if authenticated:
            headers = build_auth_headers(
                api_key=self.settings.bitget_api_access_key,
                secret_key=self.settings.bitget_api_secret_key,
                passphrase=self.settings.bitget_api_passphrase,
                method="GET",
                request_path=request_path,
            )
        
        logger.debug("GET request", url=url, authenticated=authenticated)
        
        response = await self.client.get(url, headers=headers)
        return self._handle_response(response)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def post(
        self,
        path: str,
        data: Optional[dict[str, Any]] = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        """
        Make authenticated POST request.
        
        Args:
            path: API endpoint path
            data: Request body
            authenticated: Whether to include auth headers
            
        Returns:
            Parsed JSON response data.
            
        Raises:
            BitgetAPIError: If API returns an error.
        """
        body = json.dumps(data) if data else ""
        url = f"{self.base_url}{path}"
        
        headers = {"Content-Type": "application/json", "locale": "en-US"}
        
        if authenticated:
            headers = build_auth_headers(
                api_key=self.settings.bitget_api_access_key,
                secret_key=self.settings.bitget_api_secret_key,
                passphrase=self.settings.bitget_api_passphrase,
                method="POST",
                request_path=path,
                body=body,
            )
        
        logger.debug("POST request", url=url, authenticated=authenticated)
        
        response = await self.client.post(url, headers=headers, content=body)
        return self._handle_response(response)
    
    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """
        Handle API response and raise errors if needed.
        
        Args:
            response: HTTP response object
            
        Returns:
            Parsed response data.
            
        Raises:
            BitgetAPIError: If API returns an error code.
        """
        try:
            result = response.json()
        except json.JSONDecodeError as e:
            logger.error("Failed to parse response", status=response.status_code, body=response.text)
            raise BitgetAPIError("PARSE_ERROR", f"Failed to parse response: {e}")
        
        # Bitget uses "00000" for success
        code = result.get("code", "")
        
        if code != "00000":
            msg = result.get("msg", "Unknown error")
            logger.error("API error", code=code, message=msg, response=result)
            raise BitgetAPIError(code, msg, result)
        
        return result.get("data", result)
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
