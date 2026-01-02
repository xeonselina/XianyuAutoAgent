# Capability: PDF to Image Conversion

## Summary
Convert SF Express waybill PDFs to optimized images suitable for thermal printer output.

## ADDED Requirements

### Requirement: Convert PDF to PNG images
The system SHALL convert waybill PDF bytes to PNG image format using pdf2image library.

#### Scenario: Convert single-page PDF
**GIVEN** waybill PDF with 1 page
**WHEN** convert_pdf_to_images() is called with PDF bytes
**THEN** the system returns list with 1 PNG image
**AND** image dimensions match printer resolution (203 DPI)

#### Scenario: Convert multi-page PDF
**GIVEN** waybill PDF with 2 pages
**WHEN** convert_pdf_to_images() is called
**THEN** the system returns list with 2 PNG images
**AND** each image is converted independently

#### Scenario: Handle corrupted PDF
**GIVEN** invalid or corrupted PDF bytes
**WHEN** convert_pdf_to_images() is called
**THEN** the system raises PDFConversionError
**AND** error message indicates PDF is invalid

### Requirement: Optimize images for thermal printing
The system SHALL optimize converted images for black/white thermal printing.

#### Scenario: Convert to 1-bit black/white
**GIVEN** color PNG image from PDF
**WHEN** optimize_for_thermal_printer() is called
**THEN** the system converts image to 1-bit mode
**AND** applies dithering for better quality
**AND** output is pure black/white (no grayscale)

#### Scenario: Enhance contrast for thermal printing
**GIVEN** low-contrast PNG image
**WHEN** optimize_for_thermal_printer() is called
**THEN** the system increases contrast
**AND** darkens black areas
**AND** whitens white areas

### Requirement: Encode images as base64
The system SHALL encode optimized images as base64 strings for API transmission.

#### Scenario: Encode PNG to base64
**GIVEN** optimized PNG image bytes
**WHEN** image_to_base64() is called
**THEN** the system returns valid base64 string
**AND** string can be decoded back to original image
**AND** no padding issues

### Requirement: Support configurable DPI
The system SHALL support 203 DPI and 300 DPI printer resolutions.

#### Scenario: Convert at 203 DPI (default)
**GIVEN** waybill PDF
**WHEN** convert_pdf_to_images() is called without DPI parameter
**THEN** the system uses 203 DPI resolution
**AND** image dimensions are calculated for 203 DPI

#### Scenario: Convert at 300 DPI
**GIVEN** waybill PDF
**WHEN** convert_pdf_to_images(dpi=300) is called
**THEN** the system uses 300 DPI resolution
**AND** output images have higher resolution

### Requirement: Handle resource cleanup
The system SHALL properly clean up temporary files created during conversion.

#### Scenario: Clean up temporary files after successful conversion
**GIVEN** PDF conversion creates temp files
**WHEN** convert_pdf_to_images() completes successfully
**THEN** all temporary files are deleted
**AND** no files remain in temp directory

#### Scenario: Clean up temporary files after error
**GIVEN** PDF conversion fails with error
**WHEN** exception is raised
**THEN** all temporary files are deleted
**AND** resources are properly released
