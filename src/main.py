"""
Actor to extract deep profile data for public Instagram accounts using the authenticated GraphQL API.

This actor requires Instagram session cookies to make authenticated requests.
It fetches the complete user data object, including private contact information like email and phone number.
"""

from __future__ import annotations
from apify import Actor
import httpx
import asyncio
import importlib.metadata
from urllib.parse import quote

# This is the internal GraphQL endpoint used by the Instagram web app.
GRAPHQL_ENDPOINT = "https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"

# --- Main Logic Function (Rewritten for GraphQL) ---

async def fetch_profile(client: httpx.AsyncClient, username: str, session_cookies: str) -> dict:
    """Fetches the profile using the authenticated GraphQL endpoint."""
    url = GRAPHQL_ENDPOINT.format(username=username)
    
    # Construct the headers with the provided session cookies for authentication.
    # The x-ig-app-id is a public ID used by the web app.
    headers = {
        "Cookie": session_cookies,
        "x-ig-app-id": "936619743392459",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    }

    try:
        r = await client.get(url, headers=headers, follow_redirects=True, timeout=30)
        r.raise_for_status()
        
        response_json = r.json()
        user_data = response_json.get("data", {}).get("user")

        if not user_data:
            # Log the raw response if the expected data is not found.
            Actor.log.warning(f"User object not found for {username}. Response: {response_json}")
            return {"username": username, "error": "User object not found in API response"}

        # The entire user object is returned, containing all deep profile data.
        return {
            "username": username,
            "profile_data": user_data,
            "error": None,
        }

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401 or e.response.status_code == 403:
            Actor.log.error(f"Authentication failed for {username}. Your session cookies might be invalid or expired. Status: {e.response.status_code}")
            return {"username": username, "error": "Authentication failed. Please provide valid session cookies."}
        # Let the retry wrapper handle other HTTP errors.
        raise e
    except Exception as e:
        # Let the retry wrapper handle other exceptions.
        raise e

# --- Wrapper with Retries (Unmodified) ---

async def fetch_with_retries(username: str, proxy_config, session_cookies: str) -> dict:
    """Wraps the fetch function with retry logic."""
    MAX_RETRIES = 3
    BASE_DELAY_SECONDS = 2
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            session_id = f'session_{username}_{attempt}'
            proxy_url = await proxy_config.new_url(session_id=session_id)
            transport = httpx.AsyncHTTPTransport(proxy=proxy_url)
            async with httpx.AsyncClient(transport=transport) as client:
                return await fetch_profile(client, username, session_cookies)
        except (httpx.HTTPStatusError, httpx.ProxyError, httpx.ReadTimeout) as e:
            last_error = e
            Actor.log.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed for '{username}': {type(e).__name__}. Retrying...")
            delay = BASE_DELAY_SECONDS * (2 ** attempt)
            await asyncio.sleep(delay)
        except Exception as e:
            return {"username": username, "error": f"An unexpected error occurred: {type(e).__name__}: {e}"}

    return {"username": username, "error": f"Failed after {MAX_RETRIES} attempts: {type(last_error).__name__}"}

# --- Processing and Saving Function (Modified) ---

async def process_and_save_username(
    username: str,
    proxy_config,
    semaphore: asyncio.Semaphore,
    session_cookies: str
) -> dict:
    """Processes a single username and saves the result to the dataset if successful."""
    async with semaphore:
        result = await fetch_with_retries(username, proxy_config, session_cookies)
        
        if result.get("error") is None:
            await Actor.push_data(result)
        
        return result

# --- Main Actor Function (Modified) ---

async def main() -> None:
    """Main function to run the actor."""
    async with Actor:
        Actor.log.info(f"Using httpx version: {importlib.metadata.version('httpx')}")

        inp = await Actor.get_input() or {}
        usernames: list[str] = inp.get("usernames", [])
        session_cookies: str = inp.get("sessionCookies", "")
        concurrency = inp.get("concurrency", 50)

        if not usernames:
            raise ValueError("Input 'usernames' is required.")
        if not session_cookies:
            raise ValueError("Input 'sessionCookies' is required for authentication.")

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
            
            task = process_and_save_username(clean_username, proxy_configuration, semaphore, session_cookies)
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
