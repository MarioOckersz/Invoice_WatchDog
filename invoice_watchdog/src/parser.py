"""
parser.py - Multimodal Invoice Extractor with Exponential Backoff
================================================================

PURPOSE:
--------
Extract structured supplier data from unstructured receipts (images/PDFs)
using Google's multimodal Gemini model.

ENGINEERING PRINCIPLES APPLIED:
--------------------------------
1. Separation of Concerns:
   This module handles EXTRACTION ONLY. It never performs business math,
   auditing, or fraud detection. AI is treated as a probabilistic parser;
   deterministic Python code in downstream modules handles validation.

2. Transcribe, Never Compute:
   Prompts and field descriptions strictly instruct the model to copy 
   printed numbers as-is. If the LLM "corrects" a line item calculation,
   fraudulent or erroneous invoices would bypass audit checks.

3. Transient File Lifecycle:
   Customer financial documents uploaded via Google's Files API are
   explicitly deleted in a `finally` block, ensuring no persistent copies
   remain on external infrastructure.

4. Fault Tolerance via Exponential Backoff:
   Network requests to LLM endpoints frequently hit transient 503 (server
   overloaded) and 429 (rate-limit) errors. A retry loop with backoff prevents
   intermittent service hiccups from crashing the pipeline.
"""

import os
import time
from typing import List, Optional

# Official Google GenAI SDK and internal error types
from google import genai
from google.genai import types
from google.genai.errors import APIError

# Pydantic handles runtime data parsing, validation, and schema generation
from pydantic import BaseModel, Field

# Centralized configuration keeps keys and model identifiers out of application logic
from src.config import GEMINI_API_KEY, GEMINI_MODEL


# ===========================================================================
# 1. DATA CONTRACTS (Pydantic Schemas)
# ===========================================================================
# These models define the exact JSON structure enforced during model generation.
# Field descriptions are passed directly to Gemini's schema parser, functioning
# as micro-prompts that guide field-level extraction behavior.

class LineItem(BaseModel):
    """
    Represents an individual line item on a supplier bill.
    """
    name: str = Field(
        description="Product or service name exactly as printed on the document."
    )
    quantity: Optional[float] = Field(
        default=None, 
        description="Quantity purchased. Set to null if omitted from the bill."
    )
    unit_price: Optional[float] = Field(
        default=None, 
        description="Price per single unit. Set to null if omitted from the bill."
    )
    # CRITICAL: We instruct the model to transcribe rather than recalculate.
    # If the supplier wrote 2 x $5 = $12 (a mistake), we want to capture $12
    # so that our validator catches the arithmetic error.
    total_price: Optional[float] = Field(
        default=None, 
        description="Line total AS PRINTED. Do not calculate (quantity * unit_price)."
    )


class InvoiceSchema(BaseModel):
    """
    Top-level invoice container. Captures metadata, line items, and stated totals.
    """
    supplier_name: Optional[str] = Field(
        default=None, 
        description="Name of the selling company or distributor. Null if unreadable."
    )
    invoice_number: Optional[str] = Field(
        default=None, 
        description="Unique invoice/bill identifier. Null if missing."
    )
    date: Optional[str] = Field(
        default=None, 
        description="Invoice date formatted as YYYY-MM-DD. Null if not specified."
    )
    
    # Required list: An invoice must contain items to be actionable.
    line_items: List[LineItem] = Field(
        default_factory=list,
        description="List of all purchased goods or services listed on the invoice."
    )
    
    # Financial fields are marked Optional to handle diverse billing formats:
    # Tax, discounts, and subtotals must be extracted separately so our validator
    # does not misidentify standard sales tax as an arithmetic mismatch.
    subtotal: Optional[float] = Field(
        default=None, 
        description="Subtotal before taxes or discounts, if printed."
    )
    tax: Optional[float] = Field(
        default=None, 
        description="Total tax, VAT, or GST amount, if printed."
    )
    discount: Optional[float] = Field(
        default=None, 
        description="Total discount or markdown amount, if printed."
    )
    total_amount: Optional[float] = Field(
        default=None, 
        description="Final grand total AS PRINTED. Do not recalculate."
    )


