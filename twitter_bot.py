import tweepy
import time
import requests
import json
from datetime import datetime, timezone
import logging
import os
from tweepy import OAuth1UserHandler, API
import traceback

# Try to import OpenAI - handle different versions
openai_client = None
try:
    # Try new OpenAI v1.x
    from openai import OpenAI
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if openai_api_key:
        openai_client = OpenAI(api_key=openai_api_key)
        logging.info("OpenAI v1.x client initialized")
except ImportError:
    try:
        # Try old OpenAI v0.x
        import openai
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            openai.api_key = openai_api_key
            openai_client = "legacy"  # Flag for legacy usage
            logging.info("OpenAI v0.x client initialized")
    except ImportError:
        logging.warning("OpenAI library not available")
        openai_client = None

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

# API keys
api_key = os.getenv("TWITTER_API_KEY")
api_secret = os.getenv("TWITTER_API_SECRET")
access_token = os.getenv("TWITTER_ACCESS_TOKEN")
access_token_secret = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

# POPRAWIONA LINIA:
OUTLIGHT_API_URL = "https://outlight.fun/api/tokens/most-called?timeframe=1h"

def safe_tweet_with_retry(client, text, max_retries=3):
    """
    Safely send tweet with rate limit handling and retry logic
    """
    for attempt in range(max_retries):
        try:
            response = client.create_tweet(text=text)
            logging.info(f"Tweet sent successfully! ID: {response.data['id']}")
            return response
        except tweepy.TooManyRequests as e:
            reset_time = int(e.response.headers.get('x-rate-limit-reset', 0))
            current_time = int(time.time())
            wait_time = max(reset_time - current_time + 60, 300)
            logging.warning(f"Rate limit exceeded. Attempt {attempt + 1}/{max_retries}. Waiting {wait_time} seconds.")
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            else:
                logging.error("Maximum retry attempts for tweeting exceeded.")
                raise e
        except (tweepy.Forbidden, tweepy.BadRequest) as e:
            logging.error(f"Critical Twitter API error: {e}")
            raise e
        except Exception as e:
            logging.error(f"Unexpected error on tweet attempt {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                raise e
            time.sleep(30)
    return None

def get_top_tokens():
    """Fetch data from outlight.fun API"""
    try:
        response = requests.get(OUTLIGHT_API_URL, timeout=30)
        response.raise_for_status()
        data = response.json()

        tokens_with_filtered_calls = []
        for token in data:
            channel_calls = token.get('channel_calls', [])
            calls_above_30 = [call for call in channel_calls if call.get('win_rate', 0) > 30]
            count_calls = len(calls_above_30)
            if count_calls > 0:
                token_copy = token.copy()
                token_copy['filtered_calls'] = count_calls
                tokens_with_filtered_calls.append(token_copy)

        sorted_tokens = sorted(tokens_with_filtered_calls, key=lambda x: x.get('filtered_calls', 0), reverse=True)
        return sorted_tokens[:3]
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching data from API: {e}")
        return None

def generate_ai_tweet(top_3_tokens):
    """Generate intelligent tweet using OpenAI with full contract addresses"""
    if not openai_client:
        logging.error("OpenAI client not available. Cannot generate tweet.")
        return None
        
    token_data = []
    for i, token in enumerate(top_3_tokens, 1):
        calls = token.get('filtered_calls', 0)
        symbol = token.get('symbol', 'Unknown')
        address = token.get('address', 'No Address Provided')
        # Używamy pełnego adresu
        token_data.append(f"{i}. ${symbol} - {calls} calls - CA: {address}")
    
    data_summary = "\n".join(token_data)
    
    system_prompt = """You are MONTY, an AI agent with a distinctive style for crypto content.

PERSONALITY & STYLE:
- Brilliant and witty.
- Use crypto-appropriate metaphors.
- Very short texts, abbreviated thoughts.
- Funny and slightly witty but never rude.

CONTENT FOCUS:
- Crypto analytics and Solana meme tokens.
- **When mentioning a token, include its symbol and its full Contract Address (CA) for user convenience.**
- Use effective hooks.

LANGUAGE & LIMITS:
- English B1/B2 level max.
- Make each post unique and engaging."""
    
    prompt = f"""Create a crypto Twitter post about the most called tokens in the last hour as MONTY.

DATA:
{data_summary}

Create 1 engaging post:
- Start with a strong hook.
- **Include the token data (Symbol and full CA) naturally.**
- Use MONTY's witty, brief style.
- Max 270 chars preferred.
- Include relevant emojis.

Just return the tweet text, no labels."""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            logging.info(f"Generating AI tweet (Attempt {attempt + 1}/{max_retries})...")
            
            if openai_client == "legacy":
                import openai
                response = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}], max_tokens=300, temperature=0.8, request_timeout=30)
                ai_response = response.choices[0].message.content.strip()
            else:
                response = openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}], max_tokens=300, temperature=0.8, timeout=30.0)
                ai_response = response.choices[0].message.content.strip()

            if not ai_response:
                raise ValueError("AI returned an empty response")
            
            logging.info(f"AI Response received: {len(ai_response)} characters")
            
            main_tweet = ai_response.strip().replace("Tweet:", "").replace("MAIN_TWEET:", "").strip()
            
            link_to_add = "\n\n🔗 outlight.fun"
            max_text_length = 280 - len(link_to_add)

            if len(main_tweet) > max_text_length:
                main_tweet = main_tweet[:max_text_length - 3] + "..."
                logging.warning(f"AI tweet truncated to fit the link.")
            
            main_tweet += link_to_add
            
            logging.info("✅ AI tweet generated successfully!")
            return main_tweet

        except Exception as e:
            logging.error(f"Error on AI generation attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5
                logging.info(f"Waiting {wait_time} seconds before retrying...")
                time.sleep(wait_time)
            else:
                logging.error("All attempts to generate AI tweet failed.")
                logging.error(f"Full traceback: {traceback.format_exc()}")
                return None
    return None

def main():
    logging.info("GitHub Action: Bot execution started.")

    if not all([api_key, api_secret, access_token, access_token_secret]):
        logging.error("Missing required Twitter API keys. Terminating.")
        return
    
    if not openai_client:
        logging.error("❌ CRITICAL: OpenAI API key not found. Terminating.")
        return

    logging.info("✅ Clients ready!")

    try:
        client = tweepy.Client(consumer_key=api_key, consumer_secret=api_secret, access_token=access_token, access_token_secret=access_token_secret)
        me = client.get_me()
        logging.info(f"Successfully authenticated as: @{me.data.username}")
    except Exception as e:
        logging.error(f"Error setting up Twitter client: {e}")
        return

    top_3 = get_top_tokens()
    if not top_3:
        logging.warning("No token data available. Skipping tweet for this run.")
        return

    logging.info("=== GENERATING MONTY AI TWEET ===")
    tweet_text = generate_ai_tweet(top_3)
    
    if not tweet_text:
        logging.error("Tweet generation failed. Nothing to send for this run.")
        return

    logging.info(f"📝 MONTY tweet prepared for sending ({len(tweet_text)} chars):")
    logging.info(f"   Content: {tweet_text.replace(chr(10), ' ')}")

    try:
        logging.info("=== SENDING MONTY TWEET ===")
        main_tweet_response = safe_tweet_with_retry(client, tweet_text)
        
        if main_tweet_response:
            main_tweet_id = main_tweet_response.data['id']
            logging.info(f"🎉 SUCCESS: MONTY AI tweet posted!")
            logging.info(f"   🔗 Tweet URL: https://x.com/{me.data.username}/status/{main_tweet_id}")
        else:
            logging.error("❌ CRITICAL ERROR: Failed to send tweet after retries!")

    except Exception as e:
        logging.error(f"Unexpected error during tweet sending: {e}")
        logging.error(f"Full traceback: {traceback.format_exc()}")

    logging.info("GitHub Action: Bot execution finished.")

if __name__ == "__main__":
    main()
