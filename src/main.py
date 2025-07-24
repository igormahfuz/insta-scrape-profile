"""
Actor to extract full profile data for public Instagram accounts.

- Does not require login or cookies.
- Uses the public endpoint `https://i.instagram.com/api/v1/users/web_profile_info/?username=<user>`
  (with X-IG-App-ID header).
- For each profile, it fetches the complete user data object and returns it.
- This approach is robust to API changes as it captures the entire raw user data.
"""

from __future__ import annotations
from apify import Actor
import httpx
import asyncio
import importlib.metadata

# Endpoint to get public user information.
IG_ENDPOINT = (
    "https://i.instagram.com/api/v1/users/web_profile_info/"
    "?username={username}"
)

# This App ID is public and used by the Instagram web app.
HEADERS = {
    "x-ig-app-id": "936619743392459",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}

# --- Main Logic Function (Corrected) ---

async def fetch_profile(client: httpx.AsyncClient, username: str) -> dict:
    """Fetches the profile and returns the entire user data object."""
    url = IG_ENDPOINT.format(username=username)
    try:
        r = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
        r.raise_for_status()
        user_data = r.json().get("data", {}).get("user")

        if not user_data:
            return {"username": username, "error": "Profile does not exist or is private"}

        # Return the entire user object. This is more robust than cherry-picking fields.
        # The username is added for context.
        return {
            "username": username,
            "profile_data": user_data,
            "error": None,
        }

    except Exception as e:
        # Let the retry wrapper handle exceptions.
        raise e

# --- Wrapper with Retries (Unmodified) ---

async def fetch_with_retries(username: str, proxy_config) -> dict:
    """Wraps the fetch function with retry logic for network-related errors."""
    MAX_RETRIES = 3
    BASE_DELAY_SECONDS = 2
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            session_id = f'session_{username}_{attempt}'
            proxy_url = await proxy_config.new_url(session_id=session_id)
            transport = httpx.AsyncHTTPTransport(proxy=proxy_url)
            async with httpx.AsyncClient(transport=transport) as client:
                return await fetch_profile(client, username)
        except (httpx.HTTPStatusError, httpx.ProxyError, httpx.ReadTimeout) as e:
            last_error = e
            Actor.log.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed for '{username}': {type(e).__name__}. Retrying...")
            delay = BASE_DELAY_SECONDS * (2 ** attempt)
            await asyncio.sleep(delay)
        except Exception as e:
            return {"username": username, "error": f"An unexpected error occurred: {type(e).__name__}: {e}"}

    return {"username": username, "error": f"Failed after {MAX_RETRIES} attempts: {type(last_error).__name__}"}

# --- Processing and Saving Function (Unmodified) ---

async def process_and_save_username(
    username: str,
    proxy_config,
    semaphore: asyncio.Semaphore
) -> dict:
    """Processes a single username and saves the result to the dataset if successful."""
    async with semaphore:
        result = await fetch_with_retries(username, proxy_config)
        
        if result.get("error") is None:
            await Actor.push_data(result)
        
        return result

# --- Main Actor Function (Unmodified) ---

async def main() -> None:
    """Main function to run the actor."""
    async with Actor:
        Actor.log.info(f"Using httpx version: {importlib.metadata.version('httpx')}")

        inp = await Actor.get_input() or {}
        usernames: list[str] = inp.get("usernames", [])
        concurrency = inp.get("concurrency", 100)

        if not usernames:
            raise ValueError("Input 'usernames' (a list of profiles) is required.")

        semaphore = asyncio.Semaphore(concurrency)
        proxy_configuration = await Actor.create_proxy_configuration(groups=['RESIDENTIAL'])
        
        total_usernames = len(usernames)
        processed_count = 0
        
        Actor.log.info(f"Starting processing for {total_usernames} usernames with a concurrency of {concurrency}.")

        tasks = []
        for username in usernames:
            clean_username = username.strip("@ ")
            if not clean_username:
                total_usernames -= 1
                continue
            
            task = process_and_save_username(clean_username, proxy_configuration, semaphore)
            tasks.append(task)

        for future in asyncio.as_completed(tasks):
            result = await future
            processed_count += 1
            
            username_processed = result.get('username', 'N/A')
            msg = f"{processed_count}/{total_usernames} -> {username_processed}"
            
            if result.get("error"):
                msg += f" ❌ ({result['error']})"
            else:
                msg += " ✔"
            
            Actor.log.info(msg)
            await Actor.set_status_message(msg)
        
        Actor.log.info("Processing complete.")
