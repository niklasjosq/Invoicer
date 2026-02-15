from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date
from .invoice_logic import generate_facturx_xml

app = FastAPI(title="Factur-X / ZUGFeRD API")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Override default 422 with 400 as requested.
    """
    return JSONResponse(
        status_code=400,
        content={"detail": exc.errors(), "body": exc.body},
    )

class Item(BaseModel):
    name: str
    qty: float
    price: float
    vat_percent: Optional[float] = 19.0

class Party(BaseModel):
    name: str
    address_lines: List[str]
    tax_id: Optional[str] = None
    customer_id: Optional[str] = None

class InvoiceRequest(BaseModel):
    id: str
    issue_date: date
    seller: Party
    buyer: Party
    items: List[Item]
    currency: str = "EUR"

@app.post("/generate-xml")
async def generate_xml(req: InvoiceRequest):
    """
    Endpoint to generate Factur-X XML from a JSON payload.
    """
    # 1. Validation for mandatory fields (already handled by Pydantic, but we can add custom checks if needed)
    if not req.items:
        raise HTTPException(status_code=400, detail="Invoice must contain at least one item.")
    
    # 2. Map Payload to internal data structure used by Logic
    internal_data = {
        "id": req.id,
        "date": req.issue_date,
        "sender": {
            "name": req.seller.name,
            "address_lines": req.seller.address_lines
        },
        "sender_tax_id": req.seller.tax_id,
        "recipient": {
            "name": req.buyer.name,
            "address_lines": req.buyer.address_lines
        },
        "customer_id": req.buyer.customer_id,
        "items": [
            {
                "name": item.name,
                "price": item.price,
                "qty": item.qty,
                "vat_percent": item.vat_percent
            } for item in req.items
        ],
        "footer": {}, # Optional or implicit in basic profile
        "unit_code": "C62" # Defaulting to unit for items
    }
    
    try:
        # 3. Generate XML
        xml_str = generate_facturx_xml(internal_data)
        
        # 4. Return XML with correct MIME Type and Headers
        return Response(
            content=xml_str,
            media_type="application/xml",
            headers={
                "Content-Disposition": "attachment; filename=factur-x.xml"
            }
        )
    except Exception as e:
        # Standard error handling
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
