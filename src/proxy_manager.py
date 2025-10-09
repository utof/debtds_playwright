import logging
from itertools import cycle
from pathlib import Path
from typing import Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class ProxyManager:
    """
    A class to manage a list of proxies and rotate through them.
    """

    def __init__(self, proxies: List[str]):
        """
        Initializes the ProxyManager with a list of proxy strings.

        Args:
            proxies (List[str]): A list of proxy strings (e.g., 'http://user:pass@host:port').
        """
        if not proxies:
            logger.warning("Proxy list is empty. Proxy functionality will be disabled.")
            self.proxies = []
            self.proxy_cycle = None
        else:
            self.proxies = proxies
            self.proxy_cycle = cycle(self.proxies)
            logger.info(f"Initialized with {len(self.proxies)} proxies.")

    def get_next_proxy(self) -> Optional[Dict[str, str]]:
        """
        Rotates through the list and returns a proxy in a Playwright-compatible format.

        Returns:
            Optional[Dict[str, str]]: A dictionary for Playwright proxy settings
                                     with server, username, and password parsed,
                                     or None if no proxies are available.
        """
        if not self.proxy_cycle:
            return None
        
        next_proxy = next(self.proxy_cycle)
        logger.info(f"Using proxy: {next_proxy}")
        
        # Parse proxy format: username:password@host:port
        if '@' in next_proxy:
            # Has authentication
            auth_part, server_part = next_proxy.rsplit('@', 1)
            if ':' in auth_part:
                username, password = auth_part.split(':', 1)
                # Add protocol if not present
                if not server_part.startswith(('http://', 'https://', 'socks5://')):
                    server_part = f"http://{server_part}"
                return {
                    "server": server_part,
                    "username": username,
                    "password": password
                }
        
        # No authentication or invalid format
        if not next_proxy.startswith(('http://', 'https://', 'socks5://')):
            next_proxy = f"http://{next_proxy}"
        return {"server": next_proxy}

    @classmethod
    def from_file(cls, file_path: Union[str, Path]):
        """
        Loads proxies from a text file (one proxy per line).

        Args:
            file_path (Union[str, Path]): The path to the text file.

        Returns:
            ProxyManager: An instance of the ProxyManager.
        """
        try:
            with open(file_path, "r") as f:
                proxies = [line.strip() for line in f if line.strip()]
            logger.info(f"Loaded {len(proxies)} proxies from {file_path}.")
            return cls(proxies)
        except FileNotFoundError:
            logger.warning(
                f"Proxy file not found at {file_path}. "
                "Proxy functionality will be disabled."
            )
            return cls([])
