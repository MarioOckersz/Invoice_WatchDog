# 🛡️ Invoice_WatchDog

An intelligent, lightweight pipeline that converts messy supplier documents into structured data, flags financial anomalies using deterministic code, and locks audit trails into a cryptographic hash-chain.

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Gemini API](https://img.shields.io/badge/Powered%20by-Google%20Gemini-orange.svg)](https://ai.google.dev/)

---

## 🎯 Purpose of the Tool

Small-scale retail shops and grocery markets face a persistent inventory vulnerability: supplier invoice discrepancies. Distributors frequently drop off goods with physical paper or PDF invoices containing manual arithmetic errors, sneaky duplicate billings, or unexpected price hikes on core stock (like milk, rice, or sugar) compared to previous deliveries. 

Checking these lines by hand is tedious and error-prone. Invoice_WatchDog solves this by:
1. Automating Data Intake: Instantly ingesting unstructured images or PDFs of supplier receipts.
2. Applying Deterministic Rules: Verifying invoice line math, cross-checking past item costs to catch price hikes (over 15%), and checking for duplicate bill numbers.
3. Ensuring Accountability: Storing every processed invoice in a lightweight, tamper-evident cryptographic hash-chain inside SQLite so audit logs cannot be covertly altered.

---

## 🏗️ System Architecture & Workflow

Invoice_WatchDog cleanly separates fuzzy AI interpretation from strict, deterministic financial logic:
```
 📄 Input Invoice (PNG/JPG/PDF)
         │
         ▼
 🤖 parser.py ──> Gemini Vision API (Forces strict JSON Schema)
         │
         ▼
 ⚖ validator.py ──> Plain Python Business Checks:
         │              • Math validation (Σ line items = total)
         │              • Duplicate invoice detection
         │              • Price jump alerts (>15% inflation check)
         │
         ▼
 ⛓️ ledger.py ───> Tamper-Evident SQLite Ledger (SHA-256 Hash-Chain)
         │
         ▼
 📊 Terminal Output / Anomaly Report
```
---

## 🚀 Key Features

* **Multimodal Document Extraction:** Native handling of image files (.png, .jpg) and digital documents (.pdf) using Gemini's vision pipeline to convert messy handwriting or prints into clean formats.
* **Forced JSON Schema Output:** Utilizes strict schema validation to guarantee that the LLM response always maps predictably to your application code.
* **Deterministic Math & Logic Engine:** Implements pure Python checks for arithmetic validation (sum of line items vs. stated total) and inflation thresholds (over 15% price jumps) to eliminate AI hallucination risks on sensitive data.
* **Tamper-Evident SQLite Ledger:** Secures audit histories using a lightweight cryptographic hash-chain (SHA-256) where each record binds its checksum to the previous row. Any manual database alteration breaks chain verification instantly.
* **Zero-Cost Local Setup:** Runs entirely on free-tier API parameters, making it practical for local testing, portfolio demonstrations, or small retail pilots.

---

## 📂 Project Repository Structure
```
invoice_watchdog/
│
├── .env.example            # Template for your Gemini API key
├── .gitignore              # Ignores __pycache__, .env, and local sqlite dbs
├── LICENSE                 # MIT License
├── README.md               # Project Documentation
├── requirements.txt        # Python package dependencies
│
├── data/                   # Directory for sample or live invoices
│   ├── sample_invoice_1.png
│   └── sample_invoice_2.pdf
│
├── src/                    # Core application source code
│   ├── __init__.py
│   ├── config.py           # Configuration and environment loaders
│   ├── parser.py           # Handles Gemini Vision API and strict JSON parsing
│   ├── validator.py        # Plain Python math and business logic checks
│   ├── ledger.py           # SQLite storage + cryptographic hash-chaining
│   └── cli.py              # Command Line Interface runner
│
└── tests/                  # Unit and integration tests
    ├── __init__.py
    ├── test_validator.py
    └── test_ledger.py
```
---

## 🛠️ Quick Start Guide

### 1. Clone the Repository
git clone https://github.com/yourusername/invoice_watchdog.git
cd invoice_watchdog

### 2. Install Dependencies
pip install -r requirements.txt

### 3. Configure Your Environment
Create a .env file in the root directory and add your free Google AI Studio API key:
GEMINI_API_KEY=your_actual_api_key_here

### 4. Run an Invoice Check
python -m src.cli --file data/sample_invoice_1.png

---

## 📊 Sample Output Report

==================================================
🛡️ INVOICE_WATCHDOG ANALYSIS REPORT
==================================================
Supplier      : FreshFoods Distrib.
Invoice No    : INV-99201
Date          : 2026-06-05
Total Stated  : Rs. 14,500.00

--- LINE ITEMS ---
1. Organic Rice 5kg  | Qty: 10 | Unit: Rs. 1,100.00 | Total: Rs. 11,000.00
2. Coconut Oil 1L    | Qty: 10 | Unit: Rs.   350.00 | Total: Rs.  3,500.00

--- ANOMALIES & FLAGS ---
⚠ [PRICE SPIKE]: 'Organic Rice 5kg' unit price jumped 22.2% since last invoice (Previous: Rs. 900.00)
✅ [MATH CHECK]: Line items sum matches stated total perfectly.
✅ [DUPLICATE CHECK]: Invoice number is unique for this supplier.

--- LEDGER STATUS ---
⛓️ Secure Hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
🔒 Chain Integrity: VERIFIED (No tampering detected)
==================================================

---

## 💡 Tech Stack Overview

| Component | Technology | Purpose |
| :--- | :--- | :--- |
| **Language** | Python 3.10+ | Core application logic and type safety |
| **AI Vision Engine** | Google GenAI (gemini-2.5-flash) | Multimodal extraction of unstructured receipts |
| **Data Validation** | Pydantic | Structured schema validation for LLM outputs |
| **Storage & Security** | SQLite3 + SHA-256 | Local persistence and cryptographic hash-chaining |

---

## 📄 License
Distributed under the MIT License. See LICENSE for more information.
