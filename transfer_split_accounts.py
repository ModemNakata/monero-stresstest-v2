#!/usr/bin/env python3
"""
Monero Account Transfer Split
Transfer funds between accounts using transfer_split (handles large transactions)
"""

import requests
import json
import sys
import argparse

class MoneroTransferSplit:
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
    
    def get_addresses(self, account_index):
        """Get all addresses for an account"""
        result = self.rpc_call("get_address", {"account_index": account_index})
        if result is None:
            return []
        return result.get("addresses", [])
    
    def create_addresses(self, account_index, count):
        """Create multiple addresses for an account"""
        result = self.rpc_call("create_address", {
            "account_index": account_index,
            "count": count
        })
        if result is None:
            return []
        return result.get("addresses", [])
    
    def get_balance(self, account_index):
        """Get balance for account"""
        result = self.rpc_call("get_balance", {"account_index": account_index})
        if result is None:
            return 0, 0
        return result.get("balance", 0), result.get("unlocked_balance", 0)
    
    def transfer_split(self, from_account, destinations, amount_per_dest):
        """Send transfer using transfer_split"""
        dest_list = []
        for addr in destinations:
            dest_list.append({
                "amount": amount_per_dest,
                "address": addr
            })
        
        params = {
            "destinations": dest_list,
            "account_index": from_account,
            "priority": 0
        }
        
        result = self.rpc_call("transfer_split", params)
        return result
    
    def format_xmr(self, atomic_units):
        """Convert atomic units to XMR"""
        return atomic_units / 1e12
    
    def transfer_between_accounts(self, from_account, to_account, amount_per_addr):
        """Transfer from one account to first 16 subaddresses of another account"""
        
        print("\n" + "=" * 80)
        print("MONERO ACCOUNT TRANSFER (SPLIT)")
        print("=" * 80)
        
        # Validate accounts
        print(f"\n📋 Validation:")
        print(f"  From Account: {from_account}")
        print(f"  To Account: {to_account}")
        print(f"  Amount per address: {self.format_xmr(amount_per_addr):.12f} XMR ({amount_per_addr} atomic)")
        
        # Get source account balance
        print(f"\n💰 Source Account Balance:")
        balance, unlocked = self.get_balance(from_account)
        print(f"  Account {from_account}: {self.format_xmr(balance):.12f} XMR total, "
              f"{self.format_xmr(unlocked):.12f} XMR unlocked")
        
        if unlocked == 0:
            print(f"❌ No unlocked balance in account {from_account}!")
            return False
        
        # Get destination addresses
        print(f"\n📍 Fetching destination addresses...")
        to_addresses = self.get_addresses(to_account)
        
        if not to_addresses:
            print(f"❌ No addresses found in account {to_account}!")
            return False
        
        # Create more addresses if we have fewer than 16
        if len(to_addresses) < 20:
            addresses_needed = 20 - len(to_addresses)
            print(f"⏳ Creating {addresses_needed} more addresses...")
            
            new_addresses = self.create_addresses(to_account, addresses_needed)
            if new_addresses:
                print(f"✅ Created {len(new_addresses)} new addresses")
                # Refresh the address list
                to_addresses = self.get_addresses(to_account)
            else:
                print(f"⚠️  Could not create new addresses, using existing ones")
        
        # Take first 16 addresses
        destination_addrs = []
        for i in range(min(20, len(to_addresses))):
            addr_info = to_addresses[i]
            addr = addr_info.get("address", "")
            label = addr_info.get("label", "(no label)")
            addr_idx = addr_info.get("address_index", i)
            
            if addr:
                destination_addrs.append(addr)
                short_addr = f"{addr[:16]}...{addr[-16:]}"
                print(f"  [{addr_idx:2d}] {short_addr} - {label}")
        
        if not destination_addrs:
            print(f"❌ Could not get valid addresses from account {to_account}!")
            return False
        
        num_destinations = len(destination_addrs)
        total_amount = amount_per_addr * num_destinations
        
        print(f"\n📊 Transaction Summary:")
        print(f"  Destination Addresses: {num_destinations}")
        print(f"  Amount per Address: {self.format_xmr(amount_per_addr):.12f} XMR")
        print(f"  Total Amount: {self.format_xmr(total_amount):.12f} XMR")
        
        # Check if balance is sufficient
        if unlocked < total_amount:
            print(f"\n⚠️  Warning: Total amount exceeds unlocked balance!")
            print(f"   Unlocked: {self.format_xmr(unlocked):.12f} XMR")
            print(f"   Required: {self.format_xmr(total_amount):.12f} XMR")
        
        # Confirm
        response = input(f"\n❓ Proceed with transfer? (yes/no): ").strip().lower()
        if response not in ["yes", "y"]:
            print("Cancelled.")
            return False
        
        # Send transfer
        print(f"\n⏳ Sending transfer (may split into multiple transactions)...")
        result = self.transfer_split(from_account, destination_addrs, amount_per_addr)
        
        if result is None:
            print("❌ Transfer failed!")
            return False
        
        tx_hashes = result.get("tx_hash_list", [])
        fees = result.get("fee_list", [])
        amounts = result.get("amount_list", [])
        weights = result.get("weight_list", [])
        
        if not tx_hashes:
            print("❌ No transaction hashes returned!")
            return False
        
        print(f"\n✅ Transfer Successful!")
        print(f"  Number of transactions: {len(tx_hashes)}")
        
        total_amount_sent = 0
        total_fee = 0
        
        for i, (tx_hash, fee, amount) in enumerate(zip(tx_hashes, fees, amounts)):
            print(f"\n  Transaction {i+1}/{len(tx_hashes)}:")
            print(f"    TX Hash: {tx_hash}")
            print(f"    Amount Sent: {self.format_xmr(amount):.12f} XMR")
            print(f"    Fee: {self.format_xmr(fee):.12f} XMR")
            
            if isinstance(weights, list) and i < len(weights):
                print(f"    Weight: {weights[i]}")
            
            total_amount_sent += amount
            total_fee += fee
        
        print(f"\n  📈 Summary:")
        print(f"    Total Amount Sent: {self.format_xmr(total_amount_sent):.12f} XMR")
        print(f"    Total Fees: {self.format_xmr(total_fee):.12f} XMR")
        print(f"    Total Cost: {self.format_xmr(total_amount_sent + total_fee):.12f} XMR")
        
        print("\n" + "=" * 80 + "\n")
        return True

