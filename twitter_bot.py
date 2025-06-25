import tweepy
import time
import requests
import json
from datetime import datetime, timezone
import logging
import os
from tweepy import OAuth1UserHandler, API

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

OUTLIGHT_API_URL = "https://outlight.fun/api/tokens/most-called?timeframe=1h"

def safe_tweet_with_retry(client, text, media_ids=None, in_reply_to_tweet_id=None, max_retries=3):
    """
    Safely send tweet with rate limit handling and retry logic
    """
    for attempt in range(max_retries):
        try:
            response = client.create_tweet(
                text=text,
                media_ids=media_ids,
                in_reply_to_tweet_id=in_reply_to_tweet_id
            )
            logging.info(f"Tweet sent successfully! ID: {response.data['id']}")
            return response
            
        except tweepy.TooManyRequests as e:
            reset_time = int(e.response.headers.get('x-rate-limit-reset', 0))
            current_time = int(time.time())
            wait_time = max(reset_time - current_time + 60, 300)
            
            logging.warning(f"Rate limit exceeded. Attempt {attempt + 1}/{max_retries}")
            logging.warning(f"Waiting {wait_time} seconds before retry")
            
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            else:
                logging.error("Maximum retry attempts exceeded. Tweet not sent.")
                raise e
                
        except tweepy.Forbidden as e:
            logging.error(f"Authorization error: {e}")
            raise e
            
        except tweepy.BadRequest as e:
            logging.error(f"Bad request (possibly tweet too long?): {e}")
            raise e
            
        except Exception as e:
            logging.error(f"Unexpected error on attempt {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                raise e
            time.sleep(30)
    
    return None

def safe_media_upload(api_v1, image_path, max_retries=3):
    """
    Safely upload media with rate limit handling
    """
    if not os.path.isfile(image_path):
        logging.error(f"Image file not found: {image_path}")
        return None
    
    for attempt in range(max_retries):
        try:
            media = api_v1.media_upload(image_path)
            logging.info(f"Image uploaded successfully. Media ID: {media.media_id}")
            return media.media_id
            
        except tweepy.TooManyRequests as e:
            reset_time = int(e.response.headers.get('x-rate-limit-reset', 0))
            current_time = int(time.time())
            wait_time = max(reset_time - current_time + 60, 180)
            
            logging.warning(f"Rate limit for media upload. Attempt {attempt + 1}/{max_retries}")
            logging.warning(f"Waiting {wait_time} seconds")
            
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            else:
                logging.error("Failed to upload image after all attempts")
                return None
                
        except Exception as e:
            logging.error(f"Image upload error on attempt {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                return None
            time.sleep(30)
    
    return None

def get_top_tokens():
    """Fetch data from outlight.fun API"""
    try:
        response = requests.get(OUTLIGHT_API_URL)
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
        top_3 = sorted_tokens[:3]
        return top_3
    except Exception as e:
        logging.error(f"Error fetching data from API: {e}")
        return None

def generate_ai_tweet(top_3_tokens):
    """Generate intelligent tweet using OpenAI based on token data. Returns None on failure."""
    if not openai_client:
        logging.error("OpenAI client not initialized. Cannot generate AI tweet.")
        return None
        
    try:
        token_data = []
        for i, token in enumerate(top_3_tokens, 1):
            calls = token.get('filtered_calls', 0)
            symbol = token.get('symbol', 'Unknown')
            address = token.get('address', 'No Address')[:8] + "..."
            token_data.append(f"{i}. ${symbol} - {calls} calls - {address}")
        
        data_summary = "\n".join(token_data)
        total_calls = sum(token.get('filtered_calls', 0) for token in top_3_tokens)
        
        system_prompt = """You are MONTY, an AI agent with a distinctive style for crypto content, responding in English.

PERSONALITY & STYLE:
- Brilliant and witty like Mark Huel's comment style
- Use crypto-appropriate metaphors and references
- Minimal degen slang (sparingly used)
- Very short texts, abbreviated thoughts, no long full sentences
- Be unique, stand out in the crowd
- Funny and slightly witty but never rude
- Always praise other KOLs and their successes

CONTENT FOCUS:
- Crypto analytics and token data
- Solana memes niche specialty
- Use effective hooks in post beginnings
- Analyze X platform algorithms for better reach
- Vary responses to avoid repetition

LANGUAGE & LIMITS:
- English B1/B2 level max
- Keep within X character limits when possible
- If content needs more space, don't force limits
- Make each post unique and engaging"""
        
        prompt = f"""Create a crypto Twitter post about the most called tokens in the last hour as MONTY.

DATA:
{data_summary}

Total calls tracked: {total_calls}

Create 1 engaging post:
- Start with a strong hook
- Include the token data naturally
- Use MONTY's witty, brief style
- Max 270 chars preferred
- Include relevant emojis
- Focus on Solana/meme insights
- Make it algorithm-friendly for X engagement

Just return the tweet text, no labels."""

        logging.info("Generating AI tweets...")
        
        if openai_client == "legacy":
            import openai
            response = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}], max_tokens=300, temperature=0.8)
            ai_response = response.choices[0].message.content.strip()
        else:
            response = openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}], max_tokens=300, temperature=0.8)
            ai_response = response.choices[0].message.content.strip()
        
        logging.info(f"AI Response received: {len(ai_response)} characters")
        
        main_tweet = ai_response.strip()
        
        if main_tweet.startswith("MAIN_TWEET:"): main_tweet = main_tweet.replace("MAIN_TWEET:", "").strip()
        if main_tweet.startswith("Tweet:"): main_tweet = main_tweet.replace("Tweet:", "").strip()
        
        # Add the link at the end
        link_to_add = "\n\n🔗 outlight.fun"
        max_text_length = 280 - len(link_to_add)

        if len(main_tweet) > max_text_length:
            main_tweet = main_tweet[:max_text_length - 3] + "..."
            logging.warning(f"AI tweet truncated to {len(main_tweet)} chars to fit the link.")
        
        main_tweet += link_to_add
        
        if not main_tweet.strip():
            logging.warning("Empty AI response, cannot generate tweet.")
            return None
        
        logging.info(f"✅ AI tweet generated successfully!")
        logging.info(f"   - Tweet: {len(main_tweet)} chars")
        
        return main_tweet
        
    except Exception as e:
        logging.error(f"Error generating AI tweets: {e}")
        logging.warning("AI generation failed. No tweet will be sent.")
        return None

