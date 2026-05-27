#!/usr/bin/env python3
"""
Monero Sweep All Accounts to Zero
Sweep all funds from all accounts (> 0) to account 0, one by one
"""

import requests
import json
import sys
import argparse
import time

class MoneroSweepAll:
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
    
    def get_accounts(self):
        """Get all accounts"""
        result = self.rpc_call("get_accounts", {})
        if result is None:
            return []
        return result.get("subaddress_accounts", [])
    
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
    
    def sweep_all(self, address, from_account):
        """Sweep all funds from account to address"""
        params = {
            "address": address,
            "account_index": from_account,
            "priority": 0,
            "subaddr_indices_all": True
        }
        
        result = self.rpc_call("sweep_all", params)
        return result
    
    def format_xmr(self, atomic_units):
        """Convert atomic units to XMR"""
        return atomic_units / 1e12
    
    def sweep_all_accounts(self, delay_between_sweeps=1.0):
        """Sweep all accounts > 0 to account 0"""
        
        print("\n" + "=" * 80)
        print("MONERO SWEEP ALL ACCOUNTS TO ZERO")
        print("=" * 80)
        
        # Get all accounts
        print(f"\n📋 Fetching accounts...")
        accounts = self.get_accounts()
        
        if not accounts:
            print("❌ No accounts found!")
            return False
        
        # Filter accounts > 0
        accounts_to_sweep = [acc for acc in accounts if acc.get("account_index", 0) > 0]
        
        if not accounts_to_sweep:
            print("✅ No accounts to sweep (only account 0 exists)")
            return True
        
        # Show account summary
        print(f"\n📊 Account Summary:")
        print(f"  Total accounts: {len(accounts)}")
        print(f"  Accounts to sweep: {len(accounts_to_sweep)}")
        
        total_balance = 0
        total_unlocked = 0
        
        for account in accounts:
            account_index = account.get("account_index", "?")
            balance = account.get("balance", 0)
            unlocked = account.get("unlocked_balance", 0)
            label = account.get("label", "(no label)")
            
            print(f"\n  Account {account_index}: {label}")
            print(f"    Balance: {self.format_xmr(balance):.12f} XMR")
            print(f"    Unlocked: {self.format_xmr(unlocked):.12f} XMR")
            
            total_balance += balance
            total_unlocked += unlocked
        
        print(f"\n  Total Balance (all accounts): {self.format_xmr(total_balance):.12f} XMR")
        print(f"  Total Unlocked (all accounts): {self.format_xmr(total_unlocked):.12f} XMR")
        
        # Get destination address (account 0)
        print(f"\n📍 Destination (Account 0):")
        dest_address = self.get_address(0)
        
        if not dest_address:
            print(f"❌ Could not get address for account 0!")
            return False
        
        short_addr = f"{dest_address[:16]}...{dest_address[-16:]}"
        print(f"  Address: {short_addr}")
        
        # Confirm
        print(f"\n⚠️  This will sweep {len(accounts_to_sweep)} account(s) to account 0")
        response = input(f"❓ Proceed with sweep? (yes/no): ").strip().lower()
        if response not in ["yes", "y"]:
            print("Cancelled.")
            return False
        
        # Sweep accounts one by one
        print(f"\n" + "=" * 80)
        print("SWEEPING ACCOUNTS")
        print("=" * 80)
        
        successful_sweeps = 0
        failed_sweeps = 0
        total_swept = 0
        total_fees_paid = 0
        
        for idx, account in enumerate(accounts_to_sweep, 1):
            account_index = account.get("account_index", "?")
            label = account.get("label", "(no label)")
            
            print(f"\n📤 [{idx}/{len(accounts_to_sweep)}] Sweeping Account {account_index}: {label}")
            
            # Get current balance
            balance, unlocked = self.get_balance(account_index)
            
            if unlocked == 0:
                print(f"   ⏭️  No unlocked balance, skipping")
                continue
            
            print(f"   Amount to sweep: {self.format_xmr(unlocked):.12f} XMR")
            
            # Sweep
            result = self.sweep_all(dest_address, account_index)
            
            if result is None:
                print(f"   ❌ Sweep failed!")
                failed_sweeps += 1
            else:
                tx_hashes = result.get("tx_hash_list", [])
                fees = result.get("fee_list", [])
                amounts = result.get("amount_list", [])
                
                if not tx_hashes:
                    print(f"   ❌ No transaction hashes returned!")
                    failed_sweeps += 1
                else:
                    total_amount_swept = sum(amounts)
                    total_fee = sum(fees)
                    
                    total_swept += total_amount_swept
                    total_fees_paid += total_fee
                    successful_sweeps += 1
                    
                    print(f"   ✅ Success!")
                    print(f"      Transactions: {len(tx_hashes)}")
                    print(f"      Amount: {self.format_xmr(total_amount_swept):.12f} XMR")
                    print(f"      Fee: {self.format_xmr(total_fee):.12f} XMR")
                    
                    for i, tx_hash in enumerate(tx_hashes):
                        print(f"      TX {i+1}: {tx_hash}")
            
            # Delay between sweeps
            if idx < len(accounts_to_sweep) and delay_between_sweeps > 0:
                print(f"   ⏳ Waiting {delay_between_sweeps}s before next sweep...")
                time.sleep(delay_between_sweeps)
        
        # Summary
        print(f"\n" + "=" * 80)
        print("SWEEP COMPLETE")
        print("=" * 80)
        print(f"\n📊 Results:")
        print(f"  Successful sweeps: {successful_sweeps}")
        print(f"  Failed sweeps: {failed_sweeps}")
        print(f"  Total XMR swept: {self.format_xmr(total_swept):.12f} XMR ({total_swept} atomic)")
        print(f"  Total fees paid: {self.format_xmr(total_fees_paid):.12f} XMR ({total_fees_paid} atomic)")
        print(f"  Net transferred: {self.format_xmr(total_swept):.12f} XMR")
        
        # Show final account 0 balance
        print(f"\n💰 Final Account 0 Balance:")
        balance, unlocked = self.get_balance(0)
        print(f"  Total: {self.format_xmr(balance):.12f} XMR")
        print(f"  Unlocked: {self.format_xmr(unlocked):.12f} XMR")
        
        print("\n" + "=" * 80 + "\n")
        
        return failed_sweeps == 0

def main():
    parser = argparse.ArgumentParser(
        description="Sweep all accounts to account 0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Sweep all accounts to account 0 (with 1 second delay between sweeps)
  python3 sweep_all_accounts.py

  # No delay between sweeps (faster)
  python3 sweep_all_accounts.py --delay 0

  # 5 second delay between sweeps
  python3 sweep_all_accounts.py --delay 5

  # Custom wallet URL
  python3 sweep_all_accounts.py --wallet-url http://localhost:28088
        """
    )
    
    parser.add_argument("--wallet-url", type=str, default="http://127.0.0.1:28088",
                       help="Wallet RPC URL (default: http://127.0.0.1:28088)")
    parser.add_argument("--delay", type=float, default=1.0,
                       help="Delay between sweeps in seconds (default: 1.0)")
    
    args = parser.parse_args()
    
    sweep = MoneroSweepAll(args.wallet_url)
    success = sweep.sweep_all_accounts(delay_between_sweeps=args.delay)
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
