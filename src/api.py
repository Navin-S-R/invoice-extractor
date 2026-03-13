"""FastAPI service for invoice extraction."""

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .benchmark import BenchmarkLogger, ExtractionMetrics, estimate_cost
from .config import AI_PROVIDER, get_api_key, get_model
from .extractor import extract_invoice
from .helpers import (
    SUPPORTED_EXTENSIONS,
    avg_confidence,
    count_populated_fields,
    merge_with_confidence,
)
from .validation import validate_invoice

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent
_UPLOAD_DIR = _BASE_DIR / "uploads"
_LOG_PATH = _BASE_DIR / "logs" / "benchmark.csv"


# ── Transaction state ────────────────────────────────────────────────


class TransactionStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Transaction:
    txn_id: str
    status: TransactionStatus
    file_path: Path
    file_name: str
    document_type: str
    created_at: str
    callback_url: str | None = None
    completed_at: str | None = None
    # Populated after processing
    invoice_data: dict | None = None
    invoice_raw: dict | None = None
    validation: dict | None = None
    metrics: dict | None = None
    error: str | None = None


_transactions: dict[str, Transaction] = {}
_lock = threading.Lock()


# ── Response models ──────────────────────────────────────────────────


class ExtractResponse(BaseModel):
    txn_id: str
    status: TransactionStatus
    message: str


class StatusResponse(BaseModel):
    txn_id: str
    status: TransactionStatus
    file_name: str
    document_type: str
    created_at: str
    completed_at: str | None = None
    error: str | None = None


class ValidationSummary(BaseModel):
    score_pct: int
    checks_passed: int
    checks_total: int
    warnings: list[str]
    errors: list[str]


class MetricsSummary(BaseModel):
    provider: str
    model: str
    latency_seconds: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    avg_confidence: int | None = None


class ResultResponse(BaseModel):
    txn_id: str
    status: TransactionStatus
    file_name: str
    document_type: str
    invoice: dict
    invoice_raw: dict
    validation: ValidationSummary
    metrics: MetricsSummary
    created_at: str
    completed_at: str | None = None


class TransactionListItem(BaseModel):
    txn_id: str
    status: TransactionStatus
    file_name: str
    document_type: str
    created_at: str
    completed_at: str | None = None
    error: str | None = None


class TransactionListResponse(BaseModel):
    total: int
    transactions: list[TransactionListItem]


# ── Background processing ───────────────────────────────────────────


