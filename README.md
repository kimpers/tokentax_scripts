## About
This script crawls through your tx's (direct and internal) and generates a TokenTax CSV for ERC20 trades on 0x. This works with all variations of the 0x Protocol dating back to 2018. Includes:
  1. 0x V2-V4 Limit Orders (as Maker or Taker)
  2. Protocol Fees (introduced in V3)
  3. 0x Forwarder trades
  4. Aggregation
  5. Meta-Transactions
  
The entries are placed into ZeroExTrades.csv, which can be uploaded to TokenTax.

## Usage
Update `conf.json` with your wallets then execute `python3 zeroex.py`.

## Implementation Details

This script takes a set of wallets and generates a CSV of corresponding 0x trades. It does the following:

1. For a given wallet, collect all transactions that interacted with a 0x contract (via the Etherscan API). This includes both (i) tx's originating from the wallet AND (ii) internal tx's that sent ETH or ERC20 tokens to the wallet.

2. For tx's originating from the wallet, the wallet is the Taker. Internal transactions the wallet is either the Maker (created a limit or RFQ order) or the wallet is the Taker but the tx was submitted by a MetaTransaction relayer. 

3. If the tx originated from the wallet then the user paid a gas fee and *possibly* a protocol fee ~ both in ETH. These are aggregated into a single "Fee" record for TokenTax. If the tx did not originate from the wallet, then no fee is entered.

4. Next, we look at the incoming and outgoing ERC20 transfers associated with the wallet for each transaction. There may be several ingress and egress transfers (either a muti-hop trade or a fee charged by a 0x integrator). All ingress transfers are merged into a single "Deposit" entry. All egress transfers are merged into a single "Withdrawal" entry. 

5. The Deposit, Withdrawal, and Fee are combined into a single TokenTax Trade.


## Importing to TokenTax
Before uploading, you must:
  1. Delete all 0x entries imported automatically from your wallet by TokenTax:
     * Filter your TokenTax transactions by "To (contract)" equals the `EXCHANGES` listed below.
     * For indirect fills, like meta-transactions and limit orders, tx hashes will be printed by this script.
       Fileter by "Tx Hash" on TokenTax and delete these manually.

  2. This script also combines REPv1 and REPv2 into REP. Exchanges are not
     consistent with this ticker, so this is the best way to ensure entries are aligned. 
     Manually replace all REPv1 and REPv2 with REP in TokenTax, as well.

## Notes

- This is primarily tested against Matcha. It should work with all Matcha trades since the inception of this product in mid-2020.
- The script currently ignores any refunded tokens from aggregation through 0x. This should be a dust amount, caused by rounding errors or state changing between time-of-quote and time-of-fill. For completeness, it would be a cheeky addition to make this work with refunds. But for nearly all trades we can ignore this altogether (I haven't come across a case in my own wallets where the amount was not dust).
- 0x does emit their own events. However, ERC20 Transfer events are much more reliable for reconstructing a trade. Firstly, events emitted by 0x have been upgraded many times ~ especially in 2020 when the protocol iteratively evolved from a limit-order settlement protocol to a generalized liquidity aggregator. Additionally, there were periods (esp in V3) where the 0x event reflected only the minimum amount bought or sold and not the true value. Because of this it is much more precise (and simpler) to parse ERC20 transfer events. There could be a scenario where a non-token contract emits a Transfer event; such an edge case could be handled by a TCR, but this script simply raises an exception.
