import requests
import pprint
import copy
import csv
import hashlib
import logging
import traceback
import json
from functools import reduce
from enum import Enum
import re
from datetime import datetime, timezone
pp = pprint.PrettyPrinter(indent=2)

#### Load Conf ####
conf = json.load(open('conf.json'))
wallets = conf['wallets']

# Configure (ALL ADDRESSES SHOULD BE LOWER CASE)
CSV_FILENAME = 'zeroex_trades.csv'
EXCHANGES = [
    '0xdef1c0ded9bec7f1a1670819833240f027b25eff', # 0x V4
    '0x61935cbdd02287b511119ddb11aeb42f1593b7ef', # 0x V3
    '0x6958f5e95332d93d21af0d7b9ca85b8212fee0a5', # 0x V3 Forwarder
    '0x080bf510fcbf18b91105470639e9561022937712', # 0x V2
]
# Any tx sent here will generate a migration entry. Cannot use with Compound (yet) b/c they also do repayments and income.

# Sanity check - can only handle 2 assets
def assertSameToken(transfers):
    token = None
    for transfer in transfers:
        if token == None:
            token = transfer['token']
        elif token != transfer['token']:
            raise Exception("Not unique!")
    
def assertNotEmpty(transfers):
    if len(transfers) == 0:
        raise Exception('Missing transfers!')

def flattenTransfers(transfers, transferType, ignoreTokens = []):
    transfersOfType = [t for t in transfers if t['type'] == transferType and not t['token'] in ignoreTokens]

    assertNotEmpty(transfersOfType)
    assertSameToken(transfersOfType)
    amount = 0
    for transfer in transfersOfType: 
        amount += float(transfer['amount']) 
    
    return {
        'token': transfersOfType[0]['token'],
        'amount': str(amount)
    }

def processTrade(txType, txInfo, wallet):
    # Construct single withdrawal
    withdrawal = None
    try: 
        # First try with ignoring ETH (protocol fee)
        withdrawal = flattenTransfers(txInfo['transfers'], 'Withdrawal', 'ETH')
    except:
        withdrawal = flattenTransfers(txInfo['transfers'], 'Withdrawal')
   
    # Construct single Deposit.
    # We ignore the deposits of the Withdrawal token. This indicates a dust refund from 0x.
    # This could alternatively be substracted from the `withdrawal`, but since it's dust we ignore it.
    try:
        # First try with ignoring ETH (protocol fee refund)
        deposit = flattenTransfers(txInfo['transfers'], 'Deposit', [withdrawal['token']])
    except:
        # Try with ignoring the protocol fee refund (either ETH or WETH; select smaller of the two)
        # This is kinda hacky. Could do deeper introspection.
        ethAndWethDeposits = [t for t in txInfo['transfers'] if t['type'] == 'Deposit' and t['token'] in ['WETH', 'ETH']]
        ethAndWethDepositsSorted = sorted(ethAndWethDeposits, key=lambda t: float(t['amount']))

        protocolFeeToken = ethAndWethDepositsSorted[0]['token']

        # Try to get the deposit token, now ignoring the protocol fee token.
        deposit = flattenTransfers(txInfo['transfers'], 'Deposit', [protocolFeeToken, withdrawal['token']])

    # Construct trade
    trade = {
        'Type': txType, 
        'BuyAmount': deposit['amount'],
        'BuyCurrency': deposit['token'],
        'SellAmount': withdrawal['amount'],
        'SellCurrency': withdrawal['token'],
        'FeeAmount': '0',
        'FeeCurrency': '',
        'Exchange': 'ZeroEx',
        'Group': '',
        'Comment': 'ZeroEx Tx - ' + txInfo['hash'],
        'Date': str(datetime.utcfromtimestamp(int(txInfo['timestamp']))),
    }

    return trade

def processTx(txType, txInfo, wallet, targetContracts):
    # Check if we should process this `txInfo`
    if txInfo['sentByWallet'] and not txInfo['contract'] in targetContracts:
        # This tx was sent by the wallet, but not to a target contract.
        return None
    elif not txInfo['sentByWallet']:
        # Get tx receipt
        r = requests.post('https://mainnet.infura.io/v3/ce214d176c62463fa320a73c3d4ca9bc', json={"jsonrpc":"2.0", "id": 1, "method": "eth_getTransactionReceipt", "params": [txInfo['hash']]}).json()
        txReceipt = r['result']

        # Check if a target contract emitted an event. If not, we're done.
        logsEmittedByKnownContract = [l for l in txReceipt['logs'] if l['address'] in targetContracts]
        if len(logsEmittedByKnownContract) == 0:
            # This tx did not go through a target contract.
            return None
    elif len(txInfo['transfers']) == 0:
        # This was going to a target address, but there was no transfer.
        return None

    return processTrade(txType, txInfo, wallet)