def _process_extraction(txn_id: str) -> None:
    """Synchronous extraction pipeline — runs in a thread pool."""
    txn = _transactions[txn_id]

    with _lock:
        txn.status = TransactionStatus.PROCESSING

    provider = AI_PROVIDER
    model = get_model()
    api_key = get_api_key()

    bench_logger = BenchmarkLogger(_LOG_PATH)
    metrics = ExtractionMetrics(
        file_name=txn.file_name,
        provider=provider,
        model=model,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    try:
        invoice, result = extract_invoice(txn.file_path, provider, model, api_key)

        invoice_data = invoice.model_dump(exclude_none=True)
        merged = merge_with_confidence(invoice_data, result.confidence_scores)

        # Fill metrics (same pipeline as main.py)
        metrics.status = "success"
        metrics.latency_seconds = round(result.latency_seconds, 2)
        metrics.input_tokens = result.input_tokens
        metrics.output_tokens = result.output_tokens
        metrics.total_tokens = result.input_tokens + result.output_tokens
        metrics.stop_reason = result.stop_reason
        metrics.estimated_cost_usd = round(
            estimate_cost(model, result.input_tokens, result.output_tokens), 6
        )

        metrics.items_count = len(invoice.items)
        metrics.taxes_count = len(invoice.taxes) if invoice.taxes else 0
        metrics.has_grand_total = invoice.grand_total is not None
        metrics.has_supplier = bool(invoice.supplier)
        metrics.fields_populated, metrics.fields_total = count_populated_fields(invoice)

        vr = validate_invoice(invoice)
        metrics.validation_score = vr.score_pct
        metrics.validation_passed = vr.checks_passed
        metrics.validation_total = vr.checks_total
        metrics.validation_warnings = len(vr.warnings)
        metrics.validation_errors = (
            "; ".join(vr.errors + vr.warnings) if (vr.errors or vr.warnings) else ""
        )

        avg_conf = avg_confidence(result.confidence_scores) if result.confidence_scores else None
        if avg_conf is not None:
            metrics.avg_confidence = avg_conf

        validation_summary = {
            "score_pct": vr.score_pct,
            "checks_passed": vr.checks_passed,
            "checks_total": vr.checks_total,
            "warnings": vr.warnings,
            "errors": vr.errors,
        }
        metrics_summary = {
            "provider": provider,
            "model": model,
            "latency_seconds": metrics.latency_seconds,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "total_tokens": metrics.total_tokens,
            "estimated_cost_usd": metrics.estimated_cost_usd,
            "avg_confidence": avg_conf,
        }

        with _lock:
            txn.status = TransactionStatus.COMPLETED
            txn.completed_at = datetime.now(timezone.utc).isoformat()
            txn.invoice_data = merged
            txn.invoice_raw = invoice_data
            txn.validation = validation_summary
            txn.metrics = metrics_summary

    except Exception as e:
        metrics.status = "error"
        metrics.error_message = str(e)
        with _lock:
            txn.status = TransactionStatus.FAILED
            txn.completed_at = datetime.now(timezone.utc).isoformat()
            txn.error = str(e)

    # Always log to benchmark CSV
    bench_logger.log(metrics)

    # Fire webhook callback if configured
    if txn.callback_url and txn.status == TransactionStatus.COMPLETED:
        _send_webhook(txn)


def _send_webhook(txn: Transaction) -> None:
    """POST the result to the callback URL. Fire-and-forget."""
    try:
        payload = {
            "txn_id": txn.txn_id,
            "status": txn.status.value,
            "file_name": txn.file_name,
            "document_type": txn.document_type,
            "invoice": txn.invoice_data,
            "invoice_raw": txn.invoice_raw,
            "validation": txn.validation,
            "metrics": txn.metrics,
            "created_at": txn.created_at,
            "completed_at": txn.completed_at,
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(txn.callback_url, json=payload)
            logger.info(
                "Webhook sent to %s — status %d", txn.callback_url, resp.status_code
            )
    except Exception as e:
        logger.warning("Webhook to %s failed: %s", txn.callback_url, e)


async def _run_extraction(txn_id: str) -> None:
    """Kick off extraction in a background thread."""
    await asyncio.to_thread(_process_extraction, txn_id)


# ── FastAPI app ──────────────────────────────────────────────────────


app = FastAPI(
    title="Invoice Extractor API",
    description="Extract structured invoice data from PDFs and images using AI Vision.",
    version="0.1.0",
)


@app.on_event("startup")
async def _startup():
    _UPLOAD_DIR.mkdir(exist_ok=True)
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


@app.post("/extract", response_model=ExtractResponse)
async def extract(
    file: UploadFile = File(...),
    document_type: str = Form(default="Purchase Invoice"),
    callback_url: str | None = Form(default=None),
):
    """Upload an invoice file and start extraction. Returns a transaction ID immediately."""
    suffix = Path(file.filename or "unknown").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: {', '.join(SUPPORTED_EXTENSIONS)}",
        )

    txn_id = uuid.uuid4().hex
    upload_path = _UPLOAD_DIR / f"{txn_id}{suffix}"
    content = await file.read()
    upload_path.write_bytes(content)

    now = datetime.now(timezone.utc).isoformat()
    txn = Transaction(
        txn_id=txn_id,
        status=TransactionStatus.QUEUED,
        file_path=upload_path,
        file_name=file.filename or "unknown",
        document_type=document_type,
        callback_url=callback_url,
        created_at=now,
    )

    with _lock:
        _transactions[txn_id] = txn

    asyncio.create_task(_run_extraction(txn_id))

    return ExtractResponse(
        txn_id=txn_id,
        status=TransactionStatus.QUEUED,
        message="Extraction queued. Poll GET /status/{txn_id} for progress.",
    )


@app.get("/status/{txn_id}", response_model=StatusResponse)
async def get_status(txn_id: str):
    """Check the status of an extraction job."""
    txn = _transactions.get(txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return StatusResponse(
        txn_id=txn.txn_id,
        status=txn.status,
        file_name=txn.file_name,
        document_type=txn.document_type,
        created_at=txn.created_at,
        completed_at=txn.completed_at,
        error=txn.error,
    )


@app.get("/result/{txn_id}", response_model=ResultResponse)
async def get_result(txn_id: str):
    """Get the full extraction result. Only available when status is 'completed'."""
    txn = _transactions.get(txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if txn.status == TransactionStatus.FAILED:
        raise HTTPException(status_code=422, detail=f"Extraction failed: {txn.error}")

    if txn.status != TransactionStatus.COMPLETED:
        raise HTTPException(
            status_code=202,
            detail=f"Extraction still in progress (status: {txn.status.value})",
        )

    return ResultResponse(
        txn_id=txn.txn_id,
        status=txn.status,
        file_name=txn.file_name,
        document_type=txn.document_type,
        invoice=txn.invoice_data,
        invoice_raw=txn.invoice_raw,
        validation=ValidationSummary(**txn.validation),
        metrics=MetricsSummary(**txn.metrics),
        created_at=txn.created_at,
        completed_at=txn.completed_at,
    )


@app.get("/transactions", response_model=TransactionListResponse)
async def list_transactions():
    """List all transactions with their current status."""
    with _lock:
        items = [
            TransactionListItem(
                txn_id=txn.txn_id,
                status=txn.status,
                file_name=txn.file_name,
                document_type=txn.document_type,
                created_at=txn.created_at,
                completed_at=txn.completed_at,
                error=txn.error,
            )
            for txn in _transactions.values()
        ]
    return TransactionListResponse(total=len(items), transactions=items)


# ── Entry point ──────────────────────────────────────────────────────


def main():
    """Run the API server via console script."""
    import uvicorn

    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