# ===========================================================================
# 2. SYSTEM EXTRACTION PROMPT
# ===========================================================================
# The prompt reinforces passive transcription. We treat the model like an OCR
# scanner rather than an intelligent accountant.

SYSTEM_PROMPT = (
    "Extract all information from this supplier invoice. "
    "Copy every numerical value and description exactly as printed, "
    "even if the arithmetic appears incorrect. "
    "Do not calculate, correct, or infer missing figures. "
    "If any field is absent or illegible, set its value to null."
)


# ===========================================================================
# 3. EXTRACTION PIPELINE WITH RETRY LOGIC
# ===========================================================================

def parse_invoice(file_path: str, max_retries: int = 4, base_delay: float = 2.0) -> InvoiceSchema:
    """
    Uploads an invoice to Google's Files API, extracts structured fields using Gemini,
    cleans up the remote file, and returns a validated InvoiceSchema object.

    Args:
        file_path (str): Local filesystem path to the target image (.png, .jpg) or PDF (.pdf).
        max_retries (int): Number of attempts to make against transient API errors (503/429).
        base_delay (float): Starting sleep duration in seconds for exponential backoff.

    Returns:
        InvoiceSchema: Pydantic instance populated with extracted invoice data.

    Raises:
        FileNotFoundError: If the invoice file does not exist locally.
        ValueError: If the model returns an empty or unparseable response.
        APIError: If external API calls fail after exhausting all retries.
    """
    # 1. Fail fast on local path issues before making external network calls
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Target document not found at: {file_path}")

    # 2. Instantiate the Google GenAI Client
    client = genai.Client(api_key=GEMINI_API_KEY)

    print(f"[*] Uploading '{file_path}' to Google Files API...")
    # The Files API handles documents and images natively without manual pre-processing
    uploaded_file = client.files.upload(file=file_path)

    # 3. try/finally block guarantees remote file deletion even if execution fails
    try:
        current_delay = base_delay

        for attempt in range(1, max_retries + 1):
            try:
                print(f"[*] Querying {GEMINI_MODEL} (Attempt {attempt}/{max_retries})...")

                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=[uploaded_file, SYSTEM_PROMPT],
                    config=types.GenerateContentConfig(
                        # Enforce pure JSON output format
                        response_mime_type="application/json",
                        # Bind the output directly to our Pydantic class
                        response_schema=InvoiceSchema,
                        # Temperature 0.0 maximizes determinism and minimizes hallucination
                        temperature=0.0,
                    ),
                )

                # Validate that the response contains structured output
                if response.parsed is None:
                    raise ValueError(
                        "Model returned an empty payload or failed to conform to schema."
                    )

                # Return the validated Pydantic model directly
                return response.parsed

            except APIError as err:
                # 503 = Service Unavailable / Transient High Demand
                # 429 = Rate Limit Exceeded
                is_transient = err.code in (503, 429)

                if is_transient and attempt < max_retries:
                    print(f"⚠ Server returned code {err.code} ({err.message}).")
                    print(f"  Backing off for {current_delay:.1f}s before retry...")
                    time.sleep(current_delay)
                    current_delay *= 2.0  # Exponential backoff progression: 2s, 4s, 8s...
                else:
                    # Non-recoverable error (e.g., 400 Bad Request, 401 Unauthorized) or out of retries
                    raise err

        raise RuntimeError(f"Failed to process invoice after {max_retries} attempts.")

    finally:
        # Secure audit hygiene: never leave customer financial files sitting on remote servers
        print(f"[*] Cleaning up remote artifact '{uploaded_file.name}' from Google storage...")
        try:
            client.files.delete(name=uploaded_file.name)
        except Exception as cleanup_err:
            # File cleanup failure should warn but not mask prior extraction errors
            print(f"⚠ Warning: Could not delete remote file '{uploaded_file.name}': {cleanup_err}")