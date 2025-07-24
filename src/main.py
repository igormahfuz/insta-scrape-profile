"""
Actor to extract deep profile data for public Instagram accounts.

This actor uses a two-pronged approach:
1.  It hits the authenticated web profile endpoint to get the main user data.
2.  If the user has public contacts, it makes a second API call to a specific business endpoint to get the public email and phone number.
3.  It also uses regex to parse the biography for any contact info users might have written there.
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

# --- Helper Functions ---

def parse_bio_for_contacts(biography: str) -> dict:
    """Uses regex to find email and phone numbers in the bio text."""
    if not biography:
        return {}

    # Regex for finding email addresses
    email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    emails_found = re.findall(email_regex, biography)
    
    # Regex for finding phone numbers (basic, can be improved)
    phone_regex = r'(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,3}\)?[-.\s]?)?\d{4,5}[-.\s]?\d{4}'
    phones_found = re.findall(phone_regex, biography)

    return {
        "email_from_bio": emails_found[0] if emails_found else None,
        "phone_from_bio": phones_found[0] if phones_found else None,
    }

# --- Main Logic ---

async def fetch_deep_profile(
    client: httpx.AsyncClient, 
    username: str, 
    session_cookies: str
) -> dict:
    """Fetches profile data using a multi-step process."""
    headers = {
        "Cookie": session_cookies,
        "x-ig-app-id": "936619743392459",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    }

    try:
        # 1. Get the main profile data
        profile_url = PROFILE_ENDPOINT.format(username=username)
        r_profile = await client.get(profile_url, headers=headers, follow_redirects=True, timeout=30)
        r_profile.raise_for_status()
        
        profile_json = r_profile.json()
        user_data = profile_json.get("data", {}).get("user")

        if not user_data:
            Actor.log.warning(f"User object not found for {username}. Response: {profile_json}")
            return {"username": username, "error": "User object not found"}

        # 2. Parse bio for any immediate contact info
        bio_contacts = parse_bio_for_contacts(user_data.get('biography'))
        user_data['email_from_bio'] = bio_contacts.get('email_from_bio')
        user_data['phone_from_bio'] = bio_contacts.get('phone_from_bio')

        # 3. If public contacts are available, make a second call for them
        if user_data.get('should_show_public_contacts'):
            user_id = user_data.get('id')
            if user_id:
                contact_url = CONTACT_ENDPOINT.format(user_id=user_id)
                try:
                    r_contact = await client.get(contact_url, headers=headers, timeout=20)
                    r_contact.raise_for_status()
                    contact_data = r_contact.json()
                    
                    # Merge the contact data into the main user object
                    user_data['public_phone_number'] = contact_data.get('public_phone_number')
                    user_data['public_phone_country_code'] = contact_data.get('public_phone_country_code')
                    user_data['public_email'] = contact_data.get('public_email')
                    user_data['contact_method'] = contact_data.get('contact_method') # e.g., CALL, TEXT, EMAIL

                except httpx.HTTPStatusError as e_contact:
                    Actor.log.warning(f"Could not fetch contact details for {username} (User ID: {user_id}). Status: {e_contact.response.status_code}")
                except Exception as e_contact:
                    Actor.log.warning(f"An error occurred during contact fetching for {username}: {e_contact}")

        return {
            "username": username,
            "profile_data": user_data,
            "error": None,
        }

    except httpx.HTTPStatusError as e:
        if e.response.status_code in [401, 403]:
            Actor.log.error(f"Authentication failed for {username}. Cookies may be invalid. Status: {e.response.status_code}")
            return {"username": username, "error": "Authentication failed"}
        raise e
    except Exception as e:
        raise e

# --- Boilerplate (Retries, Main Loop) - Unmodified from previous robust versions ---

async def fetch_with_retries(username: str, proxy_config, session_cookies: str) -> dict:
    MAX_RETRIES = 3
    BASE_DELAY_SECONDS = 2
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            session_id = f'session_{username}_{attempt}'
            proxy_url = await proxy_config.new_url(session_id=session_id)
            async with httpx.AsyncClient(proxies=proxy_url) as client:
                return await fetch_deep_profile(client, username, session_cookies)
        except (httpx.HTTPStatusError, httpx.ProxyError, httpx.ReadTimeout) as e:
            last_error = e
            Actor.log.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed for '{username}': {type(e).__name__}. Retrying...")
            await asyncio.sleep(BASE_DELAY_SECONDS * (2 ** attempt))
        except Exception as e:
            return {"username": username, "error": f"An unexpected error occurred: {type(e).__name__}: {e}"}
    return {"username": username, "error": f"Failed after {MAX_RETRIES} attempts: {type(last_error).__name__}"}

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
        concurrency = inp.get("concurrency", 50)

        if not usernames or not session_cookies:
            raise ValueError("Inputs 'usernames' and 'sessionCookies' are required.")

        semaphore = asyncio.Semaphore(concurrency)
        proxy_configuration = await Actor.create_proxy_configuration(groups=['RESIDENTIAL'])
        
        total_usernames = len(usernames)
        Actor.log.info(f"Starting processing for {total_usernames} usernames.")

        tasks = [process_and_save_username(u.strip("@ "), proxy_configuration, semaphore, session_cookies) for u in usernames if u.strip("@ ")]

        processed_count = 0
        for future in asyncio.as_completed(tasks):
            result = await future
            processed_count += 1
            username_processed = result.get('username', 'N/A')
            msg = f"{processed_count}/{len(tasks)} -> {username_processed}"
            if result.get("error"):
                msg += f" ❌ ({result['error']})"
            else:
                msg += " ✔"
            Actor.log.info(msg)
            await Actor.set_status_message(msg)
        
        Actor.log.info("Processing complete.")
