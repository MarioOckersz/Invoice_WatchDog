"""
invoice_parser.py

Reads a supplier invoice (image or PDF) using Gemini's vision model and returns
it as a typed Python object. This file ONLY extracts data. It does not decide
whether the invoice is correct or fraudulent; that happens in a separate
checks module, so we never trust the model's output blindly.
"""

import os
from typing import List, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# Keep the API key and model name in a config file, not hard-coded here.
# Model names get retired over time, so having it in one place means a
# one-line fix instead of hunting through the code.
from src.config import GEMINI_API_KEY, GEMINI_MODEL


# ---------------------------------------------------------------------------
# 1. DATA SHAPES (the "schema")
# ---------------------------------------------------------------------------
# Pydantic models describe the exact JSON structure we want back from the model.
# The Field(description=...) text is sent to Gemini as instructions, so the
# wording here directly influences extraction quality.
#
# Optional[...] with default None means "this value may be missing".
# Why this matters: if a field is REQUIRED and the invoice doesn't have it
# (e.g. no invoice number), the model is forced to make something up.
# A fabricated value is worse than an honest null, because our checks
# can't tell it's fake.

class LineItem(BaseModel):
    """One row of the invoice table (one product)."""

    name: str = Field(description="Product description exactly as printed")

    quantity: Optional[float] = Field(
        None, description="Quantity as printed; null if not shown"
    )
    unit_price: Optional[float] = Field(
        None, description="Unit price as printed; null if not shown"
    )

    # IMPORTANT: we tell the model to COPY the line total, not calculate it.
    # If the model calculated quantity * unit_price itself, a wrong or
    # fraudulent line total on the paper would be silently "fixed", and our
    # later arithmetic check would never catch the mismatch.
    total_price: Optional[float] = Field(
        None, description="Line total AS PRINTED. Do not calculate it."
    )


class InvoiceSchema(BaseModel):
    """The whole invoice: header info, line items, and totals."""

    supplier_name: Optional[str] = Field(None, description="Vendor name as printed")
    invoice_number: Optional[str] = Field(
        None, description="Invoice/bill number as printed; null if absent"
    )
    date: Optional[str] = Field(
        None, description="Invoice date in YYYY-MM-DD; null if unclear"
    )

    # An invoice with zero items is useless, so this one stays required
    # (an empty list is still allowed if nothing was found).
    line_items: List[LineItem]

    # Tax, discount and subtotal are separate fields on purpose.
    # Real, honest invoices often include tax. Without these fields, our
    # "do the items add up to the total?" check would wrongly flag every
    # invoice that has VAT (a false positive).
    subtotal: Optional[float] = Field(None, description="Subtotal as printed, if any")
    tax: Optional[float] = Field(None, description="Total tax/VAT as printed, if any")
    discount: Optional[float] = Field(
        None, description="Total discount as printed, if any"
    )

    # Same rule as line totals: copy it, never calculate it.
    total_amount: Optional[float] = Field(
        None, description="Grand total AS PRINTED. Do not calculate it."
    )


# ---------------------------------------------------------------------------
# 2. THE INSTRUCTION SENT TO THE MODEL
# ---------------------------------------------------------------------------
# The prompt reinforces the schema descriptions. The key idea is
# "transcribe, don't think": we want the model to behave like a scanner,
# not like an accountant who corrects mistakes.

PROMPT = (
    "Extract this supplier invoice. Copy every number exactly as printed, even if the "
    "arithmetic looks wrong. Never calculate, correct or guess values. "
    "If a field is missing or unreadable, return null."
)


# ---------------------------------------------------------------------------
# 3. THE MAIN FUNCTION
# ---------------------------------------------------------------------------

def parse_invoice(file_path: str) -> InvoiceSchema:
    """
    Upload an invoice file to Gemini, extract structured data, return it.

    Args:
        file_path: path to a PNG/JPG image or a PDF invoice.

    Returns:
        An InvoiceSchema object with the extracted fields.

    Raises:
        FileNotFoundError: if the path doesn't exist.
        ValueError: if the model returns nothing usable.
    """

    # Fail early with a clear message instead of a confusing API error later.
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    # Create the API client using our key.
    client = genai.Client(api_key=GEMINI_API_KEY)

    # Upload the file to Google's Files API. It accepts images and PDFs
    # natively, so we don't need our own OCR step.
    # The returned object is a reference to the uploaded file, not the file itself.
    uploaded = client.files.upload(file=file_path)

    # try/finally guarantees the cleanup at the bottom runs even if something
    # in between crashes. These are customer invoices, so we don't want
    # copies lingering on someone else's server.
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            # We send the file reference and the text instruction together.
            contents=[uploaded, PROMPT],
            config=types.GenerateContentConfig(
                # Ask for JSON output only (no chatty text around it).
                response_mime_type="application/json",
                # Give it our Pydantic class so output must match the schema.
                # This guarantees the FORMAT is valid. It does NOT guarantee
                # the numbers are read correctly. The model can still misread
                # a digit, which is why separate checks exist.
                response_schema=InvoiceSchema,
                # Temperature 0 = least random. For extraction we want the
                # same answer every run, not creativity.
                temperature=0.0,
            ),
        )

        # response.parsed is the SDK's already-validated InvoiceSchema object.
        # It can be None if the response was blocked or empty, so we check
        # explicitly instead of crashing later with a confusing error.
        if response.parsed is None:
            raise ValueError(
                "Model returned no parseable invoice (blocked or empty response)"
            )

        return response.parsed

    finally:
        # Always delete the uploaded copy, whether parsing succeeded or failed.
        client.files.delete(name=uploaded.name)