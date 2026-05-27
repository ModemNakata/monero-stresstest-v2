#!/usr/bin/env python3
"""
Monero Wallet Balance Info
Lists all accounts, addresses, and their balances
"""

import requests
import json
import sys

class MoneroWalletInfo:
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
            response = self.session.post(self.wallet_url, json=payload, timeout=10)
            result = response.json()
            
            if "error" in result and result["error"] is not None:
                raise Exception(f"RPC Error: {result['error']}")
            
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
    
    def get_addresses(self, account_index):
        """Get all addresses for an account"""
        result = self.rpc_call("get_address", {"account_index": account_index})
        if result is None:
            return []
        return result.get("addresses", [])
    
    def get_balance_all(self, all_accounts=True):
        """Get balance for all accounts"""
        result = self.rpc_call("get_balance", {"all_accounts": all_accounts})
        if result is None:
            return None
        return result
    
    def format_xmr(self, atomic_units):
        """Convert atomic units to XMR"""
        return atomic_units / 1e12
    
    def print_wallet_info(self):
        """Print complete wallet information"""
        print("\n" + "=" * 80)
        print("MONERO WALLET INVENTORY")
        print("=" * 80)
        
        # Get total balance
        print("\n📊 TOTAL WALLET BALANCE:")
        print("-" * 80)
        
        total_balance = self.get_balance_all(all_accounts=True)
        if total_balance is None:
            print("❌ Failed to get balance info")
            return
        
        total_xmr = self.format_xmr(total_balance.get("balance", 0))
        unlocked_xmr = self.format_xmr(total_balance.get("unlocked_balance", 0))
        
        print(f"  Total Balance:     {total_xmr:>15.12f} XMR ({total_balance.get('balance', 0)} atomic)")
        print(f"  Unlocked Balance:  {unlocked_xmr:>15.12f} XMR ({total_balance.get('unlocked_balance', 0)} atomic)")
        print(f"  Blocks to Unlock:  {total_balance.get('blocks_to_unlock', 0)}")
        
        # Get all accounts
        print("\n📋 ACCOUNTS & ADDRESSES:")
        print("-" * 80)
        
        accounts = self.get_accounts()
        
        if not accounts:
            print("❌ No accounts found or connection failed")
            return
        
        total_accounts = len(accounts)
        total_addresses = 0
        grand_total_balance = 0
        grand_total_unlocked = 0
        
        for account_idx, account in enumerate(accounts, 1):
            account_index = account.get("account_index", "?")
            account_label = account.get("label", "(no label)")
            account_balance = account.get("balance", 0)
            account_unlocked = account.get("unlocked_balance", 0)
            
            print(f"\n  📁 Account {account_index}: {account_label}")
            print(f"     Balance: {self.format_xmr(account_balance):>15.12f} XMR | "
                  f"Unlocked: {self.format_xmr(account_unlocked):>15.12f} XMR")
            
            # Get addresses for this account
            addresses = self.get_addresses(account_index)
            
            if addresses:
                print(f"     Addresses ({len(addresses)}):")
                
                for addr_idx, address in enumerate(addresses):
                    addr_string = address.get("address", "?")
                    addr_label = address.get("label", "")
                    addr_balance = address.get("balance", 0)
                    addr_unlocked = address.get("unlocked_balance", 0)
                    address_index = address.get("address_index", "?")
                    num_outputs = address.get("num_unspent_outputs", 0)
                    used = address.get("used", False)
                    
                    # Abbreviate address display
                    short_addr = f"{addr_string[:16]}...{addr_string[-16:]}"
                    
                    status = "✓" if used else "○"
                    label_str = f' [{addr_label}]' if addr_label else ""
                    
                    print(f"       {status} [{address_index}] {short_addr}{label_str}")
                    print(f"           Balance: {self.format_xmr(addr_balance):>15.12f} XMR | "
                          f"Unlocked: {self.format_xmr(addr_unlocked):>15.12f} XMR | "
                          f"Outputs: {num_outputs}")
                    
                    total_addresses += 1
                    grand_total_balance += addr_balance
                    grand_total_unlocked += addr_unlocked
            else:
                print(f"     ⚠️  No addresses found")
        
        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY:")
        print("-" * 80)
        print(f"  Total Accounts:       {total_accounts}")
        print(f"  Total Addresses:      {total_addresses}")
        print(f"  Grand Total Balance:  {self.format_xmr(grand_total_balance):>15.12f} XMR "
              f"({grand_total_balance} atomic)")
        print(f"  Grand Total Unlocked: {self.format_xmr(grand_total_unlocked):>15.12f} XMR "
              f"({grand_total_unlocked} atomic)")
        print("=" * 80 + "\n")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Monero Wallet Balance & Account Information"
    )
    parser.add_argument("--wallet-url", type=str, default="http://127.0.0.1:28088",
                       help="Wallet RPC URL (default: http://127.0.0.1:28088)")
    
    args = parser.parse_args()
    
    wallet = MoneroWalletInfo(args.wallet_url)
    wallet.print_wallet_info()

if __name__ == "__main__":
    main()
