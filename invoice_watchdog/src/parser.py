"""
src/parser.py
=============
Purpose:
    Robust, fault-tolerant multimodal invoice extractor for Invoice_WatchDog.
    Converts unstructured supplier documents (images or PDFs) into strictly 
    typed Pydantic Python structures using Google's Gemini models.

Key Architectural Decisions:
    1. Separation of Concerns (Extraction vs. Auditing):
       This file is strictly an extraction interface. It does NOT validate 
       arithmetic, calculate discounts, or determine fraud. Offloading math 
       to an LLM introduces non-deterministic hallucination risks.

    2. Transcribe, Never Compute ("Scan, Don't Think"):
       Prompts and Field descriptions explicitly forbid the model from computing
       totals (e.g. calculating qty * unit_price). If the original paper has an 
       intentional or erroneous math defect, we need the raw error preserved 
       so our downstream Python validator can flag it.

    3. Multi-Engine Cascade (503 & 429 Resilience):
       Free-tier endpoints and cutting-edge preview models regularly throw 
       transient errors (HTTP 503 Service Unavailable / HTTP 429 Rate Limits).
       To prevent service downtime, the extractor iterates through a priority list 
       of candidate models (e.g., gemini-3.8-flash -> gemini-2.0-flash -> gemini-1.5-flash).
       If an endpoint is throttled or saturated, execution automatically cascades 
       to the next available model.

    4. Transient Artifact Lifecycle (Privacy & Hygiene):
       Files sent to Google's Files API are tracked and guaranteed to be deleted 
       via a try/finally block, ensuring zero persistent customer financial 
       data lingers on remote storage.
"""

import os
import time
from typing import List, Optional

# Google GenAI modern SDK imports
from google import genai
from google.genai import types
from google.genai.errors import APIError

# Pydantic is utilized to enforce strict typing and build the JSON response schema
from pydantic import BaseModel, Field

# Centralized configuration containing API keys and candidate fallback models
from src.config import GEMINI_API_KEY, MODEL_CANDIDATES


# ===========================================================================
# 1. DATA CONTRACTS & JSON SCHEMAS
# ===========================================================================
# Pydantic classes passed to `response_schema` are transformed by the SDK 
# into OpenAPI-compatible JSON schemas sent directly to Gemini.
# The Field(description=...) strings act as granular prompt instructions.

class LineItem(BaseModel):
    """
    Represents an individual billed row item from the document.
    All numeric fields default to None to prevent synthetic hallucination.
    """
    name: str = Field(
        description="The full product description or service name exactly as printed."
    )
    quantity: Optional[float] = Field(
        default=None, 
        description="The number of units billed. Null if not explicitly printed."
    )
    unit_price: Optional[float] = Field(
        default=None, 
        description="The price per single unit before taxes. Null if not explicitly printed."
    )
    # CRITICAL: We tell the model to copy what it sees, not calculate it.
    # If the vendor printed 5 units @ $10.00 = $70.00 (a $20 error),
    # the model MUST record total_price as 70.0, allowing our Python validator
    # to catch the discrepancy.
    total_price: Optional[float] = Field(
        default=None, 
        description="Total billed amount for this specific line item AS PRINTED. Do not calculate."
    )


class InvoiceSchema(BaseModel):
    """
    Root document schema representing the complete parsed invoice.
    Accommodates variations across supplier formats (tax, discounts, subtotal).
    """
    supplier_name: Optional[str] = Field(
        default=None, 
        description="Legal business name of the vendor or supplier as printed."
    )
    invoice_number: Optional[str] = Field(
        default=None, 
        description="The primary invoice, reference, or bill identifier string."
    )
    date: Optional[str] = Field(
        default=None, 
        description="Invoice issuance date formatted strictly as YYYY-MM-DD. Null if illegible."
    )
    # Required collection of items; defaults to an empty list if none parsed
    line_items: List[LineItem] = Field(
        default_factory=list,
        description="List containing every product or service billed on the invoice."
    )
    # Intermediate financial fields prevent false-positive validation flags on invoices with taxes
    subtotal: Optional[float] = Field(
        default=None, 
        description="Calculated sum of all line items before tax or deductions, if explicitly printed."
    )
    tax: Optional[float] = Field(
        default=None, 
        description="Total sales tax, VAT, GST, or excise amount explicitly printed."
    )
    discount: Optional[float] = Field(
        default=None, 
        description="Total promotional discount or rebate deducted from total, if explicitly printed."
    )
    total_amount: Optional[float] = Field(
        default=None, 
        description="The final stated balance due or grand total AS PRINTED. Do not recalculate."
    )


