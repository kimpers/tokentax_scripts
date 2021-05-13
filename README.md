## About
This script crawls through your tx's (direct and internal) and generates TokenTax entries for trades on 0x:
  1. 0x V2-V4 Limit Orders (as Maker or Taker + Protocol Fee)
  2. 0x Forwarder trades
  3. Aggregation
  4. Meta-Transactions
  
The entries are placed into ZeroExTrades.csv, which can be uploaded to TokenTax.

## Usage
Update `conf.json` with your wallets then execute `python3 zeroex.py`.

## Importing to TokenTax
Before uploading, you must:
  1. Delete all 0x entries imported automatically from your wallet by TokenTax:
     * Filter your TokenTax transactions by "To (contract)" equals the `EXCHANGES` listed below.
     * For indirect fills, like meta-transactions and limit orders, tx hashes will be printed by this script.
       Fileter by "Tx Hash" on TokenTax and delete these manually.

  2. This script also combines REPv1 and REPv2 into REP. Exchanges are not
     consistent with this ticker, so this is the best way to ensure entries are aligned. 
     Manually replace all REPv1 and REPv2 with REP in TokenTax, as well.

## To-Do
    * Does not currently account for the gas cost paid for the transaction. Technically, this should be 
      added as the "Fee" for a TokenTax transaction.
    * It ignores any refunded tokens from aggregation on 0x. This is normally a dust amount (like 1 cent),
      so can generally be ignored.