def processWallet(csvWriter, wallet, targetContracts, txType, onlyDirect):
    # Fetch all transactions sent by this wallet.
    r = requests.get('https://api.etherscan.io/api?module=account&action=txlist&address=' + wallet + '&startblock=0&endblock=999999999&sort=asc&apikey=U7JCXJ4YFEJMMDJVAQKUANSURIMXKAXNFM').json()
    transactions = r['result']
   
    # Fetch all ERC20 transfers for this wallet.
    r = requests.get('https://api.etherscan.io/api?module=account&action=tokentx&address=' + wallet + '&startblock=0&endblock=999999999&sort=asc&apikey=U7JCXJ4YFEJMMDJVAQKUANSURIMXKAXNFM').json()
    erc20Transfers = r['result']

    # Fetch all transactions that sent ETH to this wallet.
    r = requests.get('https://api.etherscan.io/api?module=account&action=txlistinternal&address=' + wallet + '&startblock=0&endblock=999999999&sort=asc&apikey=U7JCXJ4YFEJMMDJVAQKUANSURIMXKAXNFM').json()
    inboundEthTransfers = r['result']

    # Merge everything
    txHashes = []
    txInfoByHash = {}

    for tx in transactions:
        if tx['isError'] != '0':
            # This tx failed
            continue

        txHashes.append(tx['hash'])
        txInfo = {
            'hash': tx['hash'],
            'timestamp': tx['timeStamp'],
            'sentByWallet': True,
            'contract': tx['to'],
            'transfers': []
        }
    
        if int(tx['value']) > 0:
            txInfo['transfers'].append({
                'type': 'Withdrawal',
                'token': 'ETH',
                'amount': str(int(tx['value']) / float(10**18))
            })

        txInfoByHash[tx['hash']] = txInfo

    # Parse ERC20 Transfers
    for rawTransfer in erc20Transfers:
        # Parse transfer
        txHash = rawTransfer['hash']
        timestamp = rawTransfer['timeStamp']
        token = rawTransfer['tokenSymbol']
        transfer = {
            'type': 'Withdrawal' if rawTransfer['from'] == wallet else 'Deposit',
            'token': rawTransfer['tokenSymbol'],
            'amount': int(rawTransfer['value']) / float(10 ** int(rawTransfer['tokenDecimal'])),
        }

        # Handle non-standard names
        # These are not handled properly across different exchanges.
        # Simpler to just name them all REP.
        if transfer['token'] == 'REPv1' or transfer['token'] == 'REPv2':
            transfer['token'] = 'REP'

        # Add to our list of transactions to process.
        if not txHash in txInfoByHash:
            txInfoByHash[txHash] = {
                'hash': txHash,
                'timestamp': timestamp,
                'sentByWallet': False,
                'contract': None,
                'transfers': [transfer]
            }
            txHashes.append(txHash)
        else:
            txInfoByHash[txHash]['transfers'].append(transfer)

    # Parse Incoming ETH
    for rawTransfer in inboundEthTransfers:
        # Parse transfer
        txHash = rawTransfer['hash']
        timestamp = rawTransfer['timeStamp']
        transfer = {
            'type': 'Deposit',
            'token': 'ETH',
            'amount': str(int(rawTransfer['value']) / float(10**18))
        }

        # Add to our list of transactions to process.
        if not txHash in txInfoByHash:
            txInfoByHash[txHash] = {
                'hash': txHash,
                'timestamp': timestamp,
                'sentByWallet': False,
                'contract': None,
                'transfers': [transfer]
            }
            txHashes.append(txHash)
        else:
            txInfoByHash[txHash]['transfers'].append(transfer)

    # We track indirect transactions to print out at the end, as these must be individually deleted from TokenTax.
    indirectTxs = []

    # We track failed tx's as sometimes we just need to process them again (ex if we get rate-limited).
    failedTxs = []

    seen = False

    # Process transactions that produced each transfer.
    processedTxs = {}

    todo = [
    ]

    for txHash in txHashes:
        if onlyDirect and txInfoByHash[txHash]['contract'] == None:
            # Skip this one because we only want tx's that were sent directly from the wallet.
            continue

        if len(todo) > 0 and not txHash in todo:
            continue
        
        # print('Processing ', txHash)
        # pp.pprint(txInfoByHash[txHash])

        if txHash in processedTxs:
            continue
        else:
            processedTxs[txHash] = True
        
        # Get trade and write to CSV
        try:
            trade = processTx(txType, txInfoByHash[txHash], wallet, targetContracts)
            if trade == None: # is nothing if cancelled
                continue
            
            if not txInfoByHash[txHash]['sentByWallet']:
                indirectTxs.append(txHash)

            csvWriter.writerow(trade)
        except Exception as e:
            failedTxs.append(txHash)
            print(txHash)
            print('\tFailed to get trade: ', e)
            traceback.print_exc()

    print("Failed Txs (sometimes we get rate-limited by Etherscan and you need to run these again):")
    pp.pprint(failedTxs)

    print("Limit Order Fills / Meta-Transactions Tx Hashes (delete each hash individually from TokenTax):")
    pp.pprint(indirectTxs)


#### SETUP ####
with open(CSV_FILENAME, 'w') as csvFile:
    csvWriter = csv.DictWriter(csvFile, extrasaction='ignore', fieldnames=[
        'Type',    
        'BuyAmount',
        'BuyCurrency',
        'SellAmount',
        'SellCurrency',
        'FeeAmount',
        'FeeCurrency',
        'Exchange',
        'Group',
        'Comment',
        'Date',
    ])
    csvWriter.writeheader()

    for wallet in wallets:
        print("-- %s --"%(wallet))
        processWallet(csvWriter, wallet.lower(), EXCHANGES, 'Trade', False)
    
    csvFile.flush()
    csvFile.close()