# ===========================================================================
# 2. SYSTEM INSTRUCTIONS
# ===========================================================================
# Reinforces the schema boundaries: treat the model as a dumb OCR scanner.
EXTRACTION_INSTRUCTIONS = (
    "You are a strict data transcription engine. Extract all relevant details from this invoice. "
    "Do not compute, adjust, balance, or guess numerical values. "
    "Copy every single number and string exactly as printed on the document, even if the math is wrong. "
    "If a value is not printed or cannot be determined with complete confidence, return null."
)


# ===========================================================================
# 3. EXTRACTION ENGINE WITH AUTOMATED CASCADE
# ===========================================================================

def parse_invoice(file_path: str, retries_per_model: int = 2) -> InvoiceSchema:
    """
    Uploads a document to Gemini, runs extraction across a cascade of models 
    to mitigate 503/429 outages, cleans up remote artifacts, and returns 
    a strongly typed InvoiceSchema instance.

    Args:
        file_path (str): Path to local PNG, JPG, or PDF file.
        retries_per_model (int): Retries per candidate before cascading (default: 2).

    Returns:
        InvoiceSchema: Validated Pydantic model populated with invoice data.

    Raises:
        FileNotFoundError: If the source invoice file cannot be resolved.
        RuntimeError: If all candidate models in the cascade fail.
    """
    # 1. Guard check: verify file existence locally before making remote network calls
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Source invoice document does not exist: {file_path}")

    # 2. Initialize the Google GenAI SDK client with validated environment key
    client = genai.Client(api_key=GEMINI_API_KEY)

    print(f"[*] Uploading '{file_path}' to Google Files API...")
    # The Files API handles both raster images and multi-page PDFs natively
    uploaded_artifact = client.files.upload(file=file_path)

    # 3. Wrapping the processing in try/finally ensures that no matter what fails,
    # uploaded customer data is wiped from Google's temporary file storage.
    try:
        last_encountered_error = None

        # --- CASCADE LOOP: Iterate through fallback models ---
        for model_identifier in MODEL_CANDIDATES:
            print(f"[*] Dispatching extraction job to engine: '{model_identifier}'...")
            
            backoff_delay = 2.0  # Initial sleep time in seconds for exponential backoff

            for attempt in range(1, retries_per_model + 1):
                try:
                    # Invoke multimodal model with strict schema enforcement
                    response = client.models.generate_content(
                        model=model_identifier,
                        contents=[uploaded_artifact, EXTRACTION_INSTRUCTIONS],
                        config=types.GenerateContentConfig(
                            # Force the model to output valid JSON matching our Pydantic structure
                            response_mime_type="application/json",
                            response_schema=InvoiceSchema,
                            # Temperature 0.0 guarantees deterministic extraction (no creative variation)
                            temperature=0.0,
                        ),
                    )

                    # Ensure the SDK successfully parsed the payload into an InvoiceSchema instance
                    if response.parsed is not None:
                        print(f"✅ Extraction completed successfully using '{model_identifier}'.")
                        return response.parsed
                    
                    # If response.parsed is None, the output may have been blocked or truncated
                    print(f"⚠ Engine '{model_identifier}' returned an empty or unparseable payload.")
                    break

                except APIError as api_err:
                    last_encountered_error = api_err
                    
                    # Check for transient server saturation (503) or rate-limiting (429)
                    if api_err.code in (503, 429):
                        print(f"⚠ Engine '{model_identifier}' capacity error {api_err.code}: {api_err.message}")
                        if attempt < retries_per_model:
                            print(f"  Attempt {attempt}/{retries_per_model} failed. Waiting {backoff_delay:.1f}s before retry...")
                            time.sleep(backoff_delay)
                            backoff_delay *= 2.0  # Double delay for subsequent retry
                        else:
                            print(f"  Max attempts reached for '{model_identifier}'.")
                    else:
                        # Non-transient error (e.g. 404 Model Not Found, 400 Bad Request)
                        print(f"⚠ Engine '{model_identifier}' cannot be used: {api_err.message}")
                        break  # Immediately stop retrying this model and advance to next candidate

            print(f"🔄 Cascading to next available backup model in configuration...")

        # If the loop exhausts all models in MODEL_CANDIDATES without returning:
        raise RuntimeError(
            f"All available engine candidates failed to extract data. Last error encountered: {last_encountered_error}"
        )

    finally:
        # --- CLEANUP GUARANTEE ---
        # Irrespective of success or raised exceptions, purge the uploaded document from Google servers
        print(f"[*] Purging transient artifact '{uploaded_artifact.name}' from Google storage...")
        try:
            client.files.delete(name=uploaded_artifact.name)
        except Exception as cleanup_err:
            # File deletion failure should notify but not override primary pipeline exceptions
            print(f"⚠ Warning: Failed to purge remote file '{uploaded_artifact.name}': {cleanup_err}")