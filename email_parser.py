"""
Email parser module for Expense Manager.
Strips HTML from bank transaction emails and parses them via a local LLM.
No Flask dependencies — can be tested standalone.
"""

import re
import json
import math
import html as html_module
import urllib.request
import urllib.error
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def strip_email_html(html: str) -> str | None:
    """
    Strip HTML from a bank transaction email and extract the transaction text.
    Returns the extracted text, or None if this is a promotional/non-transaction email.
    """
    if not html or not isinstance(html, str):
        return None

    # Remove style and script blocks
    text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Replace <br> tags with newlines before stripping
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)

    # Strip all remaining HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)

    # Decode all HTML entities (numeric, named, etc.)
    text = html_module.unescape(text)

    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    # Extract transaction text between "Dear Customer" and sign-off
    match = re.search(
        r'Dear Customer[,.]?\s*(.+?)(?:Warm [Rr]egards|Assuring you|This is a system)',
        text,
        re.DOTALL
    )

    if match:
        return 'Dear Customer, ' + match.group(1).strip()

    return None


def parse_with_llm(email_text: str, llm_url: str, system_prompt: str, timeout: int = 90) -> dict | None:
    """
    Send extracted email text to a local LLM for parsing.
    Returns a dict with transaction fields, or None on failure.

    The LLM endpoint must be OpenAI-compatible (/v1/chat/completions).
    """
    if not email_text or not llm_url or not system_prompt:
        return None

    url = llm_url.rstrip('/') + '/v1/chat/completions'

    payload = {
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': email_text}
        ],
        'temperature': 0
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode('utf-8'))

        content = result['choices'][0]['message']['content'].strip()

        # Try direct JSON parse
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # Try extracting JSON from markdown code blocks
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(1))
            else:
                # Try finding a JSON object anywhere in the response (supports nested braces)
                obj_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
                if obj_match:
                    parsed = json.loads(obj_match.group())
                else:
                    logger.warning("LLM response is not valid JSON: %s", content[:200])
                    return None

        # Validate required fields
        if not _validate_parsed(parsed):
            return None

        return parsed

    except urllib.error.URLError as e:
        logger.error("LLM request failed: %s", e)
        return None
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error("Failed to parse LLM response: %s", e)
        return None
    except Exception as e:
        logger.error("Unexpected error in LLM parsing: %s", e)
        return None


def _validate_parsed(parsed: dict) -> bool:
    """Validate that the parsed transaction has all required fields with correct types."""
    if not isinstance(parsed, dict):
        return False

    # Amount must be a positive finite number
    amount = parsed.get('amount')
    if not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
        logger.warning("Invalid amount: %s", amount)
        return False

    # Date must be valid YYYY-MM-DD
    date_str = parsed.get('date')
    if not isinstance(date_str, str):
        logger.warning("Missing date")
        return False
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        logger.warning("Invalid date format: %s", date_str)
        return False

    # Account must be a non-empty string
    if not isinstance(parsed.get('account'), str) or not parsed['account'].strip():
        logger.warning("Missing or empty account")
        return False

    # Merchant must be a non-empty string
    if not isinstance(parsed.get('merchant'), str) or not parsed['merchant'].strip():
        logger.warning("Missing or empty merchant")
        return False

    # Type must be Expense or Income (default to Expense if missing/invalid)
    valid_types = ('Expense', 'Income')
    if parsed.get('type') not in valid_types:
        parsed['type'] = 'Expense'

    return True


def build_default_prompt(account_mapping: dict = None) -> str:
    """
    Build the default system prompt for HDFC Bank email parsing.
    Account mapping is injected dynamically.
    """
    current_year = datetime.now().year

    mapping_lines = ""
    if account_mapping:
        mapping_lines = "\n".join(
            f'- "{key}" = "{value}"'
            for key, value in account_mapping.items()
        )
    else:
        mapping_lines = '- Map account numbers and card endings to your configured account names'

    categories = "Groceries, Dining, Transport, Utilities, Shopping, Health, Entertainment, Education, Rent & Housing, Savings & Investment, Subscriptions, Miscellaneous"

    return f"""You are a bank transaction parser for HDFC Bank email alerts. The current year is {current_year}.

CRITICAL RULES — follow these exactly:

DATE PARSING:
- DD-MM-YY format: the YY is the last two digits of {current_year}. So 24-03-{str(current_year)[-2:]} means {current_year}-03-24
- "DD Mon, YYYY" format: use as-is. So "24 Mar, {current_year}" means {current_year}-03-24
- Always output dates as YYYY-MM-DD

ACCOUNT IDENTIFICATION — this is the most important rule:
{mapping_lines}
- If the email says "debited from account XXXX", match XXXX against the account mapping above
- If the email says "Credit Card ending XXXX", match that against the account mapping above
- The "account" field in your output MUST be one of the exact account names from the mapping above
- NEVER use "VPA", "UPI", "IMAP", or any other value — only the mapped account names

MERCHANT NAME:
- For UPI transactions: the email says "to VPA someaddress@bank MERCHANT NAME on DD-MM-YY" — extract ONLY the merchant name AFTER the VPA address, not the VPA address itself
- For Credit Card transactions: the email says "towards MERCHANT on DD Mon, YYYY" — extract the merchant name after "towards"
- Strip prefixes: PYU*, MAB.*, or any VPA/bank identifier (e.g., "PYU*Swiggy Food" → "Swiggy Food")

CATEGORY — must be one of these exact values, NEVER use "Expense" or "Income" as category:
{categories}
- Pick based on merchant: Swiggy/Zomato/restaurant → Dining, Amazon/Flipkart → Shopping, Uber/Ola/IRCTC → Transport, Blinkit/DMart/grocery → Groceries, Netflix/Spotify → Subscriptions, gym/pharmacy → Health
- If unsure, use "Miscellaneous"

TYPE:
- All debits are "Expense"
- All credits are "Income"

Return ONLY a valid JSON object with these exact fields — no explanation, no markdown, no extra text:
{{"amount": number, "merchant": "string", "date": "YYYY-MM-DD", "account": "string", "category": "string", "type": "Expense"}}"""


# ── Meta-prompt for users setting up custom bank parsing ─────────────────────

PROMPT_SETUP_GUIDE = """How to create a parsing prompt for your bank:

1. Copy 3-4 different transaction alert emails from your bank
   (include: debit, credit, UPI, card transactions)

2. Open any capable LLM (ChatGPT, Claude, Gemini, etc.)

3. Paste this prompt along with your sample emails:

   "I have a self-hosted expense tracker that parses bank transaction emails
   using an LLM. I need you to create a system prompt that extracts
   transaction details from my bank's email alerts.

   Here are sample emails from my bank:
   [paste your emails here]

   The output must be a JSON object with exactly these fields:
   - amount (number, always positive)
   - merchant (string, clean merchant name)
   - date (string in YYYY-MM-DD format)
   - account (string, must match one of my account names listed below)
   - category (string, best guess from: Groceries, Dining, Transport,
     Utilities, Shopping, Health, Entertainment, Education, Miscellaneous)
   - type (string, either 'Expense' or 'Income')

   My accounts are:
   [list your account names here, e.g., 'Chase Checking', 'Amex Platinum']

   Create a system prompt with explicit rules for:
   - Parsing my bank's specific date formats
   - Extracting merchant names (removing bank-specific prefixes)
   - Mapping account identifiers to my account names
   - Handling the current year correctly

   The prompt should instruct the LLM to return ONLY a JSON object,
   no explanation or markdown."

4. Copy the generated system prompt into the Custom Prompt field

5. Click "Test Parse" with a sample email to verify it works"""