def main():
    parser = argparse.ArgumentParser(
        description="Transfer funds between Monero accounts (uses transfer_split)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Transfer 100000000000 atomic units (0.1 XMR) per address
  python3 transfer_split_accounts.py 0 1 100000000000

  # Transfer 1000000000 atomic units (0.001 XMR) per address
  python3 transfer_split_accounts.py 0 2 1000000000

  # Transfer 1 atomic unit (dust)
  python3 transfer_split_accounts.py 1 2 1

  # Custom wallet URL
  python3 transfer_split_accounts.py --wallet-url http://localhost:28088 0 1 100000000000
        """
    )
    
    parser.add_argument("from_account", type=int, help="Source account index")
    parser.add_argument("to_account", type=int, help="Destination account index")
    parser.add_argument("amount", type=int, 
                       help="Amount per address in atomic units (1 XMR = 1e12 atomic)")
    parser.add_argument("--wallet-url", type=str, default="http://127.0.0.1:28088",
                       help="Wallet RPC URL (default: http://127.0.0.1:28088)")
    
    args = parser.parse_args()
    
    if args.from_account == args.to_account:
        print("❌ Source and destination accounts must be different!")
        sys.exit(1)
    
    if args.amount <= 0:
        print("❌ Amount must be positive!")
        sys.exit(1)
    
    transfer = MoneroTransferSplit(args.wallet_url)
    success = transfer.transfer_between_accounts(args.from_account, args.to_account, args.amount)
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
