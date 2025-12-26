# Proposal: Batch Print SF Waybills

## Change ID
`batch-print-sf-waybills`

## Overview
Add batch waybill printing capability to the batch shipping management page. This enables users to print SF Express shipping labels directly to cloud printers using the Kuaimai (快麦) cloud printing service.

## Problem Statement
Currently, the batch shipping workflow requires manual printing of SF Express waybills. Users need to:
1. Access SF Express platform separately to print labels
2. Manually match labels with orders
3. Print each label individually

This creates inefficiency and potential for errors when processing multiple shipments.

## Proposed Solution
Integrate SF Express waybill printing API with Kuaimai cloud printing service to enable one-click batch printing of shipping labels from the batch shipping management interface.

### Technical Approach
1. Call SF Express `COM_RECE_CLOUD_PRINT_WAYBILLS` API to generate waybill PDFs
2. Convert PDF to images using `pdf2image` library
3. Encode images as base64
4. Send to Kuaimai cloud printing service using `tsplXmlWrite` API
5. Track printing status and provide user feedback

## Scope

### In Scope
- Add "Batch Print Waybills" button to BatchShippingView
- Integrate SF Express cloud printing API (PDF format)
- Integrate Kuaimai cloud printing service
- PDF to image conversion service
- Printer selection and management
- Printing status tracking and error handling
- Filter: only print waybills for orders with tracking numbers

### Out of Scope
- Support for other express carriers
- Direct CPCL/ZPL format (will use PDF → Image path)
- Local printer support (cloud printing only)
- Custom waybill templates
- Waybill preview before printing

## Dependencies
- Existing SF Express service (`app/services/shipping/sf_express_service.py`)
- Existing batch shipping UI (`frontend/src/views/BatchShippingView.vue`)
- SF Express API credentials (already configured)
- Kuaimai cloud printing account (needs configuration)

## External Services Required
1. **SF Express Open Platform**
   - API: `COM_RECE_CLOUD_PRINT_WAYBILLS`
   - Authentication: existing msgDigest method
   - Response format: PDF

2. **Kuaimai Cloud Printing**
   - API: `tsplXmlWrite`
   - Authentication: appId + appSecret
   - Input: base64 encoded images

## Python Dependencies
```
pdf2image>=1.16.0  # PDF to image conversion
Pillow>=10.0.0     # Already installed, for image processing
```

## System Dependencies
- `poppler-utils` (for pdf2image on Linux)
- Already available in Docker container

## User Impact
- **Positive**: Significantly faster batch shipping workflow, reduced manual work
- **Risk**: Printing failures need clear error messages and retry mechanism

## Success Criteria
1. Users can select multiple rentals and print all waybills with one click
2. Printing success rate >95% under normal network conditions
3. Clear error messages for each failed print job
4. Average printing time <10 seconds for batch of 10 waybills

## Implementation Phases
1. **Phase 1**: Backend services (SF API integration, PDF conversion, Kuaimai integration)
2. **Phase 2**: Frontend UI (button, printer selection, status display)
3. **Phase 3**: Error handling and retry mechanism

## Open Questions
1. How to handle printer selection? (default printer vs. user selection)
2. Should we cache converted images or convert on-demand?
3. What to do if only some waybills fail to print?
4. Do we need to store printing history/logs?

## Related Changes
- Depends on existing `batch-print-shipping-orders` for UI patterns
- Complements `enhance-batch-shipping-workflow` for complete shipping automation
