"""
Actor to extract full profile data for public Instagram accounts.

- Does not require login or cookies.
- Uses the public endpoint `https://i.instagram.com/api/v1/users/web_profile_info/?username=<user>`
  (with X-IG-App-ID header).
- For each profile, it fetches the complete user data object.
- Extracts a comprehensive list of fields from the user object.
- Saves each profile's data to the dataset.
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

# List of all fields to be extracted from the user data object.
DESIRED_FIELDS = [
    "about", "account_badges", "account_category", "account_type", 
    "active_standalone_fundraisers", "additional_business_addresses", 
    "adjusted_banners_order", "ads_incentive_expiration_date", "ads_page_id", 
    "ads_page_name", "allow_manage_memorialization", "auto_expand_chaining", 
    "avatar_status", "bio_links", "biography", "biography_email", 
    "biography_with_entities", "birthday_today_visibility_for_viewer", 
    "broadcast_chat_preference_status", "business_contact_method", 
    "can_add_fb_group_link_on_profile", "can_hide_category", 
    "can_hide_public_contacts", "can_use_affiliate_partnership_messaging_as_brand", 
    "can_use_affiliate_partnership_messaging_as_creator", 
    "can_use_branded_content_discovery_as_brand", 
    "can_use_branded_content_discovery_as_creator", 
    "can_use_paid_partnership_messaging_as_creator", "category", "category_id", 
    "chaining_results", "chaining_suggestions", "chaining_upsell_cards", 
    "charity_profile_fundraiser_info", "contact_phone_number", 
    "creator_shopping_info", "current_catalog_id", "direct_messaging", 
    "disable_profile_shop_cta", "eligible_for_text_app_activation_badge", 
    "enable_add_school_in_edit_profile", "existing_user_age_collection_enabled", 
    "external_lynx_url", "external_url", "fan_club_info", 
    "fb_page_call_to_action_id", "fbe_app_id", "fbe_label", "fbe_partner", 
    "fbe_url", "fbid_v2", "feed_post_reshare_disabled", "follow_friction_type", 
    "follower_count", "following_count", "full_name", 
    "has_active_charity_business_profile_fundraiser", "has_anonymous_profile_picture", 
    "has_biography_translation", "has_chaining", "has_collab_collections", 
    "has_ever_selected_topics", "has_exclusive_feed_content", 
    "has_fan_club_subscriptions", "has_gen_ai_personas_for_profile_banner", 
    "has_guides", "has_highlight_reels", "has_ig_profile", "has_igtv_series", 
    "has_music_on_profile", "has_nme_badge", "has_private_collections", 
    "has_public_tab_threads", "has_videos", "has_views_fetching", 
    "hd_multiple_profile_picture_urls", "hd_profile_pic_url_info", 
    "hd_profile_pic_versions", "highlight_reshare_disabled", 
    "highlights_tray_type", "id", "include_direct_blacklist_status", 
    "instagram_pk", "interop_messaging_user_fbid", "is_active_on_text_post_app", 
    "is_auto_confirm_enabled_for_all_reciprocal_follow_requests", "is_bestie", 
    "is_business", "is_call_to_action_enabled", "is_category_tappable", 
    "is_creator_agent_enabled", "is_direct_roll_call_enabled", 
    "is_eligible_for_diverse_owned_business_info", 
    "is_eligible_for_meta_verified_enhanced_link_sheet", 
    "is_eligible_for_meta_verified_enhanced_link_sheet_consumption", 
    "is_eligible_for_meta_verified_label", 
    "is_eligible_for_meta_verified_links_in_reels", 
    "is_eligible_for_meta_verified_multiple_addresses_consumption", 
    "is_eligible_for_meta_verified_multiple_addresses_creation", 
    "is_eligible_for_meta_verified_related_accounts", 
    "is_eligible_for_post_boost_mv_upsell", "is_eligible_for_request_message", 
    "is_eligible_for_slide", "is_eligible_to_display_diverse_owned_business_info", 
    "is_facebook_onboarded_charity", "is_favorite", "is_favorite_for_clips", 
    "is_favorite_for_highlights", "is_favorite_for_stories", "is_in_canada", 
    "is_interest_account", "is_memorialized", 
    "is_meta_verified_related_accounts_display_enabled", "is_new_to_instagram", 
    "is_opal_enabled", "is_open_to_collab", "is_oregon_custom_gender_consented", 
    "is_parenting_account", "is_potential_business", "is_prime_onboarding_account", 
    "is_private", "is_profile_audio_call_enabled", 
    "is_profile_broadcast_sharing_enabled", "is_profile_picture_expansion_enabled", 
    "is_profile_search_enabled", "is_recon_ad_cta_on_profile_eligible_with_viewer", 
    "is_regulated_c18", "is_regulated_news_in_viewer_location", 
    "is_remix_setting_enabled_for_posts", "is_remix_setting_enabled_for_reels", 
    "is_ring_creator", "is_secondary_account_creation", "is_stories_teaser_muted", 
    "is_supervision_features_enabled", "is_verified", "is_whatsapp_linked", 
    "latest_besties_reel_media", "latest_reel_media", "linked_fb_info", 
    "live_subscription_status", "location_data", "media_count", 
    "merchant_checkout_style", "meta_verified_benefits_info", 
    "meta_verified_related_accounts_count", "meta_verified_related_accounts_info", 
    "multiple_profile_picture_urls", "nametag", 
    "nonpro_can_maybe_see_profile_hypercard", "not_meta_verified_friction_info", 
    "open_external_url_with_in_app_browser", "page_id", "page_name", 
    "pinned_channels_info", "posts_subscription_status", 
    "primary_profile_link_type", "professional_conversion_suggested_account_type", 
    "profile_context", "profile_context_facepile_users", 
    "profile_context_links_with_user_ids", "profile_overlay_info", 
    "profile_pic_genai_tool_info", "profile_pic_id", "profile_pic_url", 
    "profile_pic_url_hd", "profile_reels_sorting_eligibility", "profile_type", 
    "pronouns", "public_email", "public_phone_country_code", 
    "public_phone_number", "recon_features", "recs_from_friends", 
    "reels_subscription_status", "relevant_news_regulation_locations", 
    "remove_message_entrypoint", "seller_shoppable_feed_type", 
    "should_show_tagged_tab", "show_account_transparency_details", 
    "show_blue_badge_on_main_profile", "show_post_insights_entry_point", 
    "show_schools_badge", "show_shoppable_feed", "show_wa_link_on_profile", 
    "spam_follower_setting_enabled", "stories_subscription_status", 
    "text_app_last_visited_time", "text_post_app_badge_label", 
    "text_post_new_post_count", "third_party_downloads_enabled", 
    "threads_profile_glyph_url", "total_ar_effects", "total_igtv_videos", 
    "transparency_product_enabled", "trial_clips_enabled", 
    "trial_clips_rate_limiting", "upcoming_events", "username", 
    "views_on_grid_status", "whatsapp_number"
]

# --- Main Logic Function (Modified) ---

async def fetch_profile(client: httpx.AsyncClient, username: str) -> dict:
    """Fetches the profile and extracts the desired fields."""
    url = IG_ENDPOINT.format(username=username)
    try:
        r = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
        r.raise_for_status()
        user_data = r.json().get("data", {}).get("user")

        if not user_data:
            return {"username": username, "error": "Profile does not exist or is private"}

        # Prepare the output dictionary, starting with the username for context.
        output = {"username": username}

        # Iterate through the desired fields and extract them from the user_data.
        # Using .get() is safe and will return None if a field is not present.
        for field in DESIRED_FIELDS:
            output[field] = user_data.get(field)
        
        output["error"] = None  # Add an error field to indicate success.
        return output

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
        
        # Best practice for Pay-Per-Result (PPR) actors:
        # Only push to dataset (and count as a result) if there was no error.
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
        # Use residential proxies for better success rates.
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

        # Process tasks as they complete to provide real-time feedback.
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
