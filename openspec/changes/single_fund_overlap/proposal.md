# Proposal: Compare one fund with the configured funds

## Goal

Add a command that takes one fund from `config/funds.yaml` and reports its stock-holdings overlap with each of the other configured funds.

## Proposed shape

Add a local command-line script, `fund_overlap_main.py`, that takes any valid AMFI scheme code and compares that fund with the active funds in the local `config/funds.yaml`. The target fund does not need to be listed in that file. The YAML supplies the comparison funds only. It reuses MFHelper's existing AMFI/Tickertape mapping, holdings fetch, and overlap calculation code. It prints a ranked comparison and the largest shared stock holdings for each pair. It does not run as a remote service or write to Google Sheets.

Remote or scheduled execution may be considered later, but is out of scope for this version.

## Why a separate command

The existing `overlap_main.py` prints a full pairwise matrix and writes a full report to a Google Sheet. A focused script can answer the one-fund question without changing that existing workflow or triggering its sheet write.
