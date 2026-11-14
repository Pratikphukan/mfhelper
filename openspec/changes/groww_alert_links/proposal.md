# Proposal: Use Fund Code Map links in alert emails

## Problem

MFHelper currently creates Groww links using the retired `/mutual-funds/search?q=...` URL. Groww returns a Page not found response for these links.

## Proposed change

Use the user's existing `Fund Code Map` sheet as the source of each fund's Groww page URL. The alert job will match by AMFI scheme code and use the saved URL for the fund card's Groww button. Preserve the existing button labels and appearance.

## Outcome

Confluence and trimming cards will link to the correct Groww fund page when a valid URL is available. If a URL is unavailable, the button will open Groww's general mutual-funds page instead of a broken link.