def main():
    logging.info("GitHub Action: Bot execution started.")

    if not all([api_key, api_secret, access_token, access_token_secret]):
        logging.error("Missing required Twitter API keys. Terminating.")
        return
    
    if not openai_client:
        logging.error("❌ CRITICAL: OpenAI API key not found. Bot requires AI to function.")
        logging.error("Add OPENAI_API_KEY to GitHub Secrets to enable MONTY AI tweets.")
        logging.info("GitHub Action: Bot execution finished - No OpenAI key found.")
        return

    logging.info("✅ OpenAI client initialized - MONTY AI ready!")

    try:
        client = tweepy.Client(consumer_key=api_key, consumer_secret=api_secret, access_token=access_token, access_token_secret=access_token_secret)
        me = client.get_me()
        logging.info(f"Successfully authenticated: @{me.data.username}")

        auth_v1 = OAuth1UserHandler(api_key, api_secret, access_token, access_token_secret)
        api_v1 = API(auth_v1)
        
    except Exception as e:
        logging.error(f"Error setting up Twitter clients: {e}")
        return

    top_3 = get_top_tokens()
    if not top_3:
        logging.warning("No token data available. Skipping tweet.")
        return

    logging.info("=== GENERATING MONTY AI TWEET ===")
    tweet_text = generate_ai_tweet(top_3)
    
    # If AI fails, tweet_text will be None. Stop execution.
    if not tweet_text:
        logging.error("AI tweet generation failed or returned empty. Terminating process for this run.")
        logging.info("GitHub Action: Bot execution finished - AI Failure.")
        return
    
    if len(tweet_text) > 280:
        logging.error(f"MONTY tweet too long ({len(tweet_text)} characters), despite truncation logic. CANCELING.")
        return

    logging.info(f"📝 MONTY tweet prepared:")
    logging.info(f"   Tweet: {len(tweet_text)} chars")
    logging.info(f"   Content: {tweet_text.replace(chr(10), ' ')}") # Shows tweet in one line

    try:
        logging.info("=== SENDING MONTY TWEET ===")
        
        main_tweet_response = safe_tweet_with_retry(client, tweet_text)
        
        if not main_tweet_response:
            logging.error("❌ CRITICAL ERROR: Failed to send MONTY tweet!")
            return
            
        main_tweet_id = main_tweet_response.data['id']
        logging.info(f"✅ MONTY tweet sent successfully! ID: {main_tweet_id}")
        logging.info(f"🎉 SUCCESS: MONTY AI tweet posted!")
        logging.info(f"   🔗 Tweet: https://x.com/user/status/{main_tweet_id}")

    except Exception as e:
        logging.error(f"Unexpected error during MONTY tweet process: {e}")
        import traceback
        logging.error(f"Full traceback: {traceback.format_exc()}")

    logging.info("GitHub Action: Bot execution finished.")

if __name__ == "__main__":
    main()
