#!/usr/bin/env python3
"""
Monero Account Sweep
Sweep all funds from one account to another
"""

import requests
import json
import sys
import argparse

class MoneroSweep:
    def __init__(self, wallet_url="http://127.0.0.1:28088"):
        self.wallet_url = f"{wallet_url}/json_rpc"
        self.session = requests.Session()
    
    def rpc_call(self, method, params=None):
        """Make RPC call"""
        if params is None:
            params = {}
        
        payload = {
            "jsonrpc": "2.0",
            "id": "0",
            "method": method,
            "params": params
        }
        
        try:
            response = self.session.post(self.wallet_url, json=payload, timeout=30)
            result = response.json()
            
            if "error" in result and result["error"] is not None:
                error = result["error"]
                raise Exception(f"RPC Error {error.get('code', '?')}: {error.get('message', 'Unknown')}")
            
            return result.get("result", {})
        except Exception as e:
            print(f"❌ RPC Error: {e}")
            return None
    
    def get_address(self, account_index):
        """Get primary address for an account"""
        result = self.rpc_call("get_address", {"account_index": account_index})
        if result is None:
            return None
        return result.get("address", None)
    
    def get_balance(self, account_index):
        """Get balance for account"""
        result = self.rpc_call("get_balance", {"account_index": account_index})
        if result is None:
            return 0, 0
        return result.get("balance", 0), result.get("unlocked_balance", 0)
    
    def sweep_all(self, address, from_account, subaddr_indices_all=True):
        """Sweep all funds from account to address"""
        params = {
            "address": address,
            "account_index": from_account,
            "priority": 0,
            "subaddr_indices_all": subaddr_indices_all
        }
        
        result = self.rpc_call("sweep_all", params)
        return result
    
    def format_xmr(self, atomic_units):
        """Convert atomic units to XMR"""
        return atomic_units / 1e12
    
    def sweep_account(self, from_account, to_account):
        """Sweep all funds from one account to another"""
        
        print("\n" + "=" * 80)
        print("MONERO ACCOUNT SWEEP")
        print("=" * 80)
        
        # Validate accounts
        print(f"\n📋 Validation:")
        print(f"  From Account: {from_account}")
        print(f"  To Account: {to_account}")
        
        if from_account == to_account:
            print(f"❌ Source and destination accounts must be different!")
            return False
        
        # Get source account balance
        print(f"\n💰 Source Account Balance:")
        balance, unlocked = self.get_balance(from_account)
        print(f"  Account {from_account}:")
        print(f"    Total: {self.format_xmr(balance):.12f} XMR ({balance} atomic)")
        print(f"    Unlocked: {self.format_xmr(unlocked):.12f} XMR ({unlocked} atomic)")
        
        if unlocked == 0:
            print(f"❌ No unlocked balance in account {from_account}!")
            return False
        
        # Get destination account address
        print(f"\n📍 Fetching destination address...")
        dest_address = self.get_address(to_account)
        
        if not dest_address:
            print(f"❌ Could not get address for account {to_account}!")
            return False
        
        short_addr = f"{dest_address[:16]}...{dest_address[-16:]}"
        print(f"  Account {to_account}: {short_addr}")
        
        print(f"\n📊 Sweep Summary:")
        print(f"  Amount to sweep: {self.format_xmr(unlocked):.12f} XMR")
        print(f"  Destination: {short_addr}")
        
        # Confirm
        response = input(f"\n❓ Proceed with sweep? (yes/no): ").strip().lower()
        if response not in ["yes", "y"]:
            print("Cancelled.")
            return False
        
        # Send sweep
        print(f"\n⏳ Sweeping all funds...")
        result = self.sweep_all(dest_address, from_account, subaddr_indices_all=True)
        
        if result is None:
            print("❌ Sweep failed!")
            return False
        
        tx_hashes = result.get("tx_hash_list", [])
        fees = result.get("fee_list", [])
        amounts = result.get("amount_list", [])
        weights = result.get("weight_list", [])
        
        if not tx_hashes:
            print("❌ No transaction hashes returned!")
            return False
        
        print(f"\n✅ Sweep Successful!")
        print(f"  Number of transactions: {len(tx_hashes)}")
        
        total_amount_swept = 0
        total_fee = 0
        
        for i, (tx_hash, fee, amount) in enumerate(zip(tx_hashes, fees, amounts)):
            print(f"\n  Transaction {i+1}/{len(tx_hashes)}:")
            print(f"    TX Hash: {tx_hash}")
            print(f"    Amount Swept: {self.format_xmr(amount):.12f} XMR ({amount} atomic)")
            print(f"    Fee: {self.format_xmr(fee):.12f} XMR ({fee} atomic)")
            
            if isinstance(weights, list) and i < len(weights):
                print(f"    Weight: {weights[i]}")
            
            total_amount_swept += amount
            total_fee += fee
        
        print(f"\n  📈 Summary:")
        print(f"    Total Amount Swept: {self.format_xmr(total_amount_swept):.12f} XMR ({total_amount_swept} atomic)")
        print(f"    Total Fees: {self.format_xmr(total_fee):.12f} XMR ({total_fee} atomic)")
        print(f"    Net Transfer: {self.format_xmr(total_amount_swept):.12f} XMR")
        
        print("\n" + "=" * 80 + "\n")
        return True

def main():
    parser = argparse.ArgumentParser(
        description="Sweep all funds from one account to another",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Sweep all funds from account 1 to account 0
  python3 sweep_account.py 1 0

  # Sweep from account 2 to account 5
  python3 sweep_account.py 2 5

  # Custom wallet URL
  python3 sweep_account.py --wallet-url http://localhost:28088 1 0
        """
    )
    
    parser.add_argument("from_account", type=int, help="Source account index (will be swept)")
    parser.add_argument("to_account", type=int, help="Destination account index (will receive funds)")
    parser.add_argument("--wallet-url", type=str, default="http://127.0.0.1:28088",
                       help="Wallet RPC URL (default: http://127.0.0.1:28088)")
    
    args = parser.parse_args()
    
    sweep = MoneroSweep(args.wallet_url)
    success = sweep.sweep_account(args.from_account, args.to_account)
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
