# Proposal: AMFI Quarterly Scheme AUM

## Objective

Use AMFI's scheme-wise Average AUM (AAUM) as the AUM source for fund analytics,
and show the reporting quarter next to each AUM value so users can tell how old
the figure is.

## Background

The analytics sheet currently has an `AUM (Cr.)` column and a `Last Updated
(IST)` timestamp. The timestamp is when MFHelper generated the row; it does not
say which reporting period the AUM value covers. AMFI's scheme-wise AAUM report
is quarterly, so the reporting quarter must be shown separately.

## Scope

- Retrieve scheme-wise quarterly AAUM from AMFI.
- Add an `AUM Quarter` column beside `AUM (Cr.)` in the analytics sheet.
- Keep `Last Updated (IST)` as the time MFHelper generated the row.
- Refresh the saved AUM when AMFI publishes a newer quarterly report; otherwise
  retain the latest available report and label its quarter.
- Handle AMFI's separate plan/option rows according to the approved AUM meaning.

## Out of Scope

- Daily or live AUM (AMFI's scheme-wise figure is quarterly average AUM).
- Expense-ratio source changes.
- Changes to unrelated analytics or dashboard calculations.
