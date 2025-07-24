"""
Actor to extract deep profile data for public Instagram accounts.

This actor uses a sequential, multi-step process to avoid rate-limiting:
1.  It hits the authenticated web profile endpoint to get the main user data.
2.  If the user has public contacts, it makes a second API call to get the public email and phone number.
3.  It makes a third API call to the 'chaining' endpoint to get suggested/related profiles.
4.  It also uses regex to parse the biography for any contact info and tagged accounts.
"""

from __future__ import annotations
from apify import Actor
import httpx
import asyncio
import importlib.metadata
import re

# --- Constants ---
PROFILE_ENDPOINT = "https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
CONTACT_ENDPOINT = "https://www.instagram.com/api/v1/business/users/{user_id}/contact_info/"
GRAPHQL_ENDPOINT = "https://www.instagram.com/graphql/query/"

# --- Helper Functions ---

def parse_bio(biography: str) -> dict:
    """Uses regex to find emails, phone numbers, and tagged accounts in the bio text."""
    if not biography:
        return {}

    email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    phone_regex = r'(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,3}\)?[-.\s]?)?\d{4,5}[-.\s]?\d{4}'
    tag_regex = r'@([a-zA-Z0-9_.]+)'

    return {
        "email_from_bio": re.findall(email_regex, biography),
        "phone_from_bio": re.findall(phone_regex, biography),
        "tagged_in_bio": re.findall(tag_regex, biography),
    }

# --- Main Logic (Corrected to be Sequential) ---

async def fetch_deep_profile(
    client: httpx.AsyncClient,
    username: str,
    session_cookies: str
) -> dict:
    """Fetches profile data using a sequential multi-step process."""
    headers = {
        "Cookie": session_cookies,
        "x-ig-app-id": "936619743392459",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    }

    try:
        # Step 1: Get the main profile data
        profile_url = PROFILE_ENDPOINT.format(username=username)
        r_profile = await client.get(profile_url, headers=headers, follow_redirects=True, timeout=30)
        r_profile.raise_for_status()
        user_data = r_profile.json().get("data", {}).get("user")

        if not user_data:
            return {"username": username, "error": "User object not found"}

        # Step 2: Parse bio
        bio_analysis = parse_bio(user_data.get('biography'))
        user_data.update(bio_analysis)

        user_id = user_data.get('id')
        if not user_id:
            return {"username": username, "profile_data": user_data, "error": None}

        # Step 3: Sequentially fetch contact info if available
        #if user_data.get('should_show_public_contacts'):
        #    try:
        #        r_contact = await client.get(CONTACT_ENDPOINT.format(user_id=user_id), headers=headers, timeout=20)
        #        r_contact.raise_for_status()
        #        user_data.update(r_contact.json())
        #    except Exception as e:
        #        Actor.log.warning(f"Could not fetch contact details for {username}: {e}")

        # Step 4: Sequentially fetch related profiles using GraphQL
        if user_data.get('has_chaining'):
            try:
                graphql_variables = {
                    "user_id": user_id,
                    "include_chaining": True,
                    "include_reel": False,
                    "include_suggested_users": True,
                    "include_logged_out_extras": False,
                    "include_highlight_reels": False,
                    "include_related_profiles": True, # This is the important one
                }
                params = {
                    'query_hash': '7c16654f22c819fb63d1183034a5162f',
                    'variables': json.dumps(graphql_variables),
                }
                r_chaining = await client.get(GRAPHQL_ENDPOINT, params=params, headers=headers, timeout=20)
                r_chaining.raise_for_status()
                chaining_data = r_chaining.json()
                # The response structure is different for GraphQL
                if 'data' in chaining_data and 'user' in chaining_data['data'] and 'edge_related_profiles' in chaining_data['data']['user']:
                    user_data['related_profiles'] = chaining_data['data']['user']['edge_related_profiles'].get('edges', [])
            except Exception as e:
                Actor.log.warning(f"Could not fetch related profiles for {username}: {e}")

        return {"username": username, "profile_data": user_data, "error": None}

    except httpx.HTTPStatusError as e:
        if e.response.status_code in [401, 403]:
            return {"username": username, "error": "Authentication failed"}
        raise e # Let the retry wrapper handle other status errors
    except Exception as e:
        raise e # Let the retry wrapper handle other errors

# --- Boilerplate (Retries, Main Loop) ---

async def fetch_with_retries(username: str, proxy_config, session_cookies: str) -> dict:
    MAX_RETRIES = 3
    BASE_DELAY_SECONDS = 2
    for attempt in range(MAX_RETRIES):
        try:
            session_id = f'session_{username}_{attempt}'
            proxy_url = await proxy_config.new_url(session_id=session_id)
            async with httpx.AsyncClient(proxy=proxy_url) as client:
                return await fetch_deep_profile(client, username, session_cookies)
        except (httpx.HTTPStatusError, httpx.ProxyError, httpx.ReadTimeout) as e:
            Actor.log.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed for '{username}': {type(e).__name__}. Retrying...")
            await asyncio.sleep(BASE_DELAY_SECONDS * (2 ** attempt))
        except Exception as e:
            return {"username": username, "error": f"An unexpected error occurred: {type(e).__name__}: {e}"}
    return {"username": username, "error": f"Failed after {MAX_RETRIES} attempts"}

async def process_and_save_username(username: str, proxy_config, semaphore: asyncio.Semaphore, session_cookies: str) -> dict:
    async with semaphore:
        result = await fetch_with_retries(username, proxy_config, session_cookies)
        if result.get("error") is None:
            await Actor.push_data(result)
        return result

async def main() -> None:
    async with Actor:
        Actor.log.info(f"Using httpx version: {importlib.metadata.version('httpx')}")
        inp = await Actor.get_input() or {}
        usernames: list[str] = inp.get("usernames", [])
        session_cookies: str = inp.get("sessionCookies", "")
        concurrency = inp.get("concurrency", 10) # Reduced default concurrency

        if not usernames or not session_cookies:
            raise ValueError("Inputs 'usernames' and 'sessionCookies' are required.")

        semaphore = asyncio.Semaphore(concurrency)
        proxy_configuration = await Actor.create_proxy_configuration(groups=['RESIDENTIAL'])
        
        tasks = [process_and_save_username(u.strip("@ "), proxy_configuration, semaphore, session_cookies) for u in usernames if u.strip("@ ")]
        total_tasks = len(tasks)
        Actor.log.info(f"Starting processing for {total_tasks} usernames with concurrency {concurrency}.")

        processed_count = 0
        for future in asyncio.as_completed(tasks):
            result = await future
            processed_count += 1
            username_processed = result.get('username', 'N/A')
            msg = f"{processed_count}/{total_tasks} -> {username_processed}"
            if result.get("error"):
                msg += f" ❌ ({result['error']})"
            else:
                msg += " ✔"
            Actor.log.info(msg)
            await Actor.set_status_message(msg)
        
        Actor.log.info("Processing complete.")
